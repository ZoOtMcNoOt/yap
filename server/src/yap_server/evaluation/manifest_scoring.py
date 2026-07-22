from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
import wave

from yap_server.evaluation.corpus_manifest import (
    evaluation_policy_sha256,
    load_promotion_corpus_manifest_with_identity,
)
from yap_server.evaluation.transcript_scoring import (
    critical_token_set_sha256,
    current_scorer_lock,
    score_transcript,
)
from yap_server.limits import MAX_TRANSCRIPT_BYTES
from yap_server.pools.batch_asr_worker import (
    MAX_AUDIO_SECONDS,
    MAX_ENCODED_AUDIO_BYTES,
    SAMPLE_RATE_HZ,
)


_MAX_SCORER_LOCK_BYTES = 64 * 1024
_MAX_CRITICAL_POLICY_BYTES = 512 * 1024
_MAX_INFERENCE_RESULT_LOCK_BYTES = 64 * 1024
_INFERENCE_RESULT_LOCK_DIGEST_ENV = (
    "YAP_EVAL_INFERENCE_RESULT_LOCK_SHA256"
)
_AUDIO_READ_FRAMES = SAMPLE_RATE_HZ * 10
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def score_manifest_case(
    *,
    manifest_path: Path,
    registry_path: Path,
    case_id: str,
    model_id: str,
    model_revision: str,
    audio_path: Path,
    reference_path: Path,
    hypothesis_path: Path,
    inference_result_lock_path: Path,
    scorer_lock_path: Path,
    critical_token_policy_path: Path | None,
) -> dict[str, object]:
    """Score one trusted promotion case entirely inside the private cache."""

    cache_root = _private_cache_root()
    if reference_path.resolve(strict=True).samefile(
        hypothesis_path.resolve(strict=True)
    ):
        raise ValueError("reference and hypothesis must be distinct artifacts")
    manifest, manifest_sha256 = load_promotion_corpus_manifest_with_identity(
        manifest_path,
        registry_path,
    )
    scorer_lock_sha256 = _verified_scorer_lock(
        scorer_lock_path,
        cache_root=cache_root,
        expected_sha256=_sha256(
            manifest.get("scorerLockSha256"),
            "manifest scorer lock SHA-256",
        ),
    )
    candidate = _candidate(
        manifest,
        model_id=model_id,
        model_revision=model_revision,
    )
    candidate_lock_sha256 = _sha256(
        candidate.get("candidateLockSha256"),
        "candidate lock SHA-256",
    )
    case = _case(manifest, case_id)
    if case.get("purpose") != "independentPromotion":
        raise ValueError("manifest scoring requires an independent-promotion case")
    reference = _mapping(case.get("reference"), "manifest reference")
    audio = _mapping(case.get("audio"), "manifest audio")
    verified_audio = _verified_audio(
        audio_path,
        cache_root=cache_root,
        manifest_audio=audio,
    )
    reference_text, reference_bytes = _private_text(
        reference_path,
        cache_root=cache_root,
        maximum_bytes=MAX_TRANSCRIPT_BYTES,
        field="reference transcript",
    )
    expected_reference_sha256 = _sha256(
        reference.get("sha256"),
        "manifest reference SHA-256",
    )
    if hashlib.sha256(reference_bytes).hexdigest() != expected_reference_sha256:
        raise ValueError("reference SHA-256 differs from the manifest")
    hypothesis_text, hypothesis_bytes = _private_text(
        hypothesis_path,
        cache_root=cache_root,
        maximum_bytes=MAX_TRANSCRIPT_BYTES,
        field="hypothesis transcript",
    )
    (
        inference_result_lock_sha256,
        runtime,
        terminology_context,
    ) = _verified_inference_result_lock(
        inference_result_lock_path,
        cache_root=cache_root,
        case_id=case_id,
        model_id=model_id,
        model_revision=model_revision,
        candidate_lock_sha256=candidate_lock_sha256,
        audio=verified_audio,
        hypothesis_sha256=hashlib.sha256(hypothesis_bytes).hexdigest(),
    )

    expected_policy_sha256 = reference.get("criticalTokenSetSha256")
    critical_tokens: list[str] | None
    if expected_policy_sha256 is None:
        if critical_token_policy_path is not None:
            raise ValueError("manifest case does not admit a critical-token policy")
        critical_tokens = None
    else:
        expected_policy_sha256 = _sha256(
            expected_policy_sha256,
            "manifest critical-token set SHA-256",
        )
        if critical_token_policy_path is None:
            raise ValueError("manifest case requires a private critical-token policy")
        critical_tokens = _critical_token_policy(
            critical_token_policy_path,
            cache_root=cache_root,
        )
        if critical_token_set_sha256(critical_tokens) != expected_policy_sha256:
            raise ValueError("critical-token policy differs from the manifest")
    _validate_terminology_context_policy_binding(
        terminology_context,
        critical_token_set_sha256=expected_policy_sha256,
        critical_token_count=(
            None if critical_tokens is None else len(critical_tokens)
        ),
    )

    language_bcp47 = reference.get("languageBcp47")
    scoring_profile = reference.get("scoringProfile")
    punctuation_profile = reference.get("punctuationProfile")
    if not all(
        isinstance(value, str)
        for value in (language_bcp47, scoring_profile, punctuation_profile)
    ):
        raise ValueError("manifest evaluation policy is invalid")
    policy_sha256 = evaluation_policy_sha256(
        language_bcp47=language_bcp47,
        scoring_profile=scoring_profile,
        punctuation_profile=punctuation_profile,
        critical_token_set_sha256=expected_policy_sha256,
    )
    score = score_transcript(
        reference_text,
        hypothesis_text,
        language_bcp47=language_bcp47,
        scoring_profile=scoring_profile,
        audio_duration_seconds=(
            verified_audio["durationSamples"]
            / verified_audio["sampleRateHz"]
        ),
        critical_tokens=critical_tokens,
        critical_token_set_sha256=expected_policy_sha256,
    )
    return {
        "schemaVersion": 2,
        "privacyScope": "private-case",
        "caseId": case_id,
        "manifestSha256": manifest_sha256,
        "evaluationPolicySha256": policy_sha256,
        "scorerLockSha256": scorer_lock_sha256,
        "candidateLockSha256": candidate_lock_sha256,
        "inferenceResultLockSha256": inference_result_lock_sha256,
        "model": {"id": model_id, "revision": model_revision},
        "runtime": runtime,
        "terminologyContext": terminology_context,
        "score": score.to_private_evidence(),
    }


