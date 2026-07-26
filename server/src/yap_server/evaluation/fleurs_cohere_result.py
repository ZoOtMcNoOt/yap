from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from yap_server.evaluation.fleurs_comparator_plan import (
    FleursCohereComparatorPlan,
    FleursComparatorSelection,
)
from yap_server.evaluation.fleurs_corpus import FleursComparatorCase, FleursReleaseLock
from yap_server.evaluation.transcript_scoring import (
    TranscriptScore,
    aggregate_transcript_scores,
    score_transcript,
)
from yap_server.pools.cohere_engine import CohereAsrInput
from yap_server.pools.model_lock import ModelPoolLock, sha256_file
from yap_server.transcript_text import canonical_transcript


def validate_fleurs_cohere_results(
    results: object,
    *,
    requests: list[CohereAsrInput],
    cases: list[FleursComparatorCase],
    plan: FleursCohereComparatorPlan,
    model_lock: ModelPoolLock,
) -> list[str]:
    """Validate model, route, audio, runtime, and transcript result boundaries."""

    if not isinstance(results, list) or len(results) != len(requests):
        raise ValueError("Cohere comparator returned the wrong result count")
    hypotheses: list[str] = []
    for result, request, case in zip(results, requests, cases, strict=True):
        if not isinstance(result, Mapping) or result.get("schemaVersion") != 1:
            raise ValueError("Cohere comparator result envelope is invalid")
        if result.get("jobId") != request.job_id:
            raise ValueError("Cohere comparator result job identity differs")
        model = _mapping(result.get("model"), "Cohere comparator model result")
        if model != {
            "poolId": model_lock.pool_id,
            "id": model_lock.model_id,
            "revision": model_lock.model_revision,
        }:
            raise ValueError("Cohere comparator result model identity differs")
        audio = _mapping(result.get("audio"), "Cohere comparator audio result")
        if (
            audio.get("sha256") != case.audio.sha256
            or audio.get("durationMs") != case.audio.duration_ms
            or audio.get("sampleRateHz") != case.audio.sample_rate
        ):
            raise ValueError("Cohere comparator result audio identity differs")
        transcript = _mapping(
            result.get("transcript"),
            "Cohere comparator transcript result",
        )
        if transcript.get("language") != plan.provider_language:
            raise ValueError("Cohere comparator result provider language differs")
        if transcript.get("punctuation") is not plan.punctuation:
            raise ValueError("Cohere comparator result punctuation route differs")
        runtime = _mapping(result.get("runtime"), "Cohere comparator runtime result")
        if runtime.get("batchSize") != len(requests):
            raise ValueError("Cohere comparator result batch size differs")
        _validate_runtime(runtime, model_lock)
        hypotheses.append(
            canonical_transcript(
                transcript.get("text"),
                "Cohere comparator hypothesis",
            )
        )
    return hypotheses


def score_fleurs_cohere_case(
    case: FleursComparatorCase,
    hypothesis: str,
    *,
    plan: FleursCohereComparatorPlan,
) -> tuple[TranscriptScore, dict[str, object]]:
    """Score one case and retain its text only in private evidence."""

    score = score_transcript(
        case.reference,
        hypothesis,
        language_bcp47=plan.evaluation_locale_bcp47,
        scoring_profile=plan.scoring_profile,
        audio_duration_seconds=case.duration_samples / 16_000,
    )
    return (
        score,
        {
            "caseIndex": case.case_index,
            "sourceItemId": case.source_item_id,
            "promptId": case.prompt_id,
            "audio": {
                "encodedPcmWavSha256": case.audio.sha256,
                "decodedPcmSha256": hashlib.sha256(case.audio.pcm_bytes).hexdigest(),
                "durationSamples": case.duration_samples,
                "sampleRateHz": case.audio.sample_rate,
            },
            "reference": case.reference,
            "hypothesis": hypothesis,
            "score": score.to_private_evidence(),
        },
    )


