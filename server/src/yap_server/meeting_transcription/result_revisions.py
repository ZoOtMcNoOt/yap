from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from yap_server.alignment_contract import (
    JOINT_SEGMENT_TIMING_REVISION,
    AlignmentUnavailableReason,
    unavailable_alignment,
)
from yap_server.meeting_transcription.runtime_provenance import (
    MeetingRuntimeProvenance,
    load_meeting_runtime_provenance,
)
from yap_server.jobs.contract_values import (
    exact_keys,
    identifier,
    language_tag,
    mapping,
    utc_timestamp,
    valid_sha256,
)
from yap_server.transcript_text import canonical_transcript

from .contract import (
    MAX_MEETING_SEGMENT_COUNT,
    MAX_MEETING_SPEAKERS,
    MEETING_SAMPLE_RATE_HZ,
)

_SPEAKER_CAPACITY_LIMIT = MAX_MEETING_SPEAKERS
_SPEAKER_CAPACITY_CODE = "SPEAKER_CAPACITY_REACHED"
_SPEAKER_CAPACITY_FALLBACK = "not_run_recommended"
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MAX_MODEL_PROVENANCE_CHARS = 256


@dataclass(frozen=True, slots=True)
class MeetingResultAuthority:
    provenance: MeetingRuntimeProvenance
    runtime_lock_sha256: str


