from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .component_lock import LidComponentLock
from .materialization import (
    LidMaterializedRequest,
    LidPcmProbe,
    materialize_lid_pcm_request,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
LID_PREFLIGHT_MEDIA_TYPE = (
    "application/vnd.yap.lid-preflight.v1+octet-stream"
)
MAX_LID_PREFLIGHT_BODY_BYTES = 1024 * 1024
MAX_LID_PREFLIGHT_MANIFEST_BYTES = 32 * 1024
_MAX_INTERVALS_PER_PROBE = 128
_MAX_SOURCE_SAMPLES = 16_000 * 4 * 60 * 60


class LidTransportError(ValueError):
    """The versioned desktop-to-server probe envelope is invalid."""


class LidTransportStaleError(LidTransportError):
    """The probe envelope targets a superseded catalog or policy."""


@dataclass(frozen=True)
class TransportVadInterval:
    start_sample: int
    end_sample_exclusive: int


@dataclass(frozen=True)
class LidTransportProbe:
    index: int
    source_start_sample: int
    source_end_sample: int
    voiced_samples: int
    pcm_sha256: str
    vad_intervals: tuple[TransportVadInterval, ...]
    pcm_bytes: bytes = field(repr=False)


@dataclass(frozen=True)
class LidTransportRequest:
    request_id: str
    source_samples: int
    source_pcm_sha256: str
    catalog_revision: str
    policy_revision: str
    probes: tuple[LidTransportProbe, ...]


def parse_lid_preflight_envelope(
    body: bytes,
    *,
    lock: LidComponentLock,
    expected_catalog_revision: str,
) -> LidTransportRequest:
    """Parse four-byte manifest length, strict JSON, then contiguous probe PCM."""

    if not isinstance(lock, LidComponentLock):
        raise TypeError("lock must be a validated LidComponentLock")
    if (
        not isinstance(body, bytes)
        or not 4 < len(body) <= MAX_LID_PREFLIGHT_BODY_BYTES
    ):
        raise LidTransportError("LID preflight envelope size is invalid")
    if _SHA256.fullmatch(expected_catalog_revision) is None:
        raise ValueError("expected ASR catalog revision is invalid")
    manifest_length = int.from_bytes(body[:4], "big")
    if not 1 <= manifest_length <= MAX_LID_PREFLIGHT_MANIFEST_BYTES:
        raise LidTransportError("LID preflight manifest size is invalid")
    manifest_end = 4 + manifest_length
    if manifest_end > len(body):
        raise LidTransportError("LID preflight manifest is truncated")
    try:
        payload = json.loads(
            body[4:manifest_end],
            object_pairs_hook=_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LidTransportError("LID preflight manifest is invalid JSON") from error
    root = _mapping(payload, "root")
    _exact_keys(
        root,
        {
            "schemaVersion",
            "requestId",
            "sourceSamples",
            "sourcePcmSha256",
            "catalogRevision",
            "policyRevision",
            "probes",
        },
        "root",
    )
    if _integer(root["schemaVersion"], "schemaVersion", 1) != 1:
        raise LidTransportError("unsupported LID preflight envelope schema")
    request_id = _string(root["requestId"], "requestId")
    if _REQUEST_ID.fullmatch(request_id) is None:
        raise LidTransportError("LID preflight request ID is invalid")
    source_samples = _integer(root["sourceSamples"], "sourceSamples", 1)
    if not lock.policy.minimum_source_samples <= source_samples <= _MAX_SOURCE_SAMPLES:
        raise LidTransportError("LID preflight source duration is invalid")
    source_pcm_sha256 = _sha256(root["sourcePcmSha256"], "sourcePcmSha256")
    catalog_revision = _sha256(root["catalogRevision"], "catalogRevision")
    if catalog_revision != expected_catalog_revision:
        raise LidTransportStaleError(
            "LID preflight ASR catalog revision is stale"
        )
    policy_revision = _string(root["policyRevision"], "policyRevision")
    if policy_revision != lock.policy.revision:
        raise LidTransportStaleError("LID preflight policy revision is stale")
    raw_probes = root["probes"]
    if not isinstance(raw_probes, list) or len(raw_probes) != lock.policy.maximum_windows:
        raise LidTransportError("LID preflight requires exactly five regions")

    cursor = manifest_end
    probes: list[LidTransportProbe] = []
    previous_end = 0
    for position, raw_probe in enumerate(raw_probes):
        field_name = f"probes[{position}]"
        probe = _mapping(raw_probe, field_name)
        _exact_keys(
            probe,
            {
                "index",
                "sourceStartSample",
                "sourceEndSample",
                "voicedSamples",
                "pcmByteLength",
                "pcmSha256",
                "vadIntervals",
            },
            field_name,
        )
        index = _integer(probe["index"], f"{field_name}.index", 0)
        start = _integer(
            probe["sourceStartSample"],
            f"{field_name}.sourceStartSample",
            0,
        )
        end = _integer(
            probe["sourceEndSample"],
            f"{field_name}.sourceEndSample",
            1,
        )
        voiced = _integer(
            probe["voicedSamples"],
            f"{field_name}.voicedSamples",
            1,
        )
        span = end - start
        if (
            index != position
            or start < previous_end
            or end > source_samples
            or span != lock.policy.maximum_window_samples
            or not lock.policy.minimum_voiced_samples_per_window <= voiced <= span
        ):
            raise LidTransportError("LID preflight probe window is invalid")
        byte_length = _integer(
            probe["pcmByteLength"],
            f"{field_name}.pcmByteLength",
            1,
        )
        if byte_length != span * lock.policy.sample_width_bytes:
            raise LidTransportError("LID preflight PCM length differs from its span")
        intervals = _vad_intervals(
            probe["vadIntervals"],
            field=field_name,
            window_start=start,
            window_end=end,
        )
        if sum(item.end_sample_exclusive - item.start_sample for item in intervals) != voiced:
            raise LidTransportError("LID preflight voiced evidence is inconsistent")
        pcm_end = cursor + byte_length
        if pcm_end > len(body):
            raise LidTransportError("LID preflight PCM is truncated")
        pcm = body[cursor:pcm_end]
        pcm_sha256 = _sha256(probe["pcmSha256"], f"{field_name}.pcmSha256")
        if hashlib.sha256(pcm).hexdigest() != pcm_sha256:
            raise LidTransportError("LID preflight PCM digest differs")
        probes.append(
            LidTransportProbe(
                index=index,
                source_start_sample=start,
                source_end_sample=end,
                voiced_samples=voiced,
                pcm_sha256=pcm_sha256,
                vad_intervals=intervals,
                pcm_bytes=pcm,
            )
        )
        cursor = pcm_end
        previous_end = end
    if cursor != len(body):
        raise LidTransportError("LID preflight envelope contains trailing bytes")
    return LidTransportRequest(
        request_id=request_id,
        source_samples=source_samples,
        source_pcm_sha256=source_pcm_sha256,
        catalog_revision=catalog_revision,
        policy_revision=policy_revision,
        probes=tuple(probes),
    )


def materialize_lid_transport_request(
    request: LidTransportRequest,
    *,
    destination: Path,
    lock: LidComponentLock,
    ensure_active: Callable[[], None] = lambda: None,
) -> LidMaterializedRequest:
    if not isinstance(request, LidTransportRequest):
        raise TypeError("request must be a validated LidTransportRequest")
    return materialize_lid_pcm_request(
        destination=destination,
        request_id=request.request_id,
        source_samples=request.source_samples,
        probes=tuple(
            LidPcmProbe(
                index=probe.index,
                source_start_sample=probe.source_start_sample,
                source_end_sample=probe.source_end_sample,
                voiced_samples=probe.voiced_samples,
                pcm_bytes=probe.pcm_bytes,
            )
            for probe in request.probes
        ),
        lock=lock,
        ensure_active=ensure_active,
    )


def _vad_intervals(
    value: object,
    *,
    field: str,
    window_start: int,
    window_end: int,
) -> tuple[TransportVadInterval, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_INTERVALS_PER_PROBE:
        raise LidTransportError("LID preflight VAD evidence is invalid")
    intervals: list[TransportVadInterval] = []
    previous_end = window_start
    for position, raw_interval in enumerate(value):
        interval_field = f"{field}.vadIntervals[{position}]"
        interval = _mapping(raw_interval, interval_field)
        _exact_keys(interval, {"startSample", "endSampleExclusive"}, interval_field)
        start = _integer(interval["startSample"], f"{interval_field}.startSample", 0)
        end = _integer(
            interval["endSampleExclusive"],
            f"{interval_field}.endSampleExclusive",
            1,
        )
        if start < previous_end or start >= end or end > window_end:
            raise LidTransportError("LID preflight VAD intervals are invalid")
        intervals.append(TransportVadInterval(start, end))
        previous_end = end
    return tuple(intervals)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LidTransportError(f"{field} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise LidTransportError(f"{field} fields are invalid")


def _integer(value: object, field: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise LidTransportError(f"{field} is invalid")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LidTransportError(f"{field} is invalid")
    return value


def _sha256(value: object, field: str) -> str:
    text = _string(value, field)
    if _SHA256.fullmatch(text) is None:
        raise LidTransportError(f"{field} is invalid")
    return text


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LidTransportError("LID preflight manifest contains duplicate keys")
        result[key] = value
    return result
