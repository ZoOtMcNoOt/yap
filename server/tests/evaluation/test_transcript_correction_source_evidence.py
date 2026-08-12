from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from yap_server.evaluation.fleurs_comparator_plan import (
    load_fleurs_cohere_comparator_plan,
    select_fleurs_comparator_run,
)
from yap_server.evaluation.fleurs_corpus import load_fleurs_release_lock
from yap_server.evaluation.transcript_correction_source_evidence import (
    load_private_transcript_correction_source_evidence,
)
from yap_server.pools.model_lock import load_model_pool_lock


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MODEL_LOCK = "server/model-pools.lock.json"
_SOURCES = (
    (
        "en-US",
        "server/fleurs-en-us-cohere-comparator.plan.json",
        "server/fleurs-en-us-test.lock.json",
        "screen",
    ),
    (
        "es-419",
        "server/fleurs-cohere-comparator.plan.json",
        "server/fleurs-es-419-test.lock.json",
        "full",
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_case(index: int, language: str) -> dict[str, object]:
    identity = f"{language}:{index}"
    return {
        "audio": {
            "decodedPcmSha256": hashlib.sha256(
                f"decoded:{identity}".encode()
            ).hexdigest(),
            "durationSamples": 16_000,
            "encodedPcmWavSha256": hashlib.sha256(
                f"encoded:{identity}".encode()
            ).hexdigest(),
            "sampleRateHz": 16_000,
        },
        "caseIndex": index,
        "hypothesis": f"source transcript {index}",
        "promptId": index,
        "reference": f"reference transcript {index}",
        "score": {"languageBcp47": language},
        "sourceItemId": f"source-{language.lower()}-{index}",
    }


def _copy_public_inputs(root: Path) -> None:
    for relative in {
        _MODEL_LOCK,
        *(item for source in _SOURCES for item in source[1:3]),
    }:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / relative, destination)


def _build_private_sources(root: Path) -> tuple[tuple[Path, ...], dict[str, object]]:
    model_path = root / _MODEL_LOCK
    model = load_model_pool_lock(model_path)
    private_root = root.parent / "private-source-evidence"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    paths: list[Path] = []
    lock_sources: list[dict[str, object]] = []
    for language, plan_relative, release_relative, selection_id in _SOURCES:
        plan_path = root / plan_relative
        release_path = root / release_relative
        plan = load_fleurs_cohere_comparator_plan(plan_path)
        release = load_fleurs_release_lock(release_path)
        selection = select_fleurs_comparator_run(plan, selection_id)
        aggregate = {
            "schemaVersion": 1,
            "evidenceKind": "locked-public-comparator",
            "promotionEligible": False,
            "exposureStatus": "unknown",
            "planSha256": _sha256(plan_path),
            "implementation": {
                "revision": "yap-fleurs-cohere-comparator-v1",
                "moduleSha256": {},
            },
            "source": {
                "datasetId": plan.dataset_id,
                "datasetRevision": plan.dataset_revision,
                "datasetConfig": plan.dataset_config,
                "split": plan.split,
                "releaseLockSha256": _sha256(release_path),
                "audioArchiveSha256": release.audio_archive.sha256,
                "metadataSha256": release.metadata.sha256,
                "selectionId": selection.identifier,
                "selectionRule": selection.selection,
                "caseCount": selection.case_count,
            },
            "candidate": {
                "poolId": model.pool_id,
                "modelId": model.model_id,
                "modelRevision": model.model_revision,
                "modelLockSha256": _sha256(model_path),
                "runtimeImage": model.runtime_image,
                "runtimeSourceTag": model.runtime_source_tag,
                "runtimeDigest": model.runtime_digest,
                "pythonVersion": model.runtime_python_version,
                "torchVersion": model.runtime_torch_version,
                "cudaVersion": model.runtime_cuda_version,
            },
            "route": {
                "evaluationLocaleBcp47": plan.evaluation_locale_bcp47,
                "providerLanguage": plan.provider_language,
                "punctuation": plan.punctuation,
            },
            "execution": {
                "batchSizeLimit": plan.batch_size,
                "warmupCases": plan.warmup_cases,
            },
            "quality": {},
            "privacy": {
                "terminalOutput": "aggregate-only",
                "caseEvidence": "private-only",
                "containsTranscriptText": False,
                "containsFilesystemPaths": False,
            },
        }
        value = {
            "schemaVersion": 1,
            "privacyScope": "private-case-evidence",
            "aggregate": aggregate,
            "cases": [
                _source_case(index, language)
                for index in range(selection.case_count)
            ],
        }
        body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        path = private_root / f"{language.lower()}.json"
        path.write_bytes(body)
        path.chmod(0o600)
        paths.append(path)
        lock_sources.append(
            {
                "languageBcp47": language,
                "evidenceSha256": hashlib.sha256(body).hexdigest(),
                "comparatorPlanSha256": _sha256(plan_path),
                "releaseLockSha256": _sha256(release_path),
                "selectionId": selection.identifier,
                "caseCount": selection.case_count,
            }
        )
    lock = {
        "schemaVersion": 1,
        "evidenceKind": "transcript-correction-source-evidence-lock",
        "modelLockSha256": _sha256(model_path),
        "sources": lock_sources,
    }
    lock_path = root / "server/transcript-correction-source-evidence.lock.json"
    lock_path.write_text(
        json.dumps(lock, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return tuple(paths), lock


class TranscriptCorrectionSourceEvidenceTests(unittest.TestCase):
    def test_exact_locked_source_evidence_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "repository"
            root.mkdir()
            _copy_public_inputs(root)
            paths, lock = _build_private_sources(root)

            loaded = load_private_transcript_correction_source_evidence(
                paths,
                repository_root=root,
            )

            self.assertEqual(
                set(loaded),
                {source["evidenceSha256"] for source in lock["sources"]},
            )
            self.assertEqual(
                sum(len(source.cases) for source in loaded.values()),
                928,
            )

    def test_missing_or_changed_source_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "repository"
            root.mkdir()
            _copy_public_inputs(root)
            paths, _lock = _build_private_sources(root)

            with self.assertRaisesRegex(ValueError, "membership differs"):
                load_private_transcript_correction_source_evidence(
                    paths[:1],
                    repository_root=root,
                )

            changed = json.loads(paths[0].read_text(encoding="utf-8"))
            changed["cases"][0]["hypothesis"] = "changed transcript"
            paths[0].write_text(
                json.dumps(changed, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            paths[0].chmod(0o600)
            with self.assertRaisesRegex(ValueError, "is not locked"):
                load_private_transcript_correction_source_evidence(
                    paths,
                    repository_root=root,
                )


if __name__ == "__main__":
    unittest.main()
