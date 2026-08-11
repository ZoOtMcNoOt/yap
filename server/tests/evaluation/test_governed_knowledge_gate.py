"""Governed knowledge aggregate gate contract tests."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from yap_server.evaluation import agent_route_qualification_evidence as route_evidence
from yap_server.evaluation import governed_knowledge_gate as gate
from yap_server.evaluation import owned_postgres_knowledge_runtime as postgres_runtime


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMAGE_ID = "sha256:" + "4" * 64
_MANIFEST_DIGEST = "sha256:" + "f" * 64
_HEAD = "3" * 40
_CONTAINER_ID = "b" * 64


class GovernedKnowledgeGateContractTests(unittest.TestCase):
    def test_repository_locks_are_strict_and_route_artifacts_are_frozen(self) -> None:
        runtime = postgres_runtime.load_knowledge_database_runtime_lock(REPOSITORY_ROOT)
        route = route_evidence.load_agent_route_qualification_reference(REPOSITORY_ROOT)

        self.assertEqual(runtime.platform, "linux/arm64")
        self.assertEqual(route.outcome, "required-workload-routes-qualified")
        self.assertEqual(len(route.artifact_sha256), 15)
        self.assertIn("qualification.json", route.artifact_sha256)
        for relative, expected in {
            **route.input_sha256,
            **route.dependency_sha256,
        }.items():
            self.assertEqual(
                hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest(),
                expected,
            )

    def test_database_result_rejects_a_green_suite_with_skips(self) -> None:
        runtime = _runtime_lock()
        result = _database_result()
        result["skipped"] = 1

        with self.assertRaisesRegex(ValueError, "did not pass"):
            gate._validate_database_test_result(result, runtime)

    def test_portable_result_freezes_phase_scoped_modules_without_skips(self) -> None:
        suite = unittest.defaultTestLoader.loadTestsFromNames(
            list(gate._EXPECTED_PORTABLE_MODULES)
        )
        self.assertEqual(suite.countTestCases(), gate._EXPECTED_PORTABLE_TEST_COUNT)
        result = {
            "expectedFailures": 0,
            "modules": list(gate._EXPECTED_PORTABLE_MODULES),
            "schemaVersion": 1,
            "skipped": 0,
            "testsRun": gate._EXPECTED_PORTABLE_TEST_COUNT,
            "unexpectedSuccesses": 0,
        }
        gate._validate_portable_test_result(result)
        for field in ("expectedFailures", "skipped", "unexpectedSuccesses"):
            with self.subTest(field=field):
                failed = {**result, field: 1}
                with self.assertRaisesRegex(ValueError, "did not pass"):
                    gate._validate_portable_test_result(failed)

    def test_portable_identity_requires_the_database_runtime_packages(self) -> None:
        portable = runpy.run_path(
            str(REPOSITORY_ROOT / "verification/run-portable-server-suite.py")
        )
        self.assertEqual(
            portable["_REQUIRED_RUNTIME_PACKAGES"],
            gate._EXPECTED_PORTABLE_PACKAGES,
        )
        identity = {
            "lockSha256": "a" * 64,
            "packages": {name: "1.0" for name in gate._EXPECTED_PORTABLE_PACKAGES},
            "python": "3.12.11",
        }
        gate._validate_python_identity(identity, "a" * 64)
        del identity["packages"]["psycopg-binary"]
        with self.assertRaisesRegex(ValueError, "identity differs"):
            gate._validate_python_identity(identity, "a" * 64)

    def test_postgres_runner_adds_the_server_test_package_root(self) -> None:
        postgres_suite = runpy.run_path(
            str(
                REPOSITORY_ROOT
                / "verification/run-governed-knowledge-postgres-suite.py"
            )
        )
        server_root = REPOSITORY_ROOT / "server"
        previous_cwd = Path.cwd()
        try:
            os.chdir(server_root)
            with patch.object(sys, "path", ["sentinel"]):
                postgres_suite["_configure_server_test_imports"]()
                self.assertEqual(sys.path[0], str(server_root))
        finally:
            os.chdir(previous_cwd)

    def test_restart_probe_separates_concept_and_resource_identity(self) -> None:
        restart_probe = runpy.run_path(
            str(
                REPOSITORY_ROOT
                / "verification/run-governed-knowledge-restart-probe.py"
            )
        )
        with TemporaryDirectory() as directory:
            generation = restart_probe["_generation"](
                Path(directory),
                tenant_id="tenant-a",
                source_revision="restart-contract",
                body="Persistence sentinel is available.",
            )

        self.assertEqual(generation.concepts[0].concept_id, "projects/restart-probe")
        self.assertEqual(
            generation.concepts[0].frontmatter["resource"],
            "yap://tenant/tenant-a/project/restart-probe",
        )

    def test_agent_route_drift_contract_covers_all_transitive_owners(self) -> None:
        protected = (
            "server/src/yap_server/evaluation/agent_vllm_runtime.py",
            "server/src/yap_server/evaluation/agent_route_qualification_evidence.py",
            "server/src/yap_server/evaluation/governed_knowledge_gate.py",
            "server/src/yap_server/evaluation/vllm_runtime_metrics.py",
            "server/src/yap_server/evaluation/provider_runtime_observations.py",
            "server/src/yap_server/evaluation/private_json_evidence.py",
            "server/src/yap_server/knowledge/agent_reasoning_routes.py",
            "server/src/yap_server/knowledge/governed_rag_agent.py",
            "server/src/yap_server/knowledge/governed_knowledge_tools.py",
            "server/src/yap_server/knowledge/knowledge_tool_contract.py",
            "server/pyproject.toml",
            "server/uv.lock",
            "server/agent-workload-fixtures.json",
            "server/runtime/agent-vllm/Dockerfile",
            "server/runtime/agent-vllm/build-qwen-vllm-runtime.sh",
            "server/runtime/agent-vllm/THIRD_PARTY_NOTICES.md",
            "server/tests/evaluation/test_agent_model_final_response_retry.py",
            "server/tests/evaluation/test_agent_model_qualification.py",
            "server/tests/evaluation/test_agent_route_qualification_evidence.py",
            "server/tests/evaluation/test_governed_knowledge_gate.py",
            "server/tests/evaluation/test_agent_runtime_pressure.py",
            "server/tests/evaluation/test_agent_vllm_runtime.py",
            "server/tests/evaluation/test_vllm_runtime_metrics.py",
            "server/tests/knowledge/test_agent_reasoning_routes.py",
            "server/tests/knowledge/test_governed_rag_agent.py",
        )
        for path in protected:
            with self.subTest(path=path):
                self.assertTrue(route_evidence.is_agent_route_evidence_path(path))

    def test_agent_route_reference_rejects_protected_descendant_changes(self) -> None:
        reference = _current_route_reference()

        changed_paths = (
            "server/src/yap_server/evaluation/provider_runtime_observations.py",
            "server/src/yap_server/evaluation/agent_route_qualification_evidence.py",
            "server/src/yap_server/evaluation/governed_knowledge_gate.py",
            "server/tests/evaluation/test_agent_route_qualification_evidence.py",
            "server/tests/evaluation/test_governed_knowledge_gate.py",
        )
        for changed_path in changed_paths:
            with self.subTest(changed_path=changed_path):
                def runner(command, **_kwargs):
                    if "merge-base" in command:
                        return _completed(command)
                    if "diff" in command:
                        return _completed(command, stdout=f"{changed_path}\n")
                    raise AssertionError(command)

                with self.assertRaisesRegex(ValueError, "implementation changed"):
                    route_evidence._verify_unchanged_route_inputs(
                        REPOSITORY_ROOT,
                        checked_head="4" * 40,
                        reference=reference,
                        runner=runner,
                    )

    def test_agent_route_reference_rejects_dependency_hash_change(self) -> None:
        reference = _current_route_reference()
        reference = replace(
            reference,
            dependency_sha256={
                **reference.dependency_sha256,
                "server/uv.lock": "0" * 64,
            },
        )

        def runner(command, **_kwargs):
            if "merge-base" in command or "diff" in command:
                return _completed(command)
            raise AssertionError(command)

        with self.assertRaisesRegex(ValueError, "input changed"):
            route_evidence._verify_unchanged_route_inputs(
                REPOSITORY_ROOT,
                checked_head="4" * 40,
                reference=reference,
                runner=runner,
            )

    def test_local_offline_boundary_rejects_desktop_changes(self) -> None:
        def runner(command, **_kwargs):
            if "merge-base" in command:
                return _completed(command)
            if "diff" in command:
                return _completed(command, stdout="desktop/src/state.ts\n")
            raise AssertionError(command)

        with self.assertRaisesRegex(ValueError, "local/offline"):
            gate.verify_local_offline_dependency_boundary(
                REPOSITORY_ROOT,
                checked_head="4" * 40,
                runner=runner,
            )

    def test_receipt_cannot_be_published_inside_the_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            gate._validate_receipt_path(
                REPOSITORY_ROOT / "untracked-governed-knowledge-receipt.json",
                REPOSITORY_ROOT,
            )


def _runtime_lock() -> postgres_runtime.KnowledgeDatabaseRuntimeLock:
    return postgres_runtime.KnowledgeDatabaseRuntimeLock(
        image="pgvector/pgvector:pg17",
        platform="linux/arm64",
        manifest_digest=_MANIFEST_DIGEST,
        image_id=_IMAGE_ID,
        postgres_version="17.10-1.pgdg12+1",
        pgvector_version="0.8.6",
        lock_sha256="a" * 64,
    )


def _database_result() -> dict[str, object]:
    return {
        "modules": list(gate._EXPECTED_DATABASE_MODULES),
        "pgvectorVersion": "0.8.6",
        "postgresVersion": "17.10 (Debian 17.10-1.pgdg12+1)",
        "schemaVersion": 1,
        "skipped": 0,
        "testsRun": gate._EXPECTED_DATABASE_TEST_COUNT,
    }


def _current_route_reference() -> route_evidence.AgentRouteQualificationReference:
    inputs = {
        path: hashlib.sha256((REPOSITORY_ROOT / path).read_bytes()).hexdigest()
        for path in route_evidence._MODEL_INPUT_PATHS
    }
    dependencies = {
        path: hashlib.sha256((REPOSITORY_ROOT / path).read_bytes()).hexdigest()
        for path in route_evidence._MODEL_DEPENDENCY_PATHS
    }
    return route_evidence.AgentRouteQualificationReference(
        checked_head=_HEAD,
        outcome="required-workload-routes-qualified",
        evidence_sha256="d" * 64,
        input_sha256=inputs,
        dependency_sha256=dependencies,
        artifact_sha256={},
        lock_sha256="e" * 64,
    )


def _completed(command, *, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