def _verified_audio(
    path: Path,
    *,
    cache_root: Path,
    manifest_audio: Mapping[str, object],
) -> dict[str, object]:
    resolved = _private_file_path(
        path,
        cache_root=cache_root,
        maximum_bytes=MAX_ENCODED_AUDIO_BYTES,
        field="promotion audio",
    )
    metadata = resolved.stat()
    raw_sha256 = _sha256_file(resolved)
    decoded_digest = hashlib.sha256()
    decoded_bytes = 0
    try:
        with wave.open(str(resolved), "rb") as source:
            frame_count = source.getnframes()
            if (
                source.getnchannels() != 1
                or source.getsampwidth() != 2
                or source.getframerate() != SAMPLE_RATE_HZ
                or source.getcomptype() != "NONE"
                or not 1 <= frame_count <= SAMPLE_RATE_HZ * MAX_AUDIO_SECONDS
            ):
                raise ValueError(
                    "promotion audio must be bounded mono PCM16 WAV at 16 kHz"
                )
            while True:
                body = source.readframes(_AUDIO_READ_FRAMES)
                if not body:
                    break
                decoded_digest.update(body)
                decoded_bytes += len(body)
    except (EOFError, wave.Error) as error:
        raise ValueError("promotion audio is not a valid PCM WAV") from error
    if decoded_bytes != frame_count * 2 or _sha256_file(resolved) != raw_sha256:
        raise ValueError("promotion audio changed during verification")
    verified: dict[str, object] = {
        "sha256": raw_sha256,
        "byteLength": metadata.st_size,
        "decodedPcmSha256": decoded_digest.hexdigest(),
        "durationSamples": frame_count,
        "sampleRateHz": SAMPLE_RATE_HZ,
        "channels": 1,
        "codec": "pcm_s16le",
    }
    expected = {
        key: manifest_audio.get(key)
        for key in (
            "sha256",
            "byteLength",
            "decodedPcmSha256",
            "durationSamples",
            "sampleRateHz",
            "channels",
            "codec",
        )
    }
    if expected != verified:
        raise ValueError(
            "promotion audio shape or identity differs from the verified WAV"
        )
    return verified


