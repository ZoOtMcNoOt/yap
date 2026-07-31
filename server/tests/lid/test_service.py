from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from yap_server.auth import PrincipalKey
from yap_server.lid import service as lid_service_module
from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.errors import (
    LidPreflightContainmentError,
    LidPreflightUnavailable,
)
from yap_server.lid.preflight import LidPreflightEngine
from yap_server.lid.service import LidPreflightService
from yap_server.pools.batch_contract import WorkerContainmentError


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"
CATALOG_REVISION = "c" * 64


class _Worker:
    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.started = threading.Event()

    def run(
        self,
        request: object,
        _request_root: Path,
        cancellation: threading.Event | None = None,
    ) -> dict[str, object]:
        self.started.set()
        while self.block:
            if cancellation is not None and cancellation.is_set():
                raise RuntimeError("cancelled")
            time.sleep(0.01)
        return {
            "schemaVersion": 1,
            "requestId": request.request_id,
            "componentId": "ambernet-batch-language-preflight",
            "model": {
                "id": "nvidia/nemo/langid_ambernet",
                "revision": "1.12.0",
            },
            "policyRevision": "ambernet-stratified-five-region-v1",
            "scoreSemantics": "mean-logit-log-softmax",
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
                    "scoreMargin": 1.0,
                }
                for probe in request.probes
            ],
        }


class _ContainmentWorker(_Worker):
    def run(
        self,
        request: object,
        _request_root: Path,
        cancellation: threading.Event | None = None,
    ) -> dict[str, object]:
        del request, cancellation
        self.started.set()
        raise WorkerContainmentError("container identity could not be verified")


class _CancelledContainmentWorker(_Worker):
    def run(
        self,
        request: object,
        _request_root: Path,
        cancellation: threading.Event | None = None,
    ) -> dict[str, object]:
        del request
        self.started.set()
        assert cancellation is not None
        cancellation.set()
        raise WorkerContainmentError("container cleanup failed after cancellation")


class LidPreflightServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lid_component_lock(LOCK_PATH)

    def test_binds_result_and_removes_every_transient_audio_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root, _Worker())

            result = service.run_envelope(_envelope(self.lock, "job-service"))

            self.assertEqual(result["status"], "suggestion")
            self.assertEqual(result["suggestedLocale"], "en-US")
            self.assertEqual(result["sourcePcmSha256"], "a" * 64)
            self.assertEqual(result["catalogRevision"], CATALOG_REVISION)
            self.assertEqual(list(root.iterdir()), [])

    def test_cancellation_interrupts_work_and_still_removes_probe_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _Worker(block=True)
            service = self._service(root, worker)
            failures: list[BaseException] = []

            def invoke() -> None:
                try:
                    service.run_envelope(_envelope(self.lock, "job-service-cancel"))
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=invoke)
            thread.start()
            self.assertTrue(worker.started.wait(timeout=2))
            self.assertTrue(service.cancel("job-service-cancel"))
            thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIn("cancel", str(failures[0]))
            self.assertEqual(list(root.iterdir()), [])

    def test_cross_owner_cancellation_is_indistinguishable_from_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _Worker(block=True)
            service = self._service(root, worker)
            owner = PrincipalKey("tenant-a", "subject-a")
            other = PrincipalKey("tenant-a", "subject-b")
            failures: list[BaseException] = []

            def invoke() -> None:
                try:
                    service.run_envelope(
                        _envelope(self.lock, "job-owner-cancel"),
                        owner=owner,
                    )
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=invoke)
            thread.start()
            self.assertTrue(worker.started.wait(timeout=2))
            self.assertFalse(service.cancel("job-owner-cancel", owner=other))
            self.assertFalse(service.cancel("unknown-request", owner=owner))
            self.assertTrue(service.cancel("job-owner-cancel", owner=owner))
            thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIn("cancel", str(failures[0]))

    def test_accepted_cancellation_cannot_race_with_a_successful_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _Worker()
            service = self._service(root, worker)
            failures: list[BaseException] = []
            results: list[dict[str, object]] = []
            cleanup_started = threading.Event()
            release_cleanup = threading.Event()
            remove_request = lid_service_module.remove_materialized_lid_request

            def blocked_cleanup(materialized: object) -> None:
                cleanup_started.set()
                if not release_cleanup.wait(timeout=2):
                    raise TimeoutError("test cleanup release timed out")
                remove_request(materialized)

            def invoke() -> None:
                try:
                    results.append(
                        service.run_envelope(
                            _envelope(self.lock, "job-completion-race")
                        )
                    )
                except BaseException as error:
                    failures.append(error)

            with patch.object(
                lid_service_module,
                "remove_materialized_lid_request",
                side_effect=blocked_cleanup,
            ):
                thread = threading.Thread(target=invoke)
                thread.start()
                self.assertTrue(cleanup_started.wait(timeout=2))
                self.assertTrue(service.cancel("job-completion-race"))
                release_cleanup.set()
                thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(results, [])
            self.assertEqual(len(failures), 1)
            self.assertIn("cancel", str(failures[0]))
            self.assertEqual(list(root.iterdir()), [])

    def test_close_waits_for_active_probe_cleanup_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = _Worker(block=True)
            service = self._service(root, worker)
            failures: list[BaseException] = []

            def invoke() -> None:
                try:
                    service.run_envelope(_envelope(self.lock, "job-close"))
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=invoke)
            thread.start()
            self.assertTrue(worker.started.wait(timeout=2))

            service.close()

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIn("cancel", str(failures[0]))
            self.assertEqual(list(root.iterdir()), [])
            service.close()

    def test_container_containment_failure_fences_and_retains_recovery_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root, _ContainmentWorker())

            with self.assertRaisesRegex(
                WorkerContainmentError,
                "identity could not be verified",
            ):
                service.run_envelope(_envelope(self.lock, "job-containment"))

            self.assertTrue(service.fenced)
            retained = list(root.iterdir())
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0].name, "lid-job-containment")
            with self.assertRaisesRegex(
                LidPreflightUnavailable,
                "transient containment could not be verified",
            ):
                service.run_envelope(_envelope(self.lock, "job-after-fence"))
            with self.assertRaisesRegex(
                LidPreflightUnavailable,
                "transient containment could not be verified",
            ):
                service.close()

    def test_containment_failure_remains_observable_after_cancellation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root, _CancelledContainmentWorker())

            with self.assertRaisesRegex(
                WorkerContainmentError,
                "cleanup failed after cancellation",
            ):
                service.run_envelope(_envelope(self.lock, "job-cancel-containment"))

            self.assertTrue(service.fenced)
            self.assertTrue((root / "lid-job-cancel-containment").is_dir())

    def test_staging_cleanup_failure_fences_before_materialization_returns(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root, _Worker())

            def fail_staging(*_args: object, **kwargs: object) -> object:
                destination = Path(kwargs["destination"])
                destination.mkdir()
                (destination / "retained.part").write_bytes(b"retained")
                raise LidPreflightContainmentError(
                    "private staging could not be removed"
                )

            with (
                patch.object(
                    lid_service_module,
                    "materialize_lid_transport_request",
                    side_effect=fail_staging,
                ),
                self.assertRaisesRegex(
                    LidPreflightContainmentError,
                    "staging could not be removed",
                ),
            ):
                service.run_envelope(_envelope(self.lock, "job-staging-fence"))

            self.assertTrue(service.fenced)
            self.assertTrue((root / "lid-job-staging-fence").is_dir())
            with self.assertRaisesRegex(
                LidPreflightUnavailable,
                "transient containment could not be verified",
            ):
                service.run_envelope(_envelope(self.lock, "job-after-staging"))

    def _service(self, root: Path, worker: _Worker) -> LidPreflightService:
        engine = LidPreflightEngine(
            lock=self.lock,
            worker=worker,
            enabled_fixed_locales=("en-US",),
        )
        return LidPreflightService(
            lock=self.lock,
            engine=engine,
            work_root=root,
            catalog_revision=CATALOG_REVISION,
        )


def _envelope(lock: object, request_id: str) -> bytes:
    pcm = tuple(bytes((index + 1, 0)) * 96_000 for index in range(5))
    probes = []
    for index, (start, body) in enumerate(
        zip(range(0, 480_000, 96_000), pcm, strict=True)
    ):
        probes.append(
            {
                "index": index,
                "sourceStartSample": start,
                "sourceEndSample": start + 96_000,
                "voicedSamples": 96_000,
                "pcmByteLength": len(body),
                "pcmSha256": hashlib.sha256(body).hexdigest(),
                "vadIntervals": [
                    {
                        "startSample": start,
                        "endSampleExclusive": start + 96_000,
                    }
                ],
            }
        )
    manifest = json.dumps(
        {
            "schemaVersion": 1,
            "requestId": request_id,
            "sourceSamples": 480_000,
            "sourcePcmSha256": "a" * 64,
            "catalogRevision": CATALOG_REVISION,
            "policyRevision": lock.policy.revision,
            "probes": probes,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return len(manifest).to_bytes(4, "big") + manifest + b"".join(pcm)


if __name__ == "__main__":
    unittest.main()
