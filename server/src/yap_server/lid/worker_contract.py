from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
from typing import Any, Protocol
import wave

from yap_server.bounded_file import read_regular_file, read_regular_text

from .component_lock import LidComponentLock


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_WAV_OVERHEAD_BYTES = 64 * 1024
_MAX_RAW_LABEL_LENGTH = 128


class WorkerInputError(ValueError):
    """A request is outside the isolated LID worker's bounded contract."""


class WorkerResultError(ValueError):
    """A worker result differs from the host's locked request and component."""


@dataclass(frozen=True)
class LidProbeReference:
    index: int
    file_name: str
    wav_sha256: str
    source_start_sample: int
    source_end_sample: int
    voiced_samples: int


@dataclass(frozen=True)
class LidWorkerRequest:
    request_id: str
    source_samples: int
    probes: tuple[LidProbeReference, ...]


@dataclass(frozen=True)
class ProbeAudio:
    pcm_bytes: bytes
    frame_count: int
    wav_sha256: str


@dataclass(frozen=True)
class LidClassification:
    raw_label: str
    top_score: float
    score_margin: float


class LidClassifier(Protocol):
    def classify(self, audio: ProbeAudio) -> LidClassification:
        """Classify one already validated mono PCM16/16-kHz probe."""


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerInputError(f"{field} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    unexpected = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unexpected:
        raise WorkerInputError(f"{field} contains unexpected fields")
    if missing:
        raise WorkerInputError(f"{field} is missing required fields")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerInputError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise WorkerInputError(f"{field} must be an integer of at least {minimum}")
    return value


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_request_payload(path: Path) -> dict[str, Any]:
    try:
        text = read_regular_text(path, _MAX_REQUEST_BYTES)
        payload = json.loads(text, object_pairs_hook=_without_duplicate_keys)
    except (json.JSONDecodeError, UnicodeError, ValueError) as error:
        if isinstance(error, WorkerInputError):
            raise
        raise WorkerInputError("LID request is missing, unsafe, or invalid") from error
    return _mapping(payload, "root")


def load_lid_worker_request(
    path: Path,
    lock: LidComponentLock,
) -> LidWorkerRequest:
    """Load a bounded request that can reference only fixed probe file names."""

    payload = _read_request_payload(path)
    _exact_keys(
        payload,
        {"schemaVersion", "requestId", "sourceSamples", "probes"},
        "root",
    )
    schema_version = _integer(payload["schemaVersion"], "schemaVersion", minimum=1)
    if schema_version != 1:
        raise WorkerInputError("unsupported LID worker request schema")
    request_id = _string(payload["requestId"], "requestId")
    if not _REQUEST_ID.fullmatch(request_id):
        raise WorkerInputError("requestId must be an opaque path-safe identifier")
    source_samples = _integer(
        payload["sourceSamples"],
        "sourceSamples",
        minimum=1,
    )
    raw_probes = payload["probes"]
    if not isinstance(raw_probes, list) or not (
        1 <= len(raw_probes) <= lock.policy.maximum_windows
    ):
        raise WorkerInputError("probes must contain one to five bounded regions")

    probes: list[LidProbeReference] = []
    for position, raw_probe in enumerate(raw_probes):
        field = f"probes[{position}]"
        probe = _mapping(raw_probe, field)
        _exact_keys(
            probe,
            {
                "index",
                "fileName",
                "wavSha256",
                "sourceStartSample",
                "sourceEndSample",
                "voicedSamples",
            },
            field,
        )
        index = _integer(probe["index"], f"{field}.index", minimum=0)
        if index != position:
            raise WorkerInputError("probe indexes must be contiguous and ordered")
        file_name = _string(probe["fileName"], f"{field}.fileName")
        if file_name != f"probe-{index}.wav":
            raise WorkerInputError("probe fileName does not match its fixed index")
        wav_sha256 = _string(probe["wavSha256"], f"{field}.wavSha256")
        if not _SHA256.fullmatch(wav_sha256):
            raise WorkerInputError("probe wavSha256 must be a lowercase SHA-256")
        start = _integer(
            probe["sourceStartSample"],
            f"{field}.sourceStartSample",
            minimum=0,
        )
        end = _integer(
            probe["sourceEndSample"],
            f"{field}.sourceEndSample",
            minimum=1,
        )
        voiced = _integer(
            probe["voicedSamples"],
            f"{field}.voicedSamples",
            minimum=1,
        )
        span = end - start
        if end > source_samples or span < 1:
            raise WorkerInputError("probe offsets must stay inside the source")
        if span != lock.policy.maximum_window_samples:
            raise WorkerInputError("probe differs from the locked region length")
        if (
            voiced < lock.policy.minimum_voiced_samples_per_window
            or voiced > span
        ):
            raise WorkerInputError("probe does not contain the required voiced span")
        if probes and probes[-1].source_end_sample > start:
            raise WorkerInputError("probe source windows must be ordered and disjoint")
        probes.append(
            LidProbeReference(
                index=index,
                file_name=file_name,
                wav_sha256=wav_sha256,
                source_start_sample=start,
                source_end_sample=end,
                voiced_samples=voiced,
            )
        )
    return LidWorkerRequest(
        request_id=request_id,
        source_samples=source_samples,
        probes=tuple(probes),
    )


def _resolve_probe(root: Path, reference: LidProbeReference) -> Path:
    candidate = root / reference.file_name
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as error:
        raise WorkerInputError("a locked LID probe is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WorkerInputError("a locked LID probe must be a regular file")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise WorkerInputError("a locked LID probe escapes its root") from error
    return candidate


def _decode_probe(
    root: Path,
    reference: LidProbeReference,
    lock: LidComponentLock,
) -> ProbeAudio:
    candidate = _resolve_probe(root, reference)
    maximum_encoded_bytes = (
        lock.policy.maximum_window_samples * lock.policy.sample_width_bytes
        + _MAX_WAV_OVERHEAD_BYTES
    )
    try:
        encoded = read_regular_file(candidate, maximum_encoded_bytes)
    except ValueError as error:
        raise WorkerInputError("a locked LID probe is unsafe or oversized") from error
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != reference.wav_sha256:
        raise WorkerInputError("a locked LID probe digest differs")
    try:
        with wave.open(io.BytesIO(encoded), "rb") as source:
            if source.getnchannels() != lock.policy.channel_count:
                raise WorkerInputError("LID probes must be mono")
            if source.getsampwidth() != lock.policy.sample_width_bytes:
                raise WorkerInputError("LID probes must use signed PCM16 samples")
            if source.getframerate() != lock.policy.sample_rate_hz:
                raise WorkerInputError("LID probes must use a 16-kHz sample rate")
            if source.getcomptype() != "NONE":
                raise WorkerInputError("compressed LID probes are unsupported")
            frame_count = source.getnframes()
            if frame_count != (
                reference.source_end_sample - reference.source_start_sample
            ):
                raise WorkerInputError("LID probe frames do not match source offsets")
            pcm_bytes = source.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise WorkerInputError("LID probe is not a valid PCM WAV") from error
    if len(pcm_bytes) != frame_count * lock.policy.sample_width_bytes:
        raise WorkerInputError("LID probe ended before its declared frame count")
    return ProbeAudio(
        pcm_bytes=pcm_bytes,
        frame_count=frame_count,
        wav_sha256=digest,
    )


def _validated_classification(value: LidClassification) -> LidClassification:
    raw_label = value.raw_label
    if (
        not isinstance(raw_label, str)
        or not (1 <= len(raw_label) <= _MAX_RAW_LABEL_LENGTH)
        or not raw_label.isprintable()
    ):
        raise RuntimeError("classifier returned invalid evidence")
    if (
        isinstance(value.top_score, bool)
        or not isinstance(value.top_score, (int, float))
        or isinstance(value.score_margin, bool)
        or not isinstance(value.score_margin, (int, float))
    ):
        raise RuntimeError("classifier returned invalid evidence")
    top_score = float(value.top_score)
    score_margin = float(value.score_margin)
    if (
        not math.isfinite(top_score)
        or not math.isfinite(score_margin)
        or top_score > 0.0
        or score_margin < 0.0
    ):
        raise RuntimeError("classifier returned invalid evidence")
    return LidClassification(
        raw_label=raw_label,
        top_score=top_score,
        score_margin=score_margin,
    )


def run_lid_worker_request(
    *,
    lock: LidComponentLock,
    request: LidWorkerRequest,
    probe_root: Path,
    classifier: LidClassifier,
) -> dict[str, Any]:
    """Classify validated probes and publish only bounded decision evidence."""

    try:
        root = probe_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise WorkerInputError("LID probe root is missing") from error
    if not root.is_dir():
        raise WorkerInputError("LID probe root is not a directory")

    observations: list[dict[str, Any]] = []
    for reference in request.probes:
        audio = _decode_probe(root, reference, lock)
        evidence = _validated_classification(classifier.classify(audio))
        observations.append(
            {
                "index": reference.index,
                "probeSha256": audio.wav_sha256,
                "sourceStartSample": reference.source_start_sample,
                "sourceEndSample": reference.source_end_sample,
                "voicedSamples": reference.voiced_samples,
                "rawLabel": evidence.raw_label,
                "topScore": evidence.top_score,
                "scoreMargin": evidence.score_margin,
            }
        )
    return {
        "schemaVersion": 1,
        "requestId": request.request_id,
        "componentId": lock.component_id,
        "model": {
            "id": lock.model.model_id,
            "revision": lock.model.revision,
        },
        "policyRevision": lock.policy.revision,
        "scoreSemantics": lock.policy.score_semantics,
        "sourceSamples": request.source_samples,
        "observations": observations,
    }


def validate_lid_worker_result(
    value: object,
    *,
    request: LidWorkerRequest,
    lock: LidComponentLock,
) -> None:
    """Rebind untrusted container output to the exact host-side request."""

    try:
        payload = _mapping(value, "result")
        _exact_keys(
            payload,
            {
                "schemaVersion",
                "requestId",
                "componentId",
                "model",
                "policyRevision",
                "scoreSemantics",
                "sourceSamples",
                "observations",
            },
            "result",
        )
        if _integer(payload["schemaVersion"], "schemaVersion", minimum=1) != 1:
            raise WorkerInputError("unsupported LID worker result schema")
        expected_values = (
            (_string(payload["requestId"], "result.requestId"), request.request_id),
            (
                _string(payload["componentId"], "result.componentId"),
                lock.component_id,
            ),
            (
                _string(payload["policyRevision"], "result.policyRevision"),
                lock.policy.revision,
            ),
            (
                _string(payload["scoreSemantics"], "result.scoreSemantics"),
                lock.policy.score_semantics,
            ),
            (
                _integer(
                    payload["sourceSamples"],
                    "result.sourceSamples",
                    minimum=1,
                ),
                request.source_samples,
            ),
        )
        if any(actual != expected for actual, expected in expected_values):
            raise WorkerInputError("LID worker result identity differs")

        model = _mapping(payload["model"], "result.model")
        _exact_keys(model, {"id", "revision"}, "result.model")
        if (
            _string(model["id"], "result.model.id") != lock.model.model_id
            or _string(model["revision"], "result.model.revision")
            != lock.model.revision
        ):
            raise WorkerInputError("LID worker result model differs")

        raw_observations = payload["observations"]
        if not isinstance(raw_observations, list) or len(raw_observations) != len(
            request.probes
        ):
            raise WorkerInputError("LID worker result observation count differs")
        for position, (raw_observation, reference) in enumerate(
            zip(raw_observations, request.probes, strict=True)
        ):
            field = f"result.observations[{position}]"
            observation = _mapping(raw_observation, field)
            _exact_keys(
                observation,
                {
                    "index",
                    "probeSha256",
                    "sourceStartSample",
                    "sourceEndSample",
                    "voicedSamples",
                    "rawLabel",
                    "topScore",
                    "scoreMargin",
                },
                field,
            )
            probe_sha256 = _string(
                observation["probeSha256"],
                f"{field}.probeSha256",
            )
            if _SHA256.fullmatch(probe_sha256) is None:
                raise WorkerInputError("LID worker probe digest is invalid")
            expected_observation = (
                (
                    _integer(observation["index"], f"{field}.index", minimum=0),
                    reference.index,
                ),
                (probe_sha256, reference.wav_sha256),
                (
                    _integer(
                        observation["sourceStartSample"],
                        f"{field}.sourceStartSample",
                        minimum=0,
                    ),
                    reference.source_start_sample,
                ),
                (
                    _integer(
                        observation["sourceEndSample"],
                        f"{field}.sourceEndSample",
                        minimum=1,
                    ),
                    reference.source_end_sample,
                ),
                (
                    _integer(
                        observation["voicedSamples"],
                        f"{field}.voicedSamples",
                        minimum=1,
                    ),
                    reference.voiced_samples,
                ),
            )
            if any(
                actual != expected
                for actual, expected in expected_observation
            ):
                raise WorkerInputError("LID worker observation binding differs")
            _validated_classification(
                LidClassification(
                    raw_label=observation["rawLabel"],
                    top_score=observation["topScore"],
                    score_margin=observation["scoreMargin"],
                )
            )
    except (KeyError, RuntimeError, TypeError, WorkerInputError) as error:
        raise WorkerResultError(
            "LID worker result violated the locked contract"
        ) from error