def build_fleurs_cohere_aggregate(
    *,
    plan: FleursCohereComparatorPlan,
    plan_path: Path,
    release_lock: FleursReleaseLock,
    model_lock: ModelPoolLock,
    selection: FleursComparatorSelection,
    scores: list[TranscriptScore],
    total_audio_samples: int,
    measured_ms: int,
    batch_call_count: int,
    batch_counts: dict[str, int],
) -> dict[str, object]:
    """Build transcript-free comparator evidence safe for aggregate reporting."""

    audio_seconds = total_audio_samples / 16_000
    return {
        "schemaVersion": 1,
        "evidenceKind": "locked-public-comparator",
        "promotionEligible": False,
        "exposureStatus": plan.exposure_status,
        "planSha256": sha256_file(plan_path),
        "implementation": _implementation_identity(),
        "source": {
            "datasetId": plan.dataset_id,
            "datasetRevision": plan.dataset_revision,
            "datasetConfig": plan.dataset_config,
            "split": plan.split,
            "releaseLockSha256": plan.source_release_lock_sha256,
            "audioArchiveSha256": release_lock.audio_archive.sha256,
            "metadataSha256": release_lock.metadata.sha256,
            "selectionId": selection.identifier,
            "selectionRule": selection.selection,
            "caseCount": selection.case_count,
        },
        "candidate": {
            "poolId": model_lock.pool_id,
            "modelId": model_lock.model_id,
            "modelRevision": model_lock.model_revision,
            "modelLockSha256": plan.model_lock_sha256,
            "runtimeImage": model_lock.runtime_image,
            "runtimeSourceTag": model_lock.runtime_source_tag,
            "runtimeDigest": model_lock.runtime_digest,
            "pythonVersion": model_lock.runtime_python_version,
            "torchVersion": model_lock.runtime_torch_version,
            "cudaVersion": model_lock.runtime_cuda_version,
        },
        "route": {
            "evaluationLocaleBcp47": plan.evaluation_locale_bcp47,
            "providerLanguage": plan.provider_language,
            "punctuation": plan.punctuation,
        },
        "execution": {
            "batchSizeLimit": plan.batch_size,
            "warmupCases": plan.warmup_cases,
            "batchCallCount": batch_call_count,
            "observedBatchSizes": dict(sorted(batch_counts.items())),
            "audioDurationSeconds": audio_seconds,
            "measuredWallMs": measured_ms,
            "realtimeFactor": round(measured_ms / 1000 / audio_seconds, 6),
            "audioSecondsPerSecond": round(audio_seconds * 1000 / measured_ms, 6),
        },
        "quality": aggregate_transcript_scores(scores),
        "privacy": {
            "terminalOutput": "aggregate-only",
            "caseEvidence": "private-only",
            "containsTranscriptText": False,
            "containsFilesystemPaths": False,
        },
    }


def _implementation_identity() -> dict[str, object]:
    root = Path(__file__).resolve().parent
    module_names = (
        "fleurs_cohere_comparator.py",
        "fleurs_cohere_result.py",
        "fleurs_comparator_plan.py",
        "fleurs_corpus.py",
    )
    return {
        "revision": "yap-fleurs-cohere-comparator-v1",
        "moduleSha256": {
            name.removesuffix(".py"): sha256_file(root / name)
            for name in module_names
        },
    }


def _validate_runtime(
    runtime: Mapping[str, object],
    model_lock: ModelPoolLock,
) -> None:
    python_version = runtime.get("pythonVersion")
    compute_capability = runtime.get("computeCapability")
    if (
        runtime.get("device") != "cuda"
        or not isinstance(runtime.get("deviceName"), str)
        or not runtime["deviceName"]
        or not isinstance(compute_capability, list)
        or len(compute_capability) != 2
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in compute_capability
        )
        or not isinstance(python_version, str)
        or not (
            python_version == model_lock.runtime_python_version
            or python_version.startswith(f"{model_lock.runtime_python_version}.")
        )
        or runtime.get("torchVersion") != model_lock.runtime_torch_version
        or runtime.get("torchCudaVersion") != model_lock.runtime_torch_cuda_version
        or runtime.get("dtype") != "bfloat16"
        or runtime.get("overlayPackages")
        != dict(model_lock.runtime_overlay_packages)
    ):
        raise ValueError("Cohere comparator runtime differs from the model lock")
    for field in ("modelLoadMs", "inferenceMs"):
        value = runtime.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Cohere comparator runtime timing is invalid")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value