def _verified_inference_result_lock(
    path: Path,
    *,
    cache_root: Path,
    case_id: str,
    model_id: str,
    model_revision: str,
    candidate_lock_sha256: str,
    audio: Mapping[str, object],
    hypothesis_sha256: str,
) -> tuple[str, dict[str, str], dict[str, object]]:
    expected_lock_sha256 = _sha256(
        os.environ.get(_INFERENCE_RESULT_LOCK_DIGEST_ENV, "").strip(),
        _INFERENCE_RESULT_LOCK_DIGEST_ENV,
    )
    body = _private_bytes(
        path,
        cache_root=cache_root,
        maximum_bytes=_MAX_INFERENCE_RESULT_LOCK_BYTES,
        allow_empty=False,
        field="inference-result lock",
    )
    lock_sha256 = hashlib.sha256(body).hexdigest()
    if lock_sha256 != expected_lock_sha256:
        raise ValueError("inference-result lock differs from its trust anchor")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("inference-result lock is not valid JSON") from error
    result_lock = _object(
        payload,
        {
            "schemaVersion",
            "caseId",
            "modelId",
            "modelRevision",
            "candidateLockSha256",
            "audioSha256",
            "decodedPcmSha256",
            "durationSamples",
            "sampleRateHz",
            "hypothesisSha256",
            "terminologyContext",
            "runtime",
        },
        "inference-result lock",
    )
    if result_lock["schemaVersion"] != 2:
        raise ValueError("inference-result lock schema is unsupported")
    if (
        result_lock["modelId"] != model_id
        or result_lock["modelRevision"] != model_revision
    ):
        raise ValueError("inference-result model identity differs from the candidate")
    expected = {
        "caseId": case_id,
        "candidateLockSha256": candidate_lock_sha256,
        "audioSha256": audio["sha256"],
        "decodedPcmSha256": audio["decodedPcmSha256"],
        "durationSamples": audio["durationSamples"],
        "sampleRateHz": audio["sampleRateHz"],
        "hypothesisSha256": hypothesis_sha256,
    }
    observed = {key: result_lock[key] for key in expected}
    if observed != expected:
        if result_lock["hypothesisSha256"] != hypothesis_sha256:
            raise ValueError(
                "hypothesis SHA-256 differs from the inference-result lock"
            )
        raise ValueError(
            "inference-result case, audio, or candidate lock identity differs"
        )
    runtime = _object(
        result_lock["runtime"],
        {"id", "revision", "lockPath", "lockSha256"},
        "inference runtime",
    )
    runtime_id = _identifier(runtime["id"], "inference runtime ID")
    runtime_revision = _identifier(
        runtime["revision"],
        "inference runtime revision",
    )
    runtime_lock_sha256 = _sha256(
        runtime["lockSha256"],
        "inference runtime lock SHA-256",
    )
    _verified_relative_artifact(
        path.parent,
        runtime["lockPath"],
        cache_root=cache_root,
        expected_sha256=runtime_lock_sha256,
        field="inference runtime lock",
    )
    terminology_context = _validated_terminology_context(
        result_lock["terminologyContext"]
    )
    return (
        lock_sha256,
        {
            "id": runtime_id,
            "revision": runtime_revision,
            "lockSha256": runtime_lock_sha256,
        },
        terminology_context,
    )


