from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
import math
import re
from typing import Iterable
from urllib.parse import urlsplit


_MAX_HTML_CHARACTERS = 16 * 1024 * 1024
_MAX_SPEECH_ITEMS = 10_000
_LANGUAGE_CODE = re.compile(r"^[a-z]{2}$")
_MULTILINGUAL_MARKER = "xm"
_SPEECH_ARTIFACT_PATH = re.compile(
    r"^/sedcms/speech/(?P<date>[0-9]{8})/"
    r"(?P<item>[0-9]{8,24})_01_(?P<language>[a-z]{2})"
    r"\.(?P<extension>mpg|docx)$"
)
_PUBLISHED_DURATION = re.compile(
    r"\bLength\s+(?P<duration>[0-9]{2}:[0-9]{2}:[0-9]{2})\s+Start\b"
)


@dataclass(frozen=True, slots=True)
class EuropeanParliamentSpeech:
    item_id: str
    language_code: str
    recorded_date: date
    start_time: time
    end_time: time
    duration_seconds: int
    audio_source: str
    reference_source: str

    def recorded_at_utc(self, *, source_utc_offset_minutes: int) -> datetime:
        offset = _utc_offset(source_utc_offset_minutes)
        local = datetime.combine(self.recorded_date, self.start_time, tzinfo=offset)
        return local.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SpeechSourceTrim:
    start_seconds: float
    duration_seconds: float
    end_seconds: float


@dataclass(slots=True)
class _SpeechBlock:
    div_depth: int
    links: dict[str, list[str]]
    original_language_markers: list[str]
    datetimes: list[str]
    text: list[str]


class _SpeechIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_SpeechBlock] = []
        self._current: _SpeechBlock | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "div":
            if self._current is None:
                classes = set(attributes.get("class", "").split())
                if "notice_debates" in classes:
                    self._current = _SpeechBlock(
                        div_depth=1,
                        links={},
                        original_language_markers=[],
                        datetimes=[],
                        text=[],
                    )
                    return
            else:
                self._current.div_depth += 1
        current = self._current
        if current is None:
            return
        if tag == "a":
            title = attributes.get("title")
            href = attributes.get("href")
            # The Parliament index renders unavailable downloads as href="#".
            # Treat those placeholders as absent artifacts; real, malformed
            # artifact URLs remain fail-closed in _artifact_identity.
            if title in {"MPG", "TEXT"} and href and href != "#":
                current.links.setdefault(title, []).append(href)
            classes = set(attributes.get("class", "").split())
            language_markers = sorted(
                value
                for value in classes
                if value not in {"on", "default"}
                and _LANGUAGE_CODE.fullmatch(value)
            )
            if {"on", "default"}.issubset(classes) and language_markers:
                current.original_language_markers.extend(language_markers)
        elif tag == "time":
            value = attributes.get("datetime")
            if value:
                current.datetimes.append(value)

    def handle_endtag(self, tag: str) -> None:
        current = self._current
        if current is None or tag != "div":
            return
        current.div_depth -= 1
        if current.div_depth == 0:
            self.blocks.append(current)
            if len(self.blocks) > _MAX_SPEECH_ITEMS:
                raise ValueError("European Parliament speech index exceeds the bound")
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None and data.strip():
            self._current.text.append(data)

    def close(self) -> None:
        super().close()
        if self._current is not None:
            raise ValueError("European Parliament speech index has an open speech block")