def load_meeting_result_authority(path: Path) -> MeetingResultAuthority:
    resolved = path.resolve(strict=True)
    contents = resolved.read_bytes()
    if len(contents) > 256 * 1024:
        raise ValueError("meeting runtime lock exceeds the bounded contract")
    return MeetingResultAuthority(
        provenance=load_meeting_runtime_provenance(resolved),
        runtime_lock_sha256=hashlib.sha256(contents).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class MeetingResultContext:
    job_id: str
    session_id: str
    created_at_utc: str
    capture_manifest_sha256: str
    language_bcp47: str
    provider_language: str
    source_track_ids: tuple[str, ...]
    maximum_end_ms: int
    source_frame_count: int

    def __post_init__(self) -> None:
        identifier(self.job_id, 128, "meeting result job ID")
        identifier(self.session_id, 128, "meeting result session ID")
        utc_timestamp(self.created_at_utc, "meeting result creation time")
        if not valid_sha256(self.capture_manifest_sha256):
            raise ValueError("meeting result capture identity is invalid")
        language_tag(self.language_bcp47, "meeting result language")
        if (
            not isinstance(self.provider_language, str)
            or not self.provider_language
            or len(self.provider_language) > 35
        ):
            raise ValueError("meeting provider language is invalid")
        if (
            not self.source_track_ids
            or len(self.source_track_ids) > 2
            or len(set(self.source_track_ids)) != len(self.source_track_ids)
        ):
            raise ValueError("meeting result source tracks are invalid")
        for track_id in self.source_track_ids:
            identifier(track_id, 128, "meeting result source track ID")
        if (
            not isinstance(self.maximum_end_ms, int)
            or isinstance(self.maximum_end_ms, bool)
            or self.maximum_end_ms < 1
        ):
            raise ValueError("meeting result duration is invalid")
        if (
            not isinstance(self.source_frame_count, int)
            or isinstance(self.source_frame_count, bool)
            or self.source_frame_count < 1
        ):
            raise ValueError("meeting result source frame count is invalid")

    @classmethod
    def from_job(
        cls,
        *,
        projection: Mapping[str, object],
        creation: Mapping[str, object],
        created_at_utc: str,
        language_bcp47: str,
        provider_language: str,
        maximum_end_ms: int,
    ) -> MeetingResultContext:
        capture_manifest = mapping(
            projection.get("captureManifest"),
            "meeting result capture manifest",
        )
        tracks = creation.get("tracks")
        if not isinstance(tracks, list):
            raise ValueError("meeting result source tracks are invalid")
        job_id = projection.get("jobId")
        session_id = projection.get("sessionId")
        capture_sha256 = capture_manifest.get("sha256")
        if not isinstance(job_id, str) or not isinstance(session_id, str):
            raise ValueError("meeting result job identity is invalid")
        if not isinstance(capture_sha256, str):
            raise ValueError("meeting result capture identity is invalid")
        source_track_ids: list[str] = []
        for track in tracks:
            track_id = mapping(track, "meeting result source track").get("trackId")
            if not isinstance(track_id, str):
                raise ValueError("meeting result source tracks are invalid")
            source_track_ids.append(track_id)
        chunks = creation.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("meeting result source chunks are invalid")
        source_frame_count = 0
        for raw_chunk in chunks:
            content_identity = mapping(
                mapping(raw_chunk, "meeting result source chunk").get(
                    "contentIdentity"
                ),
                "meeting result source content identity",
            )
            byte_length = content_identity.get("byteLength")
            if (
                not isinstance(byte_length, int)
                or isinstance(byte_length, bool)
                or byte_length < 2
                or byte_length % 2 != 0
            ):
                raise ValueError("meeting result source frame count is invalid")
            source_frame_count += byte_length // 2
        return cls(
            job_id=job_id,
            session_id=session_id,
            created_at_utc=created_at_utc,
            capture_manifest_sha256=capture_sha256,
            language_bcp47=language_bcp47,
            provider_language=provider_language,
            source_track_ids=tuple(source_track_ids),
            maximum_end_ms=maximum_end_ms,
            source_frame_count=source_frame_count,
        )


def build_meeting_result_revisions(
    worker_result: Mapping[str, object],
    *,
    context: MeetingResultContext,
    authority: MeetingResultAuthority,
) -> tuple[dict[str, object], dict[str, object]]:
    exact_keys(
        worker_result,
        {
            "schemaVersion",
            "jobId",
            "captureManifestSha256",
            "model",
            "audio",
            "meeting",
            "runtime",
        },
        "meeting worker result",
    )
    model = mapping(worker_result.get("model"), "meeting worker model")
    audio = mapping(worker_result.get("audio"), "meeting worker audio")
    meeting = mapping(worker_result.get("meeting"), "meeting worker output")
    if (
        worker_result.get("schemaVersion") != 1
        or worker_result.get("jobId") != context.job_id
        or worker_result.get("captureManifestSha256") != context.capture_manifest_sha256
    ):
        raise ValueError("meeting worker capture identity differs from the job")
    exact_keys(
        model,
        {
            "id",
            "revision",
            "runtimeHarnessRevision",
            "speakerEncoderRevision",
            "runtimeLockSha256",
        },
        "meeting worker model",
    )
    runtime_lock_sha256 = model.get("runtimeLockSha256")
    if (
        not valid_sha256(runtime_lock_sha256)
        or runtime_lock_sha256 != authority.runtime_lock_sha256
    ):
        raise ValueError("meeting worker runtime lock identity is invalid")
    if (
        model.get("id") != authority.provenance.model.identifier
        or model.get("revision") != authority.provenance.model.revision
        or model.get("runtimeHarnessRevision") != authority.provenance.harness.revision
        or model.get("speakerEncoderRevision")
        != authority.provenance.speaker_encoder.revision
    ):
        raise ValueError("meeting worker provenance differs from the pinned runtime")
    if meeting.get("language") != context.provider_language:
        raise ValueError("meeting worker language differs from the frozen route")
    if audio.get("frameCount") != context.source_frame_count:
        raise ValueError("meeting worker audio differs from the frozen source")

    speakers = meeting.get("speakers")
    if (
        not isinstance(speakers, list)
        or len(speakers) > _SPEAKER_CAPACITY_LIMIT
        or speakers != sorted(set(speakers))
    ):
        raise ValueError("meeting worker speaker inventory is invalid")
    speaker_capacity_degradation = _speaker_capacity_degradation(
        observed_speaker_count=len(speakers),
        source_frame_count=context.source_frame_count,
    )
    result_status = (
        "partial" if speaker_capacity_degradation is not None else "complete"
    )

    raw_segments = meeting.get("segments")
    if (
        not isinstance(raw_segments, list)
        or len(raw_segments) > MAX_MEETING_SEGMENT_COUNT
    ):
        raise ValueError("meeting worker segments are invalid")
    segments = [mapping(value, "meeting worker segment") for value in raw_segments]
    segment_texts = [
        _canonical_segment_text(segment.get("text"), index)
        for index, segment in enumerate(segments)
    ]
    transcript = canonical_transcript(
        " ".join(segment_texts),
        "joint meeting transcript",
    )
    model_provenance = _model_provenance(
        authority.provenance,
        str(runtime_lock_sha256),
    )
    alignment = unavailable_alignment(
        AlignmentUnavailableReason.PROVIDER_UNSUPPORTED,
        component_revision=JOINT_SEGMENT_TIMING_REVISION,
    )
    turns = _speaker_turns(segments, segment_texts, context)
    speaker_result: dict[str, object] = {
        **_revision_identity(context, status=result_status),
        "language": {
            "languageBcp47": context.language_bcp47,
            "confidence": None,
        },
        "runtimeLockSha256": runtime_lock_sha256,
        "speakerTurns": turns,
        "speakerCapacityDegradation": speaker_capacity_degradation,
        "alignment": {
            "status": alignment["status"],
            "reason": alignment["reason"],
            "componentRevision": alignment["componentRevision"],
        },
        "alignedWords": [],
        "modelProvenance": model_provenance,
    }
    transcript_result: dict[str, object] = {
        **_revision_identity(context, status=result_status),
        "language": {
            "languageBcp47": context.language_bcp47,
            "confidence": None,
        },
        "transcript": transcript,
        "speakerResultSha256": speaker_result_sha256(speaker_result),
        "alignment": {
            "status": alignment["status"],
            "reason": alignment["reason"],
            "componentRevision": alignment["componentRevision"],
        },
        "alignedWords": [],
        "modelProvenance": [model_provenance[0]],
    }
    validate_speaker_result_revision(
        speaker_result,
        transcript_result=transcript_result,
        context=context,
        authority=authority,
    )
    return transcript_result, speaker_result


def validate_speaker_result_revision(
    value: Mapping[str, object],
    *,
    transcript_result: Mapping[str, object],
    context: MeetingResultContext,
    authority: MeetingResultAuthority,
) -> None:
    _validate_speaker_result_revision(
        value,
        transcript_result=transcript_result,
        context=context,
        expected_runtime_lock_sha256=authority.runtime_lock_sha256,
        expected_model_provenance=_model_provenance(
            authority.provenance,
            authority.runtime_lock_sha256,
        ),
    )


def validate_persisted_speaker_result_revision(
    value: Mapping[str, object],
    *,
    transcript_result: Mapping[str, object],
    context: MeetingResultContext,
    route_model_revision: str,
) -> None:
    """Validate an immutable result against its frozen job, not today's lock."""

    runtime_lock_sha256 = value.get("runtimeLockSha256")
    model_provenance = _persisted_model_provenance(
        value.get("modelProvenance"),
        runtime_lock_sha256=runtime_lock_sha256,
        route_model_revision=route_model_revision,
    )
    _validate_speaker_result_revision(
        value,
        transcript_result=transcript_result,
        context=context,
        expected_runtime_lock_sha256=runtime_lock_sha256,
        expected_model_provenance=model_provenance,
    )


def _validate_speaker_result_revision(
    value: Mapping[str, object],
    *,
    transcript_result: Mapping[str, object],
    context: MeetingResultContext,
    expected_runtime_lock_sha256: str,
    expected_model_provenance: list[dict[str, str]],
) -> None:
    exact_keys(
        value,
        {
            "sessionId",
            "revision",
            "authority",
            "createdAtUtc",
            "captureManifestSha256",
            "previousResultSha256",
            "status",
            "language",
            "runtimeLockSha256",
            "speakerTurns",
            "speakerCapacityDegradation",
            "alignment",
            "alignedWords",
            "modelProvenance",
        },
        "speaker result revision",
    )
    observed_status = value.get("status")
    if not isinstance(observed_status, str):
        raise ValueError("speaker result revision status is invalid")
    expected_identity = _revision_identity(context, status=observed_status)
    if any(
        value.get(field) != expected for field, expected in expected_identity.items()
    ):
        raise ValueError("speaker result revision identity is invalid")
    if (
        not valid_sha256(expected_runtime_lock_sha256)
        or value.get("runtimeLockSha256") != expected_runtime_lock_sha256
        or transcript_result.get("speakerResultSha256") != speaker_result_sha256(value)
        or transcript_result.get("status") != observed_status
    ):
        raise ValueError("speaker result companion identity is invalid")
    _validate_speaker_capacity_degradation(
        value.get("speakerCapacityDegradation"),
        status=value.get("status"),
        source_frame_count=context.source_frame_count,
    )
    capacity_reached = value.get("speakerCapacityDegradation") is not None
    language = mapping(value.get("language"), "speaker result language")
    exact_keys(language, {"languageBcp47", "confidence"}, "speaker result language")
    if (
        language.get("languageBcp47") != context.language_bcp47
        or language.get("confidence") is not None
    ):
        raise ValueError("speaker result language is invalid")

    turns = value.get("speakerTurns")
    if not isinstance(turns, list) or len(turns) > MAX_MEETING_SEGMENT_COUNT:
        raise ValueError("speaker result turns are invalid")
    intervals: list[tuple[int, int]] = []
    observed_speakers: set[str] = set()
    rendered_text: list[str] = []
    previous_start = -1
    for index, raw_turn in enumerate(turns):
        turn = mapping(raw_turn, "speaker result turn")
        exact_keys(
            turn,
            {
                "turnId",
                "startMs",
                "endMs",
                "text",
                "attribution",
                "confidence",
                "supportingTrackIds",
                "overlapGroupId",
            },
            "speaker result turn",
        )
        start = turn.get("startMs")
        end = turn.get("endMs")
        text = canonical_transcript(
            turn.get("text"),
            "speaker result turn text",
        )
        if (
            turn.get("turnId") != f"turn-{index + 1:06d}"
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < previous_start
            or start < 0
            or end <= start
            or end > context.maximum_end_ms
            or turn.get("confidence") is not None
            or turn.get("supportingTrackIds") != list(context.source_track_ids)
            or not text
        ):
            raise ValueError("speaker result turn is invalid")
        attribution = mapping(turn.get("attribution"), "speaker attribution")
        exact_keys(
            attribution,
            {"kind", "sessionSpeakerId"},
            "speaker attribution",
        )
        speaker_id = attribution.get("sessionSpeakerId")
        if (
            attribution.get("kind") != "session_speaker"
            or not isinstance(speaker_id, str)
            or speaker_id not in {f"speaker-{number}" for number in range(1, 9)}
        ):
            raise ValueError("speaker result attribution is invalid")
        observed_speakers.add(speaker_id)
        rendered_text.append(text)
        previous_start = start
        intervals.append((start, end))
    if len(observed_speakers) > 8:
        raise ValueError("speaker result exceeds the released speaker boundary")
    if capacity_reached != (len(observed_speakers) == _SPEAKER_CAPACITY_LIMIT):
        raise ValueError("speaker capacity degradation differs from the roster")
    if " ".join(rendered_text) != transcript_result.get("transcript"):
        raise ValueError("speaker result text differs from the transcript")
    expected_overlap_groups = _overlap_group_ids(intervals)
    if [turn.get("overlapGroupId") for turn in turns] != expected_overlap_groups:
        raise ValueError("speaker result overlap groups are invalid")

    alignment = mapping(value.get("alignment"), "speaker result alignment")
    if (
        alignment
        != {
            "status": "unavailable",
            "reason": AlignmentUnavailableReason.PROVIDER_UNSUPPORTED.value,
            "componentRevision": JOINT_SEGMENT_TIMING_REVISION,
        }
        or value.get("alignedWords") != []
    ):
        raise ValueError("speaker result alignment is invalid")
    if value.get(
        "modelProvenance"
    ) != expected_model_provenance or transcript_result.get("modelProvenance") != [
        expected_model_provenance[0]
    ]:
        raise ValueError("speaker result model provenance is invalid")


def speaker_result_sha256(value: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("speaker result cannot be encoded canonically") from error
    return hashlib.sha256(encoded).hexdigest()


def _revision_identity(
    context: MeetingResultContext,
    *,
    status: str,
) -> dict[str, object]:
    if status not in {"complete", "partial"}:
        raise ValueError("meeting result status is invalid")
    return {
        "sessionId": context.session_id,
        "revision": 1,
        "authority": "server_authoritative",
        "createdAtUtc": context.created_at_utc,
        "captureManifestSha256": context.capture_manifest_sha256,
        "previousResultSha256": None,
        "status": status,
    }


def _speaker_capacity_degradation(
    *,
    observed_speaker_count: int,
    source_frame_count: int,
) -> dict[str, object] | None:
    if observed_speaker_count < _SPEAKER_CAPACITY_LIMIT:
        return None
    return {
        "code": _SPEAKER_CAPACITY_CODE,
        "fallbackDisposition": _SPEAKER_CAPACITY_FALLBACK,
        "scope": "meeting",
        "startSample": 0,
        "endSample": source_frame_count,
        "observedSpeakerCount": _SPEAKER_CAPACITY_LIMIT,
        "speakerLimit": _SPEAKER_CAPACITY_LIMIT,
    }


def _validate_speaker_capacity_degradation(
    value: object,
    *,
    status: object,
    source_frame_count: int,
) -> None:
    if value is None:
        if status != "complete":
            raise ValueError("partial speaker result omitted capacity degradation")
        return
    if status != "partial":
        raise ValueError("complete speaker result contains capacity degradation")
    degradation = mapping(value, "speaker capacity degradation")
    exact_keys(
        degradation,
        {
            "code",
            "fallbackDisposition",
            "scope",
            "startSample",
            "endSample",
            "observedSpeakerCount",
            "speakerLimit",
        },
        "speaker capacity degradation",
    )
    if (
        degradation.get("code") != _SPEAKER_CAPACITY_CODE
        or degradation.get("fallbackDisposition") != _SPEAKER_CAPACITY_FALLBACK
    ):
        raise ValueError("speaker capacity degradation identity is invalid")
    if degradation != {
        "code": _SPEAKER_CAPACITY_CODE,
        "fallbackDisposition": _SPEAKER_CAPACITY_FALLBACK,
        "scope": "meeting",
        "startSample": 0,
        "endSample": source_frame_count,
        "observedSpeakerCount": _SPEAKER_CAPACITY_LIMIT,
        "speakerLimit": _SPEAKER_CAPACITY_LIMIT,
    }:
        raise ValueError("speaker capacity degradation is not source-bound")


def _model_provenance(
    provenance: MeetingRuntimeProvenance,
    runtime_lock_sha256: str,
) -> list[dict[str, str]]:
    return [
        {
            "modelId": component.identifier,
            "revision": component.revision,
            "calibrationRevision": runtime_lock_sha256,
        }
        for component in (
            provenance.model,
            provenance.harness,
            provenance.speaker_encoder,
        )
    ]


def _persisted_model_provenance(
    value: object,
    *,
    runtime_lock_sha256: object,
    route_model_revision: str,
) -> list[dict[str, str]]:
    if not valid_sha256(runtime_lock_sha256):
        raise ValueError("persisted meeting runtime lock identity is invalid")
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("persisted meeting model provenance is invalid")
    parsed: list[dict[str, str]] = []
    for raw_component in value:
        component = mapping(raw_component, "persisted meeting model provenance")
        exact_keys(
            component,
            {"modelId", "revision", "calibrationRevision"},
            "persisted meeting model provenance",
        )
        model_id = component.get("modelId")
        revision = component.get("revision")
        calibration_revision = component.get("calibrationRevision")
        if (
            not isinstance(model_id, str)
            or not model_id
            or len(model_id) > _MAX_MODEL_PROVENANCE_CHARS
            or not isinstance(revision, str)
            or _GIT_REVISION.fullmatch(revision) is None
            or calibration_revision != runtime_lock_sha256
        ):
            raise ValueError("persisted meeting model provenance is invalid")
        parsed.append(
            {
                "modelId": model_id,
                "revision": revision,
                "calibrationRevision": str(runtime_lock_sha256),
            }
        )
    if parsed[0]["revision"] != route_model_revision or len(
        {component["modelId"] for component in parsed}
    ) != len(parsed):
        raise ValueError(
            "persisted meeting model provenance differs from the frozen route"
        )
    return parsed


def _speaker_turns(
    segments: list[Mapping[str, object]],
    segment_texts: list[str],
    context: MeetingResultContext,
) -> list[dict[str, object]]:
    speaker_labels = sorted({str(segment.get("speaker")) for segment in segments})
    speaker_ids = {
        label: f"speaker-{index + 1}" for index, label in enumerate(speaker_labels)
    }
    intervals = [
        (
            _sample_to_ms(segment.get("startSample")),
            _sample_to_ms(segment.get("endSample")),
        )
        for segment in segments
    ]
    overlap_groups = _overlap_group_ids(intervals)
    return [
        {
            "turnId": f"turn-{index + 1:06d}",
            "startMs": intervals[index][0],
            "endMs": intervals[index][1],
            "text": segment_texts[index],
            "attribution": {
                "kind": "session_speaker",
                "sessionSpeakerId": speaker_ids[str(segment.get("speaker"))],
            },
            "confidence": None,
            "supportingTrackIds": list(context.source_track_ids),
            "overlapGroupId": overlap_groups[index],
        }
        for index, segment in enumerate(segments)
    ]


def _canonical_segment_text(value: object, index: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"meeting worker segment {index} text is invalid")
    normalized = " ".join(value.split())
    text = canonical_transcript(normalized, f"meeting worker segment {index} text")
    if not text:
        raise ValueError(f"meeting worker segment {index} text is invalid")
    return text


def _sample_to_ms(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("meeting segment source sample is invalid")
    return round(value * 1_000 / MEETING_SAMPLE_RATE_HZ)


def _overlap_group_ids(
    intervals: list[tuple[int, int]],
) -> list[str | None]:
    groups: list[str | None] = [None] * len(intervals)
    group_number = 0
    start = 0
    while start < len(intervals):
        end = start + 1
        maximum_end = intervals[start][1]
        while end < len(intervals) and intervals[end][0] < maximum_end:
            maximum_end = max(maximum_end, intervals[end][1])
            end += 1
        if end - start > 1:
            group_number += 1
            group_id = f"overlap-{group_number:06d}"
            groups[start:end] = [group_id] * (end - start)
        start = end
    return groups