def _validated_terminology_context(value: object) -> dict[str, object]:
    context = _object(
        value,
        {
            "mode",
            "sourcePolicySha256",
            "requestPayloadSha256",
            "entryCount",
            "requestPayloadBytes",
        },
        "terminology context",
    )
    mode = context["mode"]
    if mode == "none":
        expected = {
            "mode": "none",
            "sourcePolicySha256": None,
            "requestPayloadSha256": None,
            "entryCount": 0,
            "requestPayloadBytes": 0,
        }
        if context != expected:
            raise ValueError("unused terminology context must be empty")
        return expected
    if mode != "provider-native":
        raise ValueError("terminology context mode is invalid")
    source_policy_sha256 = _sha256(
        context["sourcePolicySha256"],
        "terminology source-policy SHA-256",
    )
    request_payload_sha256 = _sha256(
        context["requestPayloadSha256"],
        "terminology request-payload SHA-256",
    )
    entry_count = context["entryCount"]
    request_payload_bytes = context["requestPayloadBytes"]
    if (
        isinstance(entry_count, bool)
        or not isinstance(entry_count, int)
        or not 1 <= entry_count <= 4_096
        or isinstance(request_payload_bytes, bool)
        or not isinstance(request_payload_bytes, int)
        or not 1 <= request_payload_bytes <= _MAX_CRITICAL_POLICY_BYTES
    ):
        raise ValueError("terminology context size is invalid")
    return {
        "mode": "provider-native",
        "sourcePolicySha256": source_policy_sha256,
        "requestPayloadSha256": request_payload_sha256,
        "entryCount": entry_count,
        "requestPayloadBytes": request_payload_bytes,
    }


def _validate_terminology_context_policy_binding(
    context: Mapping[str, object],
    *,
    critical_token_set_sha256: object,
    critical_token_count: int | None,
) -> None:
    if context["mode"] == "none":
        return
    if context["sourcePolicySha256"] != critical_token_set_sha256:
        raise ValueError(
            "terminology context differs from the critical-token policy"
        )
    if context["entryCount"] != critical_token_count:
        raise ValueError(
            "terminology context entry count differs from the critical-token policy"
        )


def _verified_scorer_lock(
    path: Path,
    *,
    cache_root: Path,
    expected_sha256: str,
) -> str:
    body = _private_bytes(
        path,
        cache_root=cache_root,
        maximum_bytes=_MAX_SCORER_LOCK_BYTES,
        allow_empty=False,
        field="scorer lock",
    )
    digest = hashlib.sha256(body).hexdigest()
    if digest != expected_sha256:
        raise ValueError("scorer lock SHA-256 differs from the manifest")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("scorer lock is not valid JSON") from error
    if payload != current_scorer_lock():
        raise ValueError("scorer lock does not match the executing scorer")
    return digest


def _critical_token_policy(path: Path, *, cache_root: Path) -> list[str]:
    body = _private_bytes(
        path,
        cache_root=cache_root,
        maximum_bytes=_MAX_CRITICAL_POLICY_BYTES,
        allow_empty=False,
        field="critical-token policy",
    )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("critical-token policy is not valid JSON") from error
    policy = _mapping(payload, "critical-token policy")
    if set(policy) != {"schemaVersion", "criticalTokens"}:
        raise ValueError("critical-token policy fields differ from the contract")
    if policy["schemaVersion"] != 1:
        raise ValueError("critical-token policy schema is unsupported")
    values = policy["criticalTokens"]
    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise ValueError("critical-token policy values are invalid")
    return values


