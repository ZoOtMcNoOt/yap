"""Safe AMI annotation parsing with explicit overlap-preserving word timing."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import PurePosixPath
import re
import stat
from xml.etree import ElementTree
import zipfile

from yap_server.evaluation.ami_meeting_lock import (
    EVENT_NAMES,
    MAX_ARCHIVE_MEMBER_BYTES,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    MAX_TRANSCRIPT_XML_BYTES,
    NITE_ROOT,
    AmiMeetingCorpusLock,
    AmiTranscriptMemberLock,
)


_MAX_COMPRESSION_RATIO = 64
_MAX_TRANSCRIPT_ELEMENTS = 10_000
_MAX_WORD_CHARACTERS = 512
_SOURCE_ID = re.compile(r"^ES2004a\.[A-D]\.words[0-9]+$")


@dataclass(frozen=True, slots=True)
class AmiTimedWord:
    agent_id: str
    source_id: str
    source_ordinal: int
    start_sample: int
    end_sample: int
    punctuation: bool
    truncated: bool
    mispronounced: bool
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AmiWordTimeline:
    meeting_id: str
    sample_rate_hz: int
    flat_ordering_policy: str
    words: tuple[AmiTimedWord, ...] = field(repr=False)
    vocal_sound_count: int
    disfluency_marker_count: int
    gap_count: int

    @property
    def merged_words(self) -> tuple[AmiTimedWord, ...]:
        """Return a deterministic scoring view, not inferred conversational turns."""

        return tuple(
            sorted(
                self.words,
                key=lambda word: (
                    word.start_sample,
                    word.end_sample,
                    word.agent_id,
                    word.source_ordinal,
                ),
            )
        )


def render_ami_scoring_reference(timeline: AmiWordTimeline) -> str:
    """Serialize every ordered word element for transcript scoring.

    Spaces delimit source elements, including punctuation elements. Yap's word
    and punctuation scorers interpret those marks at word boundaries, so this
    form is deterministic without pretending to recover speaker turns.
    """

    if not isinstance(timeline, AmiWordTimeline) or not timeline.words:
        raise ValueError("AMI scoring reference requires a non-empty timeline")
    return " ".join(word.text for word in timeline.merged_words)


def parse_ami_word_timeline(
    annotation_archive: bytes,
    lock: AmiMeetingCorpusLock,
) -> AmiWordTimeline:
    """Parse exact transcript members without extracting archive contents."""

    words: list[AmiTimedWord] = []
    event_totals = {name: 0 for name in EVENT_NAMES}
    source_ids: set[str] = set()
    try:
        with zipfile.ZipFile(BytesIO(annotation_archive)) as archive:
            _validate_annotation_archive(archive, lock)
            for member in lock.annotations.transcript_members:
                member_body = archive.read(member.archive_path)
                parsed_words, counts = _parse_transcript_member(
                    member_body,
                    member=member,
                    meeting_id=lock.identity.meeting_id,
                    sample_rate_hz=lock.audio.sample_rate_hz,
                    frame_count=lock.audio.frame_count,
                    source_ids=source_ids,
                )
                words.extend(parsed_words)
                for name in EVENT_NAMES:
                    event_totals[name] += counts[name]
    except (zipfile.BadZipFile, KeyError, RuntimeError, EOFError) as error:
        raise ValueError("AMI annotation archive is invalid") from error
    return AmiWordTimeline(
        meeting_id=lock.identity.meeting_id,
        sample_rate_hz=lock.audio.sample_rate_hz,
        flat_ordering_policy=lock.annotations.flat_ordering_policy,
        words=tuple(words),
        vocal_sound_count=event_totals["vocalsound"],
        disfluency_marker_count=event_totals["disfmarker"],
        gap_count=event_totals["gap"],
    )


def count_cross_speaker_overlap_words(words: tuple[AmiTimedWord, ...]) -> int:
    """Count timed words involved in a positive cross-speaker overlap."""

    active: list[AmiTimedWord] = []
    overlapping: set[str] = set()
    for word in words:
        active = [candidate for candidate in active if candidate.end_sample > word.start_sample]
        if word.end_sample > word.start_sample:
            for candidate in active:
                if candidate.agent_id != word.agent_id:
                    overlapping.add(candidate.source_id)
                    overlapping.add(word.source_id)
            active.append(word)
    return len(overlapping)


def _validate_annotation_archive(
    archive: zipfile.ZipFile,
    lock: AmiMeetingCorpusLock,
) -> None:
    members = archive.infolist()
    if len(members) != lock.annotations.member_count:
        raise ValueError("AMI annotation archive member count differs from the lock")
    seen: set[str] = set()
    total_size = 0
    for member in members:
        name = member.filename
        path = PurePosixPath(name)
        canonical_name = (
            f"{path.as_posix()}/" if member.is_dir() else path.as_posix()
        )
        mode = member.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (
            not name
            or name != canonical_name
            or "\0" in name
            or "\\" in name
            or ":" in name
            or path.is_absolute()
            or ".." in path.parts
            or name.casefold() in seen
            or member.flag_bits & 0x1
            or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            or member.file_size < 0
            or member.compress_size < 0
            or member.file_size > MAX_ARCHIVE_MEMBER_BYTES
            or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
            or (member.is_dir() != (kind == stat.S_IFDIR) and kind != 0)
        ):
            raise ValueError("AMI annotation archive member is unsafe")
        if member.file_size and (
            member.compress_size < 1
            or member.file_size > member.compress_size * _MAX_COMPRESSION_RATIO
        ):
            raise ValueError("AMI annotation archive compression ratio is unsafe")
        seen.add(name.casefold())
        total_size += member.file_size
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("AMI annotation archive expands beyond the bound")
    if total_size != lock.annotations.uncompressed_bytes:
        raise ValueError("AMI annotation archive size differs from the lock")
    by_name = {member.filename: member for member in members}
    for expected in lock.annotations.transcript_members:
        actual = by_name.get(expected.archive_path)
        if actual is None or actual.file_size != expected.size:
            raise ValueError("AMI transcript member differs from the lock")


def _parse_transcript_member(
    body: bytes,
    *,
    member: AmiTranscriptMemberLock,
    meeting_id: str,
    sample_rate_hz: int,
    frame_count: int,
    source_ids: set[str],
) -> tuple[tuple[AmiTimedWord, ...], dict[str, int]]:
    if not 1 <= len(body) <= MAX_TRANSCRIPT_XML_BYTES:
        raise ValueError("AMI transcript XML size is invalid")
    upper = body.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("AMI transcript XML declarations are unsafe")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError("AMI transcript XML is invalid") from error
    elements = list(root)
    if root.tag != NITE_ROOT or not 1 <= len(elements) <= _MAX_TRANSCRIPT_ELEMENTS:
        raise ValueError("AMI transcript XML structure is invalid")

    words: list[AmiTimedWord] = []
    counts = {name: 0 for name in EVENT_NAMES}
    previous_start = 0
    for ordinal, element in enumerate(elements):
        tag, attributes = _transcript_element(element)
        source_id, start, end = _timed_element(
            attributes,
            meeting_id=meeting_id,
            agent_id=member.agent_id,
            sample_rate_hz=sample_rate_hz,
            frame_count=frame_count,
            source_ids=source_ids,
        )
        if start > end or (ordinal and start < previous_start):
            raise ValueError("AMI transcript timing is invalid")
        previous_start = start
        text = (element.text or "").strip()
        if len(text) > _MAX_WORD_CHARACTERS:
            raise ValueError("AMI transcript element text exceeds the bound")

        if tag != "w":
            if tag == "vocalsound":
                _bounded_text(attributes["type"], "AMI vocal-sound type", 64)
            counts[tag] += 1
            continue
        if not text:
            raise ValueError("AMI word element contains no text")
        for flag in ("punc", "trunc", "mispronounced"):
            if flag in attributes and attributes[flag] != "true":
                raise ValueError("AMI transcript word flag is invalid")
        words.append(
            AmiTimedWord(
                agent_id=member.agent_id,
                source_id=source_id,
                source_ordinal=ordinal,
                start_sample=start,
                end_sample=end,
                punctuation="punc" in attributes,
                truncated="trunc" in attributes,
                mispronounced="mispronounced" in attributes,
                text=text,
            )
        )

    expected_counts = {
        "vocalsound": member.vocal_sound_count,
        "disfmarker": member.disfluency_marker_count,
        "gap": member.gap_count,
    }
    if len(words) != member.word_element_count or counts != expected_counts:
        raise ValueError("AMI transcript element counts differ from the lock")
    return tuple(words), counts


def _transcript_element(
    element: ElementTree.Element,
) -> tuple[str, dict[str, str]]:
    if list(element):
        raise ValueError("AMI transcript elements must not be nested")
    tag = _local_name(element.tag)
    attributes = {_local_name(key): value for key, value in element.attrib.items()}
    if len(attributes) != len(element.attrib):
        raise ValueError("AMI transcript attributes are ambiguous")
    required = {"id", "starttime", "endtime"}
    if tag == "w":
        allowed = required | {"punc", "trunc", "mispronounced"}
    elif tag == "vocalsound":
        allowed = required | {"type"}
    elif tag in {"disfmarker", "gap"}:
        allowed = required
    else:
        raise ValueError("AMI transcript element type is unsupported")
    if not required.issubset(attributes) or not set(attributes).issubset(allowed):
        raise ValueError("AMI transcript element attributes differ from the contract")
    return tag, attributes


def _timed_element(
    attributes: dict[str, str],
    *,
    meeting_id: str,
    agent_id: str,
    sample_rate_hz: int,
    frame_count: int,
    source_ids: set[str],
) -> tuple[str, int, int]:
    source_id = attributes["id"]
    if (
        _SOURCE_ID.fullmatch(source_id) is None
        or not source_id.startswith(f"{meeting_id}.{agent_id}.")
        or source_id in source_ids
    ):
        raise ValueError("AMI transcript source identity is invalid")
    source_ids.add(source_id)
    start = _sample_offset(
        attributes["starttime"],
        sample_rate_hz=sample_rate_hz,
        frame_count=frame_count,
    )
    end = _sample_offset(
        attributes["endtime"],
        sample_rate_hz=sample_rate_hz,
        frame_count=frame_count,
    )
    return source_id, start, end


def _sample_offset(value: str, *, sample_rate_hz: int, frame_count: int) -> int:
    if not isinstance(value, str) or len(value) > 32:
        raise ValueError("AMI transcript timestamp is invalid")
    try:
        seconds = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("AMI transcript timestamp is invalid") from error
    samples = seconds * sample_rate_hz
    if (
        not seconds.is_finite()
        or seconds < 0
        or samples != samples.to_integral_value()
    ):
        raise ValueError("AMI transcript timestamp is not sample-aligned")
    offset = int(samples)
    if offset > frame_count:
        raise ValueError("AMI transcript timestamp exceeds the audio")
    return offset


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must be bounded text")
    return value
