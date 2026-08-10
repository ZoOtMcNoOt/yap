from __future__ import annotations

import hashlib
import json
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
            "server/src/yap_server/evaluation/vllm_runtime_metrics.py",
            "server/src/yap_server/evaluation/provider_runtime_observations.py",
            "server/src/yap_server/knowledge/agent_reasoning_routes.py",
            "server/src/yap_server/knowledge/governed_rag_agent.py",
            "server/src/yap_server/knowledge/governed_knowledge_tools.py",
            "server/src/yap_server/knowledge/knowledge_tool_contract.py",
            "server/pyproject.toml",
            "server/uv.lock",
            "server/agent-workload-fixtures.json",
            "server/tests/evaluation/test_agent_model_qualification.py",
            "server/tests/evaluation/test_agent_runtime_pressure.py",
            "server/tests/evaluation/test_agent_vllm_runtime.py",
            "server/tests/evaluation/test_vllm_runtime_metrics.py",
            "server/tests/knowledge/test_agent_reasoning_routes.py",
            "server/tests/knowledge/test_governed_rag_agent.py",
        )
        for path in protected:
            with self.subTest(path=path):
                self.assertTrue(route_evidence.is_agent_route_evidence_path(path))
        self.assertFalse(
            route_evidence.is_agent_route_evidence_path(
                "server/src/yap_server/evaluation/governed_knowledge_gate.py"
            )
        )
        self.assertFalse(
            route_evidence.is_agent_route_evidence_path(
                "server/tests/evaluation/test_agent_route_qualification_evidence.py"
            )
        )

    def test_reviewed_cancellation_fixture_transition_is_exact(self) -> None:
        path = "server/tests/knowledge/test_vllm_reasoning_client.py"
        reference = route_evidence.load_agent_route_qualification_reference(
            REPOSITORY_ROOT
        )
        self.assertTrue(route_evidence.is_agent_route_evidence_path(path))
        self.assertTrue(
            route_evidence._is_allowed_protected_transition(
                REPOSITORY_ROOT,
                path=path,
                reference=reference,
                runner=subprocess.run,
            )
        )
        with patch.object(
            route_evidence,
            "read_bounded_regular_file",
            return_value=b"additional semantic drift",
        ):
            self.assertFalse(
                route_evidence._is_allowed_protected_transition(
                    REPOSITORY_ROOT,
                    path=path,
                    reference=reference,
                    runner=subprocess.run,
                )
            )

    def test_agent_route_reference_rejects_protected_descendant_changes(self) -> None:
        reference = route_evidence.load_agent_route_qualification_reference(
            REPOSITORY_ROOT
        )

        def runner(command, **_kwargs):
            if "merge-base" in command:
                return _completed(command)
            if "diff" in command:
                return _completed(
                    command,
                    stdout=(
                        "server/src/yap_server/evaluation/"
                        "provider_runtime_observations.py\n"
                    ),
                )
            raise AssertionError(command)

        with self.assertRaisesRegex(ValueError, "implementation changed"):
            route_evidence._verify_unchanged_route_inputs(
                REPOSITORY_ROOT,
                checked_head="4" * 40,
                reference=reference,
                runner=runner,
            )

    def test_agent_route_reference_rejects_dependency_hash_change(self) -> None:
        reference = route_evidence.load_agent_route_qualification_reference(
            REPOSITORY_ROOT
        )
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