def parse_european_parliament_speech_index(
    html: str,
) -> tuple[EuropeanParliamentSpeech, ...]:
    """Parse paired original-language speech artifacts without exposing text."""

    if not isinstance(html, str) or not 1 <= len(html) <= _MAX_HTML_CHARACTERS:
        raise ValueError("European Parliament speech index size is invalid")
    parser = _SpeechIndexParser()
    try:
        parser.feed(html)
        parser.close()
    except (UnicodeError, ValueError) as error:
        raise ValueError("European Parliament speech index is invalid") from error

    items: list[EuropeanParliamentSpeech] = []
    identities: set[tuple[date, str]] = set()
    for block in parser.blocks:
        has_audio = bool(block.links.get("MPG"))
        has_reference = bool(block.links.get("TEXT"))
        if not has_audio and not has_reference:
            continue
        if not has_audio or not has_reference:
            continue
        # XM is Parliament's multilingual marker. A concrete artifact suffix
        # cannot establish that the whole intervention is monolingual, so XM
        # blocks are deliberately outside this language-specific screen.
        if block.original_language_markers == [_MULTILINGUAL_MARKER]:
            continue
        item = _speech_item(block)
        if item is None:
            continue
        identity = (item.recorded_date, item.item_id)
        if identity in identities:
            raise ValueError("European Parliament speech identity is duplicated")
        identities.add(identity)
        items.append(item)
    if not items:
        raise ValueError("European Parliament speech index has no paired speeches")
    return tuple(items)


def select_post_freeze_speeches(
    items: Iterable[EuropeanParliamentSpeech],
    *,
    language_codes: Iterable[str],
    frozen_at_utc: datetime,
    source_utc_offset_minutes: int,
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
    per_language: int = 1,
) -> tuple[EuropeanParliamentSpeech, ...]:
    """Select a deterministic bounded post-freeze screen for each language."""

    if (
        not isinstance(frozen_at_utc, datetime)
        or frozen_at_utc.tzinfo is None
        or frozen_at_utc.utcoffset() is None
    ):
        raise ValueError("candidate freeze time must be timezone-aware")
    frozen_at_utc = frozen_at_utc.astimezone(timezone.utc)
    _utc_offset(source_utc_offset_minutes)
    if (
        isinstance(minimum_duration_seconds, bool)
        or not isinstance(minimum_duration_seconds, int)
        or isinstance(maximum_duration_seconds, bool)
        or not isinstance(maximum_duration_seconds, int)
        or not 1 <= minimum_duration_seconds <= maximum_duration_seconds <= 3_600
        or isinstance(per_language, bool)
        or not isinstance(per_language, int)
        or not 1 <= per_language <= 8
    ):
        raise ValueError("European Parliament speech selection bounds are invalid")
    languages = tuple(language_codes)
    if (
        not languages
        or len(languages) > 64
        or len(set(languages)) != len(languages)
        or any(_LANGUAGE_CODE.fullmatch(value) is None for value in languages)
    ):
        raise ValueError("European Parliament language selection is invalid")

    candidates = sorted(
        (
            item
            for item in items
            if minimum_duration_seconds
            <= item.duration_seconds
            <= maximum_duration_seconds
            and item.recorded_at_utc(
                source_utc_offset_minutes=source_utc_offset_minutes
            )
            > frozen_at_utc
        ),
        key=lambda item: (
            item.recorded_date,
            item.start_time,
            item.item_id,
        ),
    )
    selected: list[EuropeanParliamentSpeech] = []
    missing: list[str] = []
    for language in languages:
        matches = [item for item in candidates if item.language_code == language]
        if len(matches) < per_language:
            missing.append(language)
        else:
            selected.extend(matches[:per_language])
    if missing:
        raise ValueError(
            "European Parliament post-freeze selection is missing languages: "
            + ", ".join(missing)
        )
    return tuple(selected)


def validate_source_trim(
    *,
    published_duration_seconds: int,
    decoded_source_duration_seconds: float,
    leading_padding_seconds: float,
    trailing_padding_seconds: float,
    tolerance_seconds: float = 0.05,
) -> SpeechSourceTrim:
    """Validate an explicit source-time trim before adjacent speech is removed."""

    values = (
        decoded_source_duration_seconds,
        leading_padding_seconds,
        trailing_padding_seconds,
        tolerance_seconds,
    )
    if (
        isinstance(published_duration_seconds, bool)
        or not isinstance(published_duration_seconds, int)
        or not 1 <= published_duration_seconds <= 3_600
        or any(not isinstance(value, (int, float)) for value in values)
        or any(not math.isfinite(float(value)) for value in values)
        or leading_padding_seconds < 0
        or trailing_padding_seconds < 0
        or not 0 < tolerance_seconds <= 1
    ):
        raise ValueError("European Parliament source trim is invalid")
    expected = (
        float(leading_padding_seconds)
        + published_duration_seconds
        + float(trailing_padding_seconds)
    )
    if abs(float(decoded_source_duration_seconds) - expected) > tolerance_seconds:
        raise ValueError(
            "European Parliament source duration differs from the frozen trim"
        )
    start = float(leading_padding_seconds)
    duration = float(published_duration_seconds)
    return SpeechSourceTrim(
        start_seconds=start,
        duration_seconds=duration,
        end_seconds=start + duration,
    )


