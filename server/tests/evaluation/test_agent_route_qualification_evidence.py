from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yap_server.evaluation import agent_route_qualification_evidence as evidence
from yap_server.evaluation.agent_model_qualification import (
    evaluate_agent_model_qualification,
)
from yap_server.evaluation.checked_candidate import CheckedCandidate
from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)

from tests.evaluation.test_agent_model_qualification import (
    _candidate_run,
    _checked_candidate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentRouteQualificationEvidenceTests(unittest.TestCase):
    def test_admits_complete_tree_and_rejects_extra_or_missing_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            root, reference = _qualification_tree(Path(directory))
            with patch.object(evidence, "_verify_unchanged_route_inputs"):
                admitted = evidence.admit_agent_route_qualification(
                    REPOSITORY_ROOT,
                    checked_head="b" * 40,
                    evidence_root=root,
                    reference=reference,
                )
            self.assertEqual(admitted.evidence_sha256, reference.evidence_sha256)

            extra = root / "extra.json"
            _write_json(extra, {"unexpected": True})
            with self.assertRaisesRegex(ValueError, "tree differs"):
                evidence._verify_exact_artifact_tree(root, reference.artifact_sha256)
            extra.unlink()
            (root / "qualification.json").unlink()
            with self.assertRaisesRegex(ValueError, "tree differs"):
                evidence._verify_exact_artifact_tree(root, reference.artifact_sha256)

    def test_rejects_artifact_whose_bytes_do_not_match_the_frozen_digest(self) -> None:
        with TemporaryDirectory() as directory:
            root, reference = _qualification_tree(Path(directory))
            reference = replace(
                reference,
                artifact_sha256={
                    **reference.artifact_sha256,
                    "qualification.json": "0" * 64,
                },
            )
            with patch.object(evidence, "_verify_unchanged_route_inputs"):
                with self.assertRaisesRegex(ValueError, "out-of-band digest"):
                    evidence.admit_agent_route_qualification(
                        REPOSITORY_ROOT,
                        checked_head="b" * 40,
                        evidence_root=root,
                        reference=reference,
                    )

    def test_rejects_forged_qualification_semantics(self) -> None:
        for mutation in ("outcome", "head", "summary"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root, reference = _qualification_tree(Path(directory))
                path = root / "qualification.json"
                qualification = json.loads(path.read_text(encoding="utf-8"))
                if mutation == "outcome":
                    qualification["outcome"] = "deterministic-no-model"
                elif mutation == "head":
                    qualification["candidate"]["checkedHead"] = "c" * 40
                else:
                    qualification["candidateSummaries"][0]["eligible"] = False
                _rehash_qualification(qualification)
                _write_json(path, qualification)
                reference = replace(
                    reference,
                    evidence_sha256=qualification["evidenceSha256"],
                    artifact_sha256={
                        **reference.artifact_sha256,
                        "qualification.json": _file_sha256(path),
                    },
                )
                with patch.object(evidence, "_verify_unchanged_route_inputs"):
                    with self.assertRaisesRegex(ValueError, "decision differs"):
                        evidence.admit_agent_route_qualification(
                            REPOSITORY_ROOT,
                            checked_head="b" * 40,
                            evidence_root=root,
                            reference=reference,
                        )

    def test_rejects_runtime_receipt_with_forged_teardown(self) -> None:
        with TemporaryDirectory() as directory:
            root, reference = _qualification_tree(Path(directory))
            relative = "qwen3.6-35b-a3b-nvfp4/runtime-receipt.json"
            path = root / relative
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["teardown"]["listenerAbsent"] = False
            _write_json(path, receipt)
            reference = replace(
                reference,
                artifact_sha256={
                    **reference.artifact_sha256,
                    relative: _file_sha256(path),
                },
            )
            with patch.object(evidence, "_verify_unchanged_route_inputs"):
                with self.assertRaisesRegex(ValueError, "receipt"):
                    evidence.admit_agent_route_qualification(
                        REPOSITORY_ROOT,
                        checked_head="b" * 40,
                        evidence_root=root,
                        reference=reference,
                    )

    @unittest.skipUnless(os.name == "posix", "POSIX permission proof")
    def test_rejects_group_or_world_readable_private_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            root, reference = _qualification_tree(Path(directory))
            path = root / "qualification.json"
            path.chmod(0o644)

            with self.assertRaisesRegex(ValueError, "permissions"):
                evidence._verify_exact_artifact_tree(root, reference.artifact_sha256)


def _qualification_tree(parent: Path):
    root = parent / "agent-model"
    root.mkdir()
    root.chmod(0o700)
    candidate = _checked_candidate()
    runs = (
        _candidate_run(candidate, "qwen3.6-35b-a3b-nvfp4", 20),
        _candidate_run(candidate, "gemma-4-31b-it-nvfp4", 10),
    )
    with patch.object(CheckedCandidate, "verify_unchanged"):
        qualification = evaluate_agent_model_qualification(
            candidate=candidate,
            runs=runs,
        )
    values: dict[str, object] = {"qualification.json": qualification}
    for run in runs:
        prefix = f"{run.candidate_id}/"
        values[f"{prefix}results.json"] = run.evidence
        values[f"{prefix}runtime-receipt.json"] = run.runtime_receipt
        for name, child in run.children.items():
            values[f"{prefix}children/{name}.json"] = child
    for relative, value in values.items():
        _write_json(root / relative, value)
    artifacts = {relative: _file_sha256(root / relative) for relative in values}
    dependencies = {
        relative: _file_sha256(REPOSITORY_ROOT / relative)
        for relative in ("server/pyproject.toml", "server/uv.lock")
    }
    reference = evidence.AgentRouteQualificationReference(
        checked_head=candidate.checked_head,
        outcome="required-workload-routes-qualified",
        evidence_sha256=qualification["evidenceSha256"],
        input_sha256=candidate.input_sha256,
        dependency_sha256=dependencies,
        artifact_sha256=artifacts,
        lock_sha256="d" * 64,
    )
    return root, reference


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.parent
    while current.name != "agent-model":
        current.chmod(0o700)
        current = current.parent
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(0o600)


def _rehash_qualification(value: dict[str, object]) -> None:
    value.pop("evidenceSha256", None)
    value["evidenceSha256"] = canonical_evidence_sha256(value)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
