"""Load exact private ASR evidence used by Scribe qualification cases."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
from typing import Mapping, Sequence

from yap_server.private_artifact import read_json_object_with_identity
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock, sha256_file

from .fleurs_comparator_plan import (
    FleursCohereComparatorPlan,
    FleursComparatorSelection,
    bind_fleurs_comparator_model,
    bind_fleurs_comparator_release,
    load_fleurs_cohere_comparator_plan,
    select_fleurs_comparator_run,
)
from .fleurs_corpus import FleursReleaseLock, load_fleurs_release_lock


_MAXIMUM_EVIDENCE_BYTES = 64 * 1024 * 1024
_MAXIMUM_LOCK_BYTES = 32 * 1024
_MAXIMUM_CASES_PER_EVIDENCE = 4096
_MAXIMUM_TEXT_CHARACTERS = 32_768
_MAXIMUM_AUDIO_SECONDS = 600
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_SOURCE_FILES = {
    "en-US": (
        "server/fleurs-en-us-cohere-comparator.plan.json",
        "server/fleurs-en-us-test.lock.json",
    ),
    "es-419": (
        "server/fleurs-cohere-comparator.plan.json",
        "server/fleurs-es-419-test.lock.json",
    ),
}
_MODEL_LOCK_PATH = "server/model-pools.lock.json"


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionSourceCase:
    case_id: str
    audio_sha256: str
    language_bcp47: str
    duration_milliseconds: int
    hypothesis: str = field(repr=False)
    reference: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionSourceEvidence:
    evidence_sha256: str
    cases: dict[str, TranscriptCorrectionSourceCase] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _LockedSourceEvidence:
    language_bcp47: str
    evidence_sha256: str
    plan: FleursCohereComparatorPlan
    plan_sha256: str
    release: FleursReleaseLock
    release_lock_sha256: str
    selection: FleursComparatorSelection
    model: ModelPoolLock = field(repr=False)
    model_lock_sha256: str


def load_private_transcript_correction_source_evidence(
    paths: Sequence[Path],
    *,
    repository_root: Path,
) -> dict[str, TranscriptCorrectionSourceEvidence]:
    """Read exact owner-private comparator evidence without exposing case text."""

    root = repository_root.resolve(strict=True)
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)) or not paths:
        raise ValueError("transcript correction source evidence is required")
    expected = _load_source_evidence_lock(root)
    loaded: dict[str, TranscriptCorrectionSourceEvidence] = {}
    for path in paths:
        resolved = _private_evidence_path(Path(path), repository_root=root)
        value, identity = read_json_object_with_identity(
            resolved,
            maximum_bytes=_MAXIMUM_EVIDENCE_BYTES,
            field="transcript correction source evidence",
        )
        locked = expected.get(identity)
        if locked is None:
            raise ValueError("transcript correction source evidence is not locked")
        if identity in loaded:
            raise ValueError("transcript correction source evidence is duplicated")
        aggregate, cases = _source_cases(value)
        _validate_locked_evidence(aggregate, cases, locked)
        loaded[identity] = TranscriptCorrectionSourceEvidence(
            evidence_sha256=identity,
            cases=cases,
        )
    if set(loaded) != set(expected):
        raise ValueError("transcript correction source evidence membership differs")
    return loaded


def _source_cases(
    value: object,
) -> tuple[Mapping[str, object], dict[str, TranscriptCorrectionSourceCase]]:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "privacyScope",
        "aggregate",
        "cases",
    }:
        raise ValueError("transcript correction source evidence shape differs")
    if (
        value["schemaVersion"] != 1
        or isinstance(value["schemaVersion"], bool)
        or value["privacyScope"] != "private-case-evidence"
        or not isinstance(value["aggregate"], dict)
    ):
        raise ValueError("transcript correction source evidence identity differs")
    raw_cases = value["cases"]
    if (
        not isinstance(raw_cases, list)
        or not 1 <= len(raw_cases) <= _MAXIMUM_CASES_PER_EVIDENCE
    ):
        raise ValueError("transcript correction source evidence case count is invalid")
    cases: dict[str, TranscriptCorrectionSourceCase] = {}
    for raw_case in raw_cases:
        case = _source_case(raw_case)
        if case.case_id in cases:
            raise ValueError("transcript correction source case identity is duplicated")
        cases[case.case_id] = case
    return value["aggregate"], cases


def _load_source_evidence_lock(
    repository_root: Path,
) -> dict[str, _LockedSourceEvidence]:
    lock_path = repository_root / "server/transcript-correction-source-evidence.lock.json"
    value, _identity = read_json_object_with_identity(
        lock_path,
        maximum_bytes=_MAXIMUM_LOCK_BYTES,
        field="transcript correction source evidence lock",
    )
    if set(value) != {
        "schemaVersion",
        "evidenceKind",
        "modelLockSha256",
        "sources",
    } or value.get("schemaVersion") != 1 or isinstance(
        value.get("schemaVersion"), bool
    ) or value.get("evidenceKind") != "transcript-correction-source-evidence-lock":
        raise ValueError("transcript correction source evidence lock shape differs")
    model_lock_sha256 = _sha256(value["modelLockSha256"], "model lock")
    model_path = repository_root / _MODEL_LOCK_PATH
    if sha256_file(model_path) != model_lock_sha256:
        raise ValueError("transcript correction source model lock differs")
    model = load_model_pool_lock(model_path)
    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) != len(_SOURCE_FILES):
        raise ValueError("transcript correction source evidence lock count differs")
    result: dict[str, _LockedSourceEvidence] = {}
    seen_languages: set[str] = set()
    for raw in sources:
        if not isinstance(raw, dict) or set(raw) != {
            "languageBcp47",
            "evidenceSha256",
            "comparatorPlanSha256",
            "releaseLockSha256",
            "selectionId",
            "caseCount",
        }:
            raise ValueError("transcript correction source evidence lock entry differs")
        language = raw["languageBcp47"]
        if language not in _SOURCE_FILES or language in seen_languages:
            raise ValueError("transcript correction source evidence language differs")
        seen_languages.add(language)
        plan_relative, release_relative = _SOURCE_FILES[language]
        plan_path = repository_root / plan_relative
        release_path = repository_root / release_relative
        plan_sha256 = _sha256(raw["comparatorPlanSha256"], "comparator plan")
        release_sha256 = _sha256(raw["releaseLockSha256"], "release lock")
        if sha256_file(plan_path) != plan_sha256:
            raise ValueError("transcript correction comparator plan differs")
        if sha256_file(release_path) != release_sha256:
            raise ValueError("transcript correction source release lock differs")
        plan = load_fleurs_cohere_comparator_plan(plan_path)
        release = load_fleurs_release_lock(release_path)
        selection_id = _text(
            raw["selectionId"],
            "source selection",
            maximum=64,
            single_line=True,
        )
        selection = select_fleurs_comparator_run(plan, selection_id)
        bind_fleurs_comparator_release(plan, release, selection)
        bind_fleurs_comparator_model(plan, model)
        case_count = _positive_int(raw["caseCount"], "locked case count")
        if selection.case_count != case_count or plan.evaluation_locale_bcp47 != language:
            raise ValueError("transcript correction source selection differs")
        evidence_sha256 = _sha256(raw["evidenceSha256"], "source evidence")
        if evidence_sha256 in result:
            raise ValueError("transcript correction source evidence lock is duplicated")
        result[evidence_sha256] = _LockedSourceEvidence(
            language_bcp47=language,
            evidence_sha256=evidence_sha256,
            plan=plan,
            plan_sha256=plan_sha256,
            release=release,
            release_lock_sha256=release_sha256,
            selection=selection,
            model=model,
            model_lock_sha256=model_lock_sha256,
        )
    if seen_languages != set(_SOURCE_FILES):
        raise ValueError("transcript correction source evidence languages differ")
    return result


def _validate_locked_evidence(
    aggregate: Mapping[str, object],
    cases: dict[str, TranscriptCorrectionSourceCase],
    locked: _LockedSourceEvidence,
) -> None:
    plan = locked.plan
    release = locked.release
    model = locked.model
    if set(aggregate) != {
        "schemaVersion",
        "evidenceKind",
        "promotionEligible",
        "exposureStatus",
        "planSha256",
        "implementation",
        "source",
        "candidate",
        "route",
        "execution",
        "quality",
        "privacy",
    } or (
        aggregate.get("schemaVersion") != 1
        or isinstance(aggregate.get("schemaVersion"), bool)
        or aggregate.get("evidenceKind") != "locked-public-comparator"
        or aggregate.get("promotionEligible") is not False
        or aggregate.get("exposureStatus") != "unknown"
        or aggregate.get("planSha256") != locked.plan_sha256
    ):
        raise ValueError("transcript correction source aggregate identity differs")
    expected_source = {
        "datasetId": plan.dataset_id,
        "datasetRevision": plan.dataset_revision,
        "datasetConfig": plan.dataset_config,
        "split": plan.split,
        "releaseLockSha256": locked.release_lock_sha256,
        "audioArchiveSha256": release.audio_archive.sha256,
        "metadataSha256": release.metadata.sha256,
        "selectionId": locked.selection.identifier,
        "selectionRule": locked.selection.selection,
        "caseCount": locked.selection.case_count,
    }
    expected_candidate = {
        "poolId": model.pool_id,
        "modelId": model.model_id,
        "modelRevision": model.model_revision,
        "modelLockSha256": locked.model_lock_sha256,
        "runtimeImage": model.runtime_image,
        "runtimeSourceTag": model.runtime_source_tag,
        "runtimeDigest": model.runtime_digest,
        "pythonVersion": model.runtime_python_version,
        "torchVersion": model.runtime_torch_version,
        "cudaVersion": model.runtime_cuda_version,
    }
    if (
        aggregate["source"] != expected_source
        or aggregate["candidate"] != expected_candidate
        or aggregate["route"]
        != {
            "evaluationLocaleBcp47": plan.evaluation_locale_bcp47,
            "providerLanguage": plan.provider_language,
            "punctuation": plan.punctuation,
        }
        or aggregate["privacy"]
        != {
            "terminalOutput": "aggregate-only",
            "caseEvidence": "private-only",
            "containsTranscriptText": False,
            "containsFilesystemPaths": False,
        }
        or len(cases) != locked.selection.case_count
        or any(case.language_bcp47 != locked.language_bcp47 for case in cases.values())
    ):
        raise ValueError("transcript correction source aggregate binding differs")
    implementation = aggregate["implementation"]
    execution = aggregate["execution"]
    if (
        not isinstance(implementation, dict)
        or set(implementation) != {"revision", "moduleSha256"}
        or implementation.get("revision") != "yap-fleurs-cohere-comparator-v1"
        or not isinstance(implementation.get("moduleSha256"), dict)
        or not isinstance(execution, dict)
        or execution.get("batchSizeLimit") != plan.batch_size
        or execution.get("warmupCases") != plan.warmup_cases
        or not isinstance(aggregate["quality"], dict)
    ):
        raise ValueError("transcript correction source aggregate contract differs")


def _source_case(value: object) -> TranscriptCorrectionSourceCase:
    if not isinstance(value, dict) or set(value) != {
        "audio",
        "caseIndex",
        "hypothesis",
        "promptId",
        "reference",
        "score",
        "sourceItemId",
    }:
        raise ValueError("transcript correction source case shape differs")
    case_id = _text(
        value["sourceItemId"],
        "source case identity",
        maximum=256,
        single_line=True,
    )
    audio = value["audio"]
    score = value["score"]
    if not isinstance(audio, dict) or set(audio) != {
        "decodedPcmSha256",
        "durationSamples",
        "encodedPcmWavSha256",
        "sampleRateHz",
    }:
        raise ValueError("transcript correction source audio shape differs")
    if not isinstance(score, dict):
        raise ValueError("transcript correction source score shape differs")
    audio_sha256 = audio["decodedPcmSha256"]
    encoded_sha256 = audio["encodedPcmWavSha256"]
    if (
        not isinstance(audio_sha256, str)
        or _SHA256.fullmatch(audio_sha256) is None
        or not isinstance(encoded_sha256, str)
        or _SHA256.fullmatch(encoded_sha256) is None
    ):
        raise ValueError("transcript correction source audio identity is invalid")
    _nonnegative_int(value["caseIndex"], "case index")
    _nonnegative_int(value["promptId"], "prompt identity")
    duration_samples = _positive_int(audio["durationSamples"], "duration samples")
    sample_rate_hz = _positive_int(audio["sampleRateHz"], "sample rate")
    if duration_samples > sample_rate_hz * _MAXIMUM_AUDIO_SECONDS:
        raise ValueError("transcript correction source duration exceeds the bound")
    language = score.get("languageBcp47")
    if not isinstance(language, str) or _LANGUAGE.fullmatch(language) is None:
        raise ValueError("transcript correction source language is invalid")
    return TranscriptCorrectionSourceCase(
        case_id=case_id,
        audio_sha256=audio_sha256,
        language_bcp47=language,
        duration_milliseconds=max(1, round(duration_samples * 1_000 / sample_rate_hz)),
        hypothesis=_text(
            value["hypothesis"],
            "source hypothesis",
            maximum=_MAXIMUM_TEXT_CHARACTERS,
        ),
        reference=_text(
            value["reference"],
            "source reference",
            maximum=_MAXIMUM_TEXT_CHARACTERS,
        ),
    )


def _private_evidence_path(path: Path, *, repository_root: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    if not path.is_absolute() or path != absolute or path.is_symlink():
        raise ValueError("transcript correction source evidence path must be absolute")
    resolved = path.resolve(strict=True)
    if (
        resolved != path
        or resolved == repository_root
        or repository_root in resolved.parents
    ):
        raise ValueError("transcript correction source evidence must remain outside the repository")
    metadata = resolved.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("transcript correction source evidence must be a regular file")
    if os.name == "posix":
        parent = resolved.parent.lstat()
        if (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or stat.S_ISLNK(parent.st_mode)
            or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) & 0o077
        ):
            raise ValueError("transcript correction source evidence must be owner-private")
    return resolved


def _text(
    value: object,
    field: str,
    *,
    maximum: int,
    single_line: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\0" in value
        or (single_line and any(character in value for character in "\r\n"))
    ):
        raise ValueError(f"transcript correction {field} is invalid")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"transcript correction source {field} is invalid")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"transcript correction source {field} is invalid")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"transcript correction source {field} is invalid")
    return value


__all__ = [
    "TranscriptCorrectionSourceCase",
    "TranscriptCorrectionSourceEvidence",
    "load_private_transcript_correction_source_evidence",
]