def _case(manifest: Mapping[str, object], case_id: str) -> Mapping[str, object]:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("manifest case ID is invalid")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("manifest cases are invalid")
    matches = [
        value
        for value in cases
        if isinstance(value, Mapping) and value.get("id") == case_id
    ]
    if len(matches) != 1:
        raise ValueError("manifest case ID was not found exactly once")
    return matches[0]


def _candidate(
    manifest: Mapping[str, object],
    *,
    model_id: str,
    model_revision: str,
) -> Mapping[str, object]:
    models = manifest.get("candidateModels")
    if not isinstance(models, list):
        raise ValueError("manifest candidate models are invalid")
    matches = [
        model
        for model in models
        if isinstance(model, Mapping)
        and model.get("id") == model_id
        and model.get("revision") == model_revision
    ]
    if len(matches) != 1:
        raise ValueError("requested model is not a manifest candidate")
    return matches[0]


def _private_cache_root() -> Path:
    raw = os.environ.get("YAP_EVAL_CACHE", "").strip()
    if not raw:
        raise ValueError("YAP_EVAL_CACHE is required for manifest scoring")
    requested = Path(raw)
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("YAP_EVAL_CACHE must be an absolute real directory")
    resolved = requested.resolve(strict=True)
    repository = Path(__file__).resolve().parents[4]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("YAP_EVAL_CACHE must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("YAP_EVAL_CACHE must be a real directory")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("YAP_EVAL_CACHE must use private permissions")
    return resolved


def _private_text(
    path: Path,
    *,
    cache_root: Path,
    maximum_bytes: int,
    field: str,
) -> tuple[str, bytes]:
    body = _private_bytes(
        path,
        cache_root=cache_root,
        maximum_bytes=maximum_bytes,
        allow_empty=True,
        field=field,
    )
    try:
        return body.decode("utf-8"), body
    except UnicodeDecodeError as error:
        raise ValueError(f"{field} is not valid UTF-8") from error


def _private_bytes(
    path: Path,
    *,
    cache_root: Path,
    maximum_bytes: int,
    allow_empty: bool,
    field: str,
) -> bytes:
    resolved = _private_file_path(
        path,
        cache_root=cache_root,
        maximum_bytes=maximum_bytes,
        field=field,
        allow_empty=allow_empty,
    )
    metadata = resolved.stat()
    minimum_bytes = 0 if allow_empty else 1
    if not minimum_bytes <= metadata.st_size <= maximum_bytes:
        raise ValueError(f"{field} size is invalid")
    body = resolved.read_bytes()
    if len(body) != metadata.st_size:
        raise ValueError(f"{field} changed while it was read")
    return body


def _private_file_path(
    path: Path,
    *,
    cache_root: Path,
    maximum_bytes: int,
    field: str,
    allow_empty: bool = False,
) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{field} must be an absolute real file")
    resolved = path.resolve(strict=True)
    if cache_root not in resolved.parents:
        raise ValueError(f"{field} must remain inside YAP_EVAL_CACHE")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{field} must be a real file")
    minimum_bytes = 0 if allow_empty else 1
    if not minimum_bytes <= metadata.st_size <= maximum_bytes:
        raise ValueError(f"{field} size is invalid")
    return resolved


def _verified_relative_artifact(
    root: Path,
    relative_value: object,
    *,
    cache_root: Path,
    expected_sha256: str,
    field: str,
) -> None:
    if not isinstance(relative_value, str) or not relative_value:
        raise ValueError(f"{field} path is invalid")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} path is invalid")
    artifact = _private_file_path(
        root / relative,
        cache_root=cache_root,
        maximum_bytes=_MAX_INFERENCE_RESULT_LOCK_BYTES,
        field=field,
    )
    if _sha256_file(artifact) != expected_sha256:
        raise ValueError(f"{field} differs from the inference-result lock")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for body in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(body)
    return digest.hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _object(
    value: object,
    keys: set[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields differ from the contract")
    return value


def _sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value