class OwnedPostgresKnowledgeRuntimeTests(unittest.TestCase):
    def test_wrong_image_identity_is_rejected_before_launch(self) -> None:
        runner = _FakeDockerRunner()
        locked = _runtime_lock()
        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=postgres_runtime.KnowledgeDatabaseRuntimeLock(
                image=locked.image,
                platform=locked.platform,
                manifest_digest=locked.manifest_digest,
                image_id="sha256:" + "5" * 64,
                postgres_version=locked.postgres_version,
                pgvector_version=locked.pgvector_version,
                lock_sha256=locked.lock_sha256,
            ),
            runner=runner,
        )

        with self.assertRaisesRegex(ValueError, "differs from its lock"):
            runtime.start(timeout_seconds=10)

        self.assertFalse(
            any(command[:2] == ["docker", "run"] for command in runner.commands)
        )

    def test_launches_bounded_immutable_runtime_restarts_and_tears_down(self) -> None:
        runner = _FakeDockerRunner()
        runtime = _owned_runtime(runner)

        started = runtime.start(timeout_seconds=10)
        restart = runtime.restart(timeout_seconds=10)
        teardown = runtime.stop(timeout_seconds=5)

        launch = next(
            command for command in runner.commands if command[:2] == ["docker", "run"]
        )
        network_create = next(
            command
            for command in runner.commands
            if command[:3] == ["docker", "network", "create"]
        )
        self.assertNotIn("--internal", network_create)
        self.assertEqual(launch[launch.index("--pull") + 1], "never")
        self.assertEqual(launch[launch.index("--memory") + 1], "2g")
        self.assertEqual(launch[launch.index("--cpus") + 1], "2")
        self.assertEqual(launch[launch.index("--pids-limit") + 1], "256")
        self.assertEqual(launch[-1], _IMAGE_ID)
        readiness = next(
            command
            for command in runner.commands
            if command[:4]
            == ["docker", "exec", postgres_runtime._CONTAINER_NAME, "sh"]
        )
        self.assertIn("--host 127.0.0.1", readiness[-1])
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', readiness[-1])
        self.assertNotIn(runner.password, readiness[-1])
        self.assertEqual(started.host_port, 35432)
        self.assertTrue(all(restart.values()))
        self.assertTrue(all(teardown.values()))
        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_public_port_binding_is_rejected_and_contained(self) -> None:
        runner = _FakeDockerRunner(host_ip="0.0.0.0")
        runtime = _owned_runtime(runner)

        with self.assertRaisesRegex(ValueError, "policy differs"):
            runtime.start(timeout_seconds=10)

        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_public_binding_with_surviving_listener_fails_containment(self) -> None:
        runner = _FakeDockerRunner(host_ip="0.0.0.0")
        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=_runtime_lock(),
            runner=runner,
            listener_absent=lambda _port: False,
            process_absent=lambda _pid: True,
        )

        with self.assertRaisesRegex(RuntimeError, "containment did not complete"):
            runtime.start(timeout_seconds=10)

    def test_container_identity_and_resource_bounds_are_read_back(self) -> None:
        for field, value, error_type, message in (
            ("container_id", "c" * 64, RuntimeError, "identity"),
            ("memory_bytes", 1, ValueError, "container"),
            ("extra_network", True, ValueError, "container"),
            ("network_internal", True, ValueError, "network"),
        ):
            with self.subTest(field=field):
                runner = _FakeDockerRunner(**{field: value})
                runtime = _owned_runtime(runner)
                with self.assertRaisesRegex(error_type, message):
                    runtime.start(timeout_seconds=10)
                self.assertFalse(runner.container_exists)

    def test_malformed_launch_identity_with_survivors_fails_containment(self) -> None:
        runner = _FakeDockerRunner(run_stdout="malformed")
        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=_runtime_lock(),
            runner=runner,
            listener_absent=lambda _port: False,
            process_absent=lambda _pid: False,
        )

        with self.assertRaisesRegex(RuntimeError, "containment did not complete"):
            runtime.start(timeout_seconds=10)

    def test_initial_inspect_failure_retries_by_immutable_container_id(self) -> None:
        runner = _FakeDockerRunner(inspect_failures=1)
        observed_ports: list[int] = []
        observed_processes: list[int] = []
        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=_runtime_lock(),
            runner=runner,
            listener_absent=lambda port: not observed_ports.append(port),
            process_absent=lambda process: not observed_processes.append(process),
        )

        with self.assertRaisesRegex(RuntimeError, "command failed"):
            runtime.start(timeout_seconds=10)

        self.assertEqual(observed_ports, [35432])
        self.assertEqual(observed_processes, [4321])
        self.assertIn(
            ["docker", "container", "inspect", _CONTAINER_ID], runner.commands
        )

    def test_unobservable_created_container_fails_closed(self) -> None:
        runner = _FakeDockerRunner(inspect_failures=2)
        runtime = _owned_runtime(runner)

        with self.assertRaisesRegex(RuntimeError, "could not be observed"):
            runtime.start(timeout_seconds=10)

        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_exit_before_readiness_is_contained(self) -> None:
        runner = _FakeDockerRunner(exit_before_ready=True)
        runtime = _owned_runtime(runner, sleep=lambda _seconds: None)

        with self.assertRaisesRegex(RuntimeError, "exited before readiness"):
            runtime.start(timeout_seconds=10)

        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_failed_teardown_keeps_identity_for_verified_containment(self) -> None:
        runner = _FakeDockerRunner()
        listener_results = iter((False, True))
        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=_runtime_lock(),
            runner=runner,
            listener_absent=lambda _port: next(listener_results),
            process_absent=lambda _pid: True,
        )
        runtime.start(timeout_seconds=10)

        with self.assertRaisesRegex(RuntimeError, "teardown did not complete"):
            runtime.stop(timeout_seconds=5)
        teardown = runtime.contain_failed_run()

        self.assertTrue(all(teardown.values()))


