from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import wave

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.container_runtime import (
    ContainerLidWorker,
    reconcile_lid_containers,
    verify_lid_container_absent,
)
from yap_server.lid.worker_contract import load_lid_worker_request
from yap_server.pools.batch_contract import WorkerContainmentError
from yap_server.pools.container_runtime import (
    JOB_LABEL,
    OWNER_LABEL,
    REVISION_LABEL,
    RUNTIME_LABEL,
    STORAGE_LABEL,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"
IMAGE = "yap-lid@sha256:" + "a" * 64
HEAD = "b" * 40
CONTAINER_ID = "c" * 64
RUNTIME_ID = "lid-runtime-test-instance"


class LidContainerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lid_component_lock(LOCK_PATH)

    def test_builds_a_cpu_only_networkless_least_privilege_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            request_root = root / "request"
            model.mkdir()
            request_root.mkdir()
            request_path = _write_request(request_root, self.lock)
            request = load_lid_worker_request(request_path, self.lock)
            worker = _worker(model)

            command = worker.build_command(request, request_root)
            rendered = " ".join(command)

            self.assertIn("--pull never", rendered)
            self.assertIn("--cidfile", command)
            self.assertTrue(
                command[command.index("--cidfile") + 1].endswith(
                    ".yap-container-id"
                )
            )
            self.assertIn("--network none", rendered)
            self.assertIn("--read-only", command)
            self.assertIn("--cap-drop ALL", rendered)
            self.assertIn("no-new-privileges", rendered)
            self.assertIn("--user 10001:10001", rendered)
            self.assertIn("--pids-limit 64", rendered)
            self.assertIn("--memory 512m --memory-swap 512m", rendered)
            self.assertIn("--cpus 1", rendered)
            self.assertIn("OMP_NUM_THREADS=1", rendered)
            self.assertIn("OPENBLAS_NUM_THREADS=1", rendered)
            self.assertIn("/models/lid,readonly", rendered)
            self.assertIn("/request,readonly", rendered)
            self.assertNotIn("--device", command)
            self.assertNotIn("nvidia", rendered.casefold())

    def test_validates_output_against_the_host_request_and_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            request_root = root / "request"
            model.mkdir()
            request_root.mkdir()
            request_path = _write_request(request_root, self.lock)
            request = load_lid_worker_request(request_path, self.lock)
            payload = _result(request, self.lock)
            observed: list[list[str]] = []

            def runner(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                observed.append(command)
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

            actual = _worker(model, runner=runner).run(request, request_root)

            self.assertEqual(actual, payload)
            self.assertEqual(len(observed), 1)

            payload["observations"][0]["sourceStartSample"] += 1
            with self.assertRaisesRegex(RuntimeError, "violated the locked contract"):
                _worker(model, runner=runner).run(request, request_root)

    def test_real_execution_path_forces_container_cleanup_even_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            request_root = root / "request"
            model.mkdir()
            request_root.mkdir()
            request = load_lid_worker_request(
                _write_request(request_root, self.lock),
                self.lock,
            )
            removals: list[tuple[str, str]] = []

            def execute(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                Path(command[command.index("--cidfile") + 1]).write_text(
                    CONTAINER_ID,
                    encoding="utf-8",
                )
                raise RuntimeError("worker failed")

            def inspect(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(_expected_labels(request.request_id)),
                    "",
                )

            def remove(binary: str, container_id: str) -> None:
                removals.append((binary, container_id))

            worker = _worker(
                model,
                process_runner=execute,
                cleanup_runner=inspect,
                container_remover=remove,
            )
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                worker.run(request, request_root, cancellation=threading.Event())
            self.assertEqual(removals, [("docker", CONTAINER_ID)])
            self.assertFalse((request_root / ".yap-container-id").exists())

    def test_refuses_to_remove_a_container_when_immutable_labels_do_not_match(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            request_root = root / "request"
            model.mkdir()
            request_root.mkdir()
            request = load_lid_worker_request(
                _write_request(request_root, self.lock),
                self.lock,
            )
            removals: list[tuple[str, str]] = []

            def execute(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                Path(command[command.index("--cidfile") + 1]).write_text(
                    CONTAINER_ID,
                    encoding="utf-8",
                )
                raise RuntimeError("worker failed")

            def inspect(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                labels = _expected_labels(request.request_id)
                labels[RUNTIME_LABEL] = "foreign-runtime"
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(labels),
                    "",
                )

            worker = _worker(
                model,
                process_runner=execute,
                cleanup_runner=inspect,
                container_remover=lambda binary, identity: removals.append(
                    (binary, identity)
                ),
            )
            with self.assertRaisesRegex(
                WorkerContainmentError,
                "ownership was invalid",
            ):
                worker.run(request, request_root)
            self.assertEqual(removals, [])
            self.assertEqual(
                (request_root / ".yap-container-id").read_text(encoding="utf-8"),
                CONTAINER_ID,
            )

    def test_runner_failure_without_a_container_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            request_root = root / "request"
            model.mkdir()
            request_root.mkdir()
            request = load_lid_worker_request(
                _write_request(request_root, self.lock),
                self.lock,
            )

            def execute(
                _command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                raise TimeoutError("docker client timed out")

            with self.assertRaisesRegex(
                WorkerContainmentError,
                "identity was unavailable",
            ):
                _worker(model, process_runner=execute).run(request, request_root)

    def test_rejects_a_preexisting_container_identity_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            request_root = root / "request"
            model.mkdir()
            request_root.mkdir()
            request = load_lid_worker_request(
                _write_request(request_root, self.lock),
                self.lock,
            )
            (request_root / ".yap-container-id").write_text(
                CONTAINER_ID,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                WorkerContainmentError,
                "identity file already exists",
            ):
                _worker(model).run(request, request_root)

    def test_requires_immutable_image_checked_head_and_nonroot_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary)
            for arguments in (
                {"image": "yap-lid:latest"},
                {"checked_head": "short"},
                {"run_as_uid": 0},
                {"run_as_gid": 0},
            ):
                values: dict[str, object] = {
                    "image": IMAGE,
                    "model_dir": model,
                    "lock": self.lock,
                    "run_as_uid": 10001,
                    "run_as_gid": 10001,
                    "checked_head": HEAD,
                    "storage_namespace": "lid-test",
                }
                values.update(arguments)
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    ContainerLidWorker(**values)

    def test_startup_reconciles_only_owned_lid_containers(self) -> None:
        calls: list[list[str]] = []

        def runner(
            command: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            output = "c" * 64 + "\n" if command[1:3] == ["container", "ls"] else ""
            return subprocess.CompletedProcess(command, 0, output, "")

        removed = reconcile_lid_containers(
            "docker-test",
            storage_namespace="lid-test",
            runner=runner,
        )

        self.assertEqual(removed, 1)
        self.assertIn(
            "label=com.mcnatg1.yap.owner=lid-preflight",
            calls[0],
        )
        self.assertEqual(
            calls[1],
            ["docker-test", "container", "rm", "--force", "c" * 64],
        )

    def test_restart_requires_the_retained_exact_container_id_to_be_absent(
        self,
    ) -> None:
        calls: list[list[str]] = []

        def missing(
            command: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "Error: No such container",
            )

        verify_lid_container_absent(
            "docker-test",
            CONTAINER_ID,
            runner=missing,
        )
        self.assertEqual(
            calls,
            [["docker-test", "container", "inspect", CONTAINER_ID]],
        )

        def present(
            command: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, "{}", "")

        with self.assertRaisesRegex(
            WorkerContainmentError,
            "still exists",
        ):
            verify_lid_container_absent(
                "docker-test",
                CONTAINER_ID,
                runner=present,
            )


def _worker(model: Path, **overrides: object) -> ContainerLidWorker:
    values: dict[str, object] = {
        "image": IMAGE,
        "model_dir": model,
        "lock": load_lid_component_lock(LOCK_PATH),
        "run_as_uid": 10001,
        "run_as_gid": 10001,
        "checked_head": HEAD,
        "storage_namespace": "lid-test",
        "runtime_instance_id": RUNTIME_ID,
    }
    values.update(overrides)
    return ContainerLidWorker(**values)


def _expected_labels(request_id: str) -> dict[str, str]:
    return {
        OWNER_LABEL: "lid-preflight",
        STORAGE_LABEL: "lid-test",
        RUNTIME_LABEL: RUNTIME_ID,
        JOB_LABEL: request_id,
        REVISION_LABEL: HEAD,
    }


def _write_request(root: Path, _lock: object) -> Path:
    probes: list[dict[str, object]] = []
    for index, start in enumerate(range(0, 480_000, 96_000)):
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16_000)
            writer.writeframes(b"\x00\x00" * 96_000)
        encoded = output.getvalue()
        file_name = f"probe-{index}.wav"
        (root / file_name).write_bytes(encoded)
        probes.append(
            {
                "index": index,
                "fileName": file_name,
                "wavSha256": hashlib.sha256(encoded).hexdigest(),
                "sourceStartSample": start,
                "sourceEndSample": start + 96_000,
                "voicedSamples": 96_000,
            }
        )
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "requestId": "lid-runtime-test",
                "sourceSamples": 480_000,
                "probes": probes,
            }
        ),
        encoding="utf-8",
    )
    return request_path


def _result(request: object, lock: object) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "requestId": request.request_id,
        "componentId": lock.component_id,
        "model": {"id": lock.model.model_id, "revision": lock.model.revision},
        "policyRevision": lock.policy.revision,
        "scoreSemantics": lock.policy.score_semantics,
        "sourceSamples": request.source_samples,
        "observations": [
            {
                "index": probe.index,
                "probeSha256": probe.wav_sha256,
                "sourceStartSample": probe.source_start_sample,
                "sourceEndSample": probe.source_end_sample,
                "voicedSamples": probe.voiced_samples,
                "rawLabel": "en",
                "topScore": -0.1,
                "scoreMargin": 1.2,
            }
            for probe in request.probes
        ],
    }


if __name__ == "__main__":
    unittest.main()
