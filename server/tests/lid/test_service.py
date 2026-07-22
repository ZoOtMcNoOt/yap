from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.preflight import LidPreflightEngine
from yap_server.lid.service import LidPreflightService


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
            "componentId": "speechbrain-lid-preflight",
            "model": {
                "id": "speechbrain/lang-id-voxlingua107-ecapa",
                "revision": "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9",
            },
            "policyRevision": "speechbrain-two-window-v1",
            "scoreSemantics": "uncalibrated-log-posterior",
            "sourceSamples": request.source_samples,
            "observations": [
                {
                    "index": probe.index,
                    "probeSha256": probe.wav_sha256,
                    "sourceStartSample": probe.source_start_sample,
                    "sourceEndSample": probe.source_end_sample,
                    "voicedSamples": probe.voiced_samples,
                    "rawLabel": "en: English",
                    "topScore": -0.1,
                    "scoreMargin": 1.0,
                }
                for probe in request.probes
            ],
        }


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
                    service.run_envelope(
                        _envelope(self.lock, "job-service-cancel")
                    )
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
    pcm = (b"\x01\x00" * 128_000, b"\x02\x00" * 128_000)
    probes = []
    for index, (start, body) in enumerate(zip((0, 240_000), pcm, strict=True)):
        probes.append(
            {
                "index": index,
                "sourceStartSample": start,
                "sourceEndSample": start + 128_000,
                "voicedSamples": 128_000,
                "pcmByteLength": len(body),
                "pcmSha256": hashlib.sha256(body).hexdigest(),
                "vadIntervals": [
                    {
                        "startSample": start,
                        "endSampleExclusive": start + 128_000,
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