def _owned_runtime(runner, *, sleep=lambda _seconds: None):
    return postgres_runtime.OwnedPostgresKnowledgeRuntime(
        checked_head=_HEAD,
        runtime_lock=_runtime_lock(),
        runner=runner,
        sleep=sleep,
        listener_absent=lambda _port: True,
        process_absent=lambda _pid: True,
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
        "testsRun": 9,
    }


class _FakeDockerRunner:
    def __init__(
        self,
        *,
        host_ip: str = "127.0.0.1",
        exit_before_ready: bool = False,
        container_id: str = _CONTAINER_ID,
        memory_bytes: int = postgres_runtime._MEMORY_BYTES,
        extra_network: bool = False,
        network_internal: bool = False,
        run_stdout: str = _CONTAINER_ID,
        inspect_failures: int = 0,
    ) -> None:
        self.host_ip = host_ip
        self.exit_before_ready = exit_before_ready
        self.inspected_container_id = container_id
        self.memory_bytes = memory_bytes
        self.extra_network = extra_network
        self.network_internal = network_internal
        self.run_stdout = run_stdout
        self.inspect_failures = inspect_failures
        self.inspect_attempts = 0
        self.container_exists = False
        self.network_exists = False
        self.volume_exists = False
        self.password = ""
        self.readiness_polled = False
        self.process_id = 4321
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        command = list(command)
        self.commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return _completed(
                command,
                stdout=json.dumps(
                    [
                        {
                            "Os": "linux",
                            "Architecture": "arm64",
                            "Id": _IMAGE_ID,
                            "RepoDigests": [
                                f"docker.io/pgvector/pgvector@{_MANIFEST_DIGEST}"
                            ],
                        }
                    ]
                ),
            )
        if command[:3] == ["docker", "volume", "create"]:
            self.volume_exists = True
            return _completed(command, stdout=postgres_runtime._VOLUME_NAME + "\n")
        if command[:3] == ["docker", "volume", "inspect"]:
            if not self.volume_exists:
                return _completed(command, returncode=1)
            return _completed(
                command,
                stdout=json.dumps(
                    [
                        {
                            "Name": postgres_runtime._VOLUME_NAME,
                            "Driver": "local",
                            "Labels": self._labels(),
                        }
                    ]
                ),
            )
        if command[:3] == ["docker", "volume", "rm"]:
            self.volume_exists = False
            return _completed(command, stdout=postgres_runtime._VOLUME_NAME + "\n")
        if command[:3] == ["docker", "network", "create"]:
            self.network_exists = True
            return _completed(command, stdout="network-id\n")
        if command[:3] == ["docker", "network", "inspect"]:
            if not self.network_exists:
                return _completed(command, returncode=1)
            return _completed(
                command,
                stdout=json.dumps(
                    [
                        {
                            "Name": postgres_runtime._NETWORK_NAME,
                            "Driver": "bridge",
                            "Internal": self.network_internal,
                            "Labels": self._labels(),
                        }
                    ]
                ),
            )
        if command[:3] == ["docker", "network", "rm"]:
            self.network_exists = False
            return _completed(command, stdout=postgres_runtime._NETWORK_NAME + "\n")
        if command[:2] == ["docker", "run"]:
            self.container_exists = True
            password_entry = next(
                value for value in command if value.startswith("POSTGRES_PASSWORD=")
            )
            self.password = password_entry.split("=", 1)[1]
            return _completed(command, stdout=self.run_stdout + "\n")
        if command[:3] == ["docker", "container", "inspect"]:
            if not self.container_exists or (
                self.exit_before_ready and self.readiness_polled
            ):
                return _completed(command, returncode=1)
            self.inspect_attempts += 1
            if self.inspect_attempts <= self.inspect_failures:
                return _completed(command, returncode=1)
            return _completed(
                command, stdout=json.dumps([self._container_inspection()])
            )
        if command[:3] == ["docker", "exec", postgres_runtime._CONTAINER_NAME]:
            if command[3] == "sh":
                self.readiness_polled = True
                return _completed(
                    command,
                    returncode=1 if self.exit_before_ready else 0,
                    stdout="" if self.exit_before_ready else "1\n",
                )
            if command[3] == "dpkg-query":
                return _completed(command, stdout="17.10-1.pgdg12+1")
        if command[:2] == ["docker", "restart"]:
            self.process_id = 4322
            return _completed(command, stdout=postgres_runtime._CONTAINER_NAME + "\n")
        if command[:2] == ["docker", "stop"]:
            return _completed(command, stdout=postgres_runtime._CONTAINER_NAME + "\n")
        if command[:3] == ["docker", "rm", postgres_runtime._CONTAINER_NAME] or command[
            :3
        ] == ["docker", "rm", "--force"]:
            self.container_exists = False
            return _completed(command, stdout=postgres_runtime._CONTAINER_NAME + "\n")
        if (
            command[:2]
            in (
                ["docker", "ps"],
                ["docker", "network"],
                ["docker", "volume"],
            )
            and "ls" in command
            or command[:2] == ["docker", "ps"]
        ):
            exists = {
                "ps": self.container_exists,
                "network": self.network_exists,
                "volume": self.volume_exists,
            }[command[1]]
            return _completed(command, stdout=_CONTAINER_ID + "\n" if exists else "")
        raise AssertionError(f"unexpected command: {command}")

    def _labels(self) -> dict[str, str]:
        return {
            "io.yap.owner": postgres_runtime._OWNER_LABEL,
            "io.yap.revision": _HEAD,
        }

    def _container_inspection(self) -> dict[str, object]:
        binding = [{"HostIp": self.host_ip, "HostPort": "35432"}]
        return {
            "Id": self.inspected_container_id,
            "Name": f"/{postgres_runtime._CONTAINER_NAME}",
            "Image": _IMAGE_ID,
            "State": {"Running": True, "Pid": self.process_id},
            "Config": {
                "Labels": self._labels(),
                "Env": [
                    f"POSTGRES_USER={postgres_runtime._DATABASE_USER}",
                    f"POSTGRES_DB={postgres_runtime._DATABASE_NAME}",
                    f"POSTGRES_PASSWORD={self.password}",
                ],
            },
            "HostConfig": {
                "NetworkMode": postgres_runtime._NETWORK_NAME,
                "Memory": self.memory_bytes,
                "NanoCpus": postgres_runtime._NANO_CPUS,
                "PidsLimit": postgres_runtime._PIDS_LIMIT,
                "PortBindings": {
                    "5432/tcp": [{"HostIp": self.host_ip, "HostPort": ""}]
                },
            },
            "NetworkSettings": {
                "Ports": {"5432/tcp": binding},
                "Networks": {
                    postgres_runtime._NETWORK_NAME: {},
                    **({"unexpected": {}} if self.extra_network else {}),
                },
            },
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": postgres_runtime._VOLUME_NAME,
                    "Destination": "/var/lib/postgresql/data",
                    "RW": True,
                }
            ],
        }


def _completed(command, *, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