def _speech_item(block: _SpeechBlock) -> EuropeanParliamentSpeech | None:
    audio_source = _one(block.links.get("MPG", []), "speech audio")
    reference_source = _one(block.links.get("TEXT", []), "speech reference")
    audio_identity = _artifact_identity(audio_source, expected_extension="mpg")
    reference_identity = _artifact_identity(
        reference_source,
        expected_extension="docx",
    )
    if audio_identity[:3] != reference_identity[:3]:
        raise ValueError("European Parliament speech artifacts disagree")
    recorded_date, item_id, language_code, _extension = audio_identity
    marker = _one(block.original_language_markers, "original language marker")
    if marker != language_code:
        raise ValueError("European Parliament original language marker disagrees")
    if len(block.datetimes) != 3:
        raise ValueError("European Parliament speech times are invalid")
    try:
        displayed_date = date.fromisoformat(block.datetimes[0])
        start = datetime.fromisoformat(block.datetimes[1])
        end = datetime.fromisoformat(block.datetimes[2])
    except ValueError as error:
        raise ValueError("European Parliament speech times are invalid") from error
    if (
        displayed_date != recorded_date
        or start.tzinfo is not None
        or end.tzinfo is not None
        or start.date() != recorded_date
        or end.date() != recorded_date
    ):
        raise ValueError("European Parliament speech times disagree")
    text = " ".join(" ".join(block.text).split())
    matched_duration = _PUBLISHED_DURATION.search(text)
    if matched_duration is None:
        raise ValueError("European Parliament speech duration is missing")
    duration_seconds = _hms_seconds(matched_duration.group("duration"))
    if end == start and duration_seconds == 0:
        # The live index can retain paired download links for a speech whose
        # published timing was reduced to a zero-length placeholder.
        return None
    if end <= start or int((end - start).total_seconds()) != duration_seconds:
        raise ValueError("European Parliament speech duration disagrees")
    return EuropeanParliamentSpeech(
        item_id=item_id,
        language_code=language_code,
        recorded_date=recorded_date,
        start_time=start.time(),
        end_time=end.time(),
        duration_seconds=duration_seconds,
        audio_source=audio_source,
        reference_source=reference_source,
    )


def _artifact_identity(
    source: str,
    *,
    expected_extension: str,
) -> tuple[date, str, str, str]:
    try:
        parsed = urlsplit(source)
    except ValueError as error:
        raise ValueError("European Parliament speech artifact URL is invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.europarl.europa.eu"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("European Parliament speech artifact URL is invalid")
    matched = _SPEECH_ARTIFACT_PATH.fullmatch(parsed.path)
    if matched is None or matched.group("extension") != expected_extension:
        raise ValueError("European Parliament speech artifact path is invalid")
    raw_date = matched.group("date")
    try:
        recorded_date = datetime.strptime(raw_date, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError("European Parliament speech artifact date is invalid") from error
    return (
        recorded_date,
        matched.group("item"),
        matched.group("language"),
        matched.group("extension"),
    )


def _hms_seconds(value: str) -> int:
    hours, minutes, seconds = (int(component) for component in value.split(":"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError("European Parliament speech duration is invalid")
    return hours * 3_600 + minutes * 60 + seconds


def _one(values: list[str], field: str) -> str:
    if len(values) != 1:
        raise ValueError(f"European Parliament {field} is not unique")
    return values[0]


def _utc_offset(minutes: int) -> timezone:
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, int)
        or not -720 <= minutes <= 840
    ):
        raise ValueError("European Parliament source UTC offset is invalid")
    return timezone(timedelta(minutes=minutes))
