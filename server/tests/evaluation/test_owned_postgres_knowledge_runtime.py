"""Focused lifecycle tests for the owned Postgres knowledge runtime."""

from __future__ import annotations

import json
import subprocess
import unittest

from yap_server.evaluation import owned_postgres_knowledge_runtime as postgres_runtime


_IMAGE_ID = "sha256:" + "4" * 64
_MANIFEST_DIGEST = "sha256:" + "f" * 64
_HEAD = "3" * 40
_CONTAINER_ID = "b" * 64


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
        observed_ports: list[int] = []
        observed_processes: list[int] = []

        def listener_absent(port: int) -> bool:
            observed_ports.append(port)
            return True

        def process_absent(process: int) -> bool:
            observed_processes.append(process)
            return True

        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=_runtime_lock(),
            runner=runner,
            sleep=lambda _seconds: None,
            listener_absent=listener_absent,
            process_absent=process_absent,
        )

        started = runtime.start(timeout_seconds=10)
        restarted = runtime.restart(timeout_seconds=10)
        observed_ports.clear()
        observed_processes.clear()
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
        self.assertEqual(restarted.host_port, 35433)
        self.assertNotEqual(restarted.process_id, started.process_id)
        self.assertEqual(restarted.container_id, started.container_id)
        self.assertTrue(all(teardown.values()))
        self.assertEqual(set(observed_ports), {35432, 35433})
        self.assertEqual(set(observed_processes), {4321, 4322})
        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_containment_recovers_one_failed_post_restart_inspection(self) -> None:
        runner = _FakeDockerRunner()
        runtime = _owned_runtime(runner)

        runtime.start(timeout_seconds=10)
        runner.inspect_failures = runner.inspect_attempts + 1
        with self.assertRaisesRegex(RuntimeError, "command failed"):
            runtime.restart(timeout_seconds=10)
        teardown = runtime.contain_failed_run()

        self.assertTrue(all(teardown.values()))
        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_unobservable_post_restart_identity_fails_containment(self) -> None:
        runner = _FakeDockerRunner()
        runtime = _owned_runtime(runner)

        runtime.start(timeout_seconds=10)
        runner.inspect_failures = runner.inspect_attempts + 2
        with self.assertRaisesRegex(RuntimeError, "command failed"):
            runtime.restart(timeout_seconds=10)
        with self.assertRaisesRegex(RuntimeError, "identity could not be observed"):
            runtime.contain_failed_run()

        self.assertFalse(runner.container_exists)
        self.assertFalse(runner.network_exists)
        self.assertFalse(runner.volume_exists)

    def test_restart_rejects_a_surviving_previous_loopback_listener(self) -> None:
        runner = _FakeDockerRunner()
        runtime = postgres_runtime.OwnedPostgresKnowledgeRuntime(
            checked_head=_HEAD,
            runtime_lock=_runtime_lock(),
            runner=runner,
            sleep=lambda _seconds: None,
            listener_absent=lambda port: port != 35432,
            process_absent=lambda _pid: True,
        )

        runtime.start(timeout_seconds=10)
        with self.assertRaisesRegex(RuntimeError, "restart identity differs"):
            runtime.restart(timeout_seconds=10)
        with self.assertRaisesRegex(RuntimeError, "containment did not complete"):
            runtime.contain_failed_run()

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
        self.host_port = 35432
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
            self.host_port = 35433
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
        binding = [{"HostIp": self.host_ip, "HostPort": str(self.host_port)}]
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
