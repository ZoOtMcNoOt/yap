from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from yap_server.meeting_transcription.batch_worker import (
    MeetingTranscriptionBatchWorker,
)
from yap_server.meeting_transcription.container_worker import (
    MeetingTranscriptionJob,
)
from yap_server.meeting_transcription.contract import MEETING_TRANSCRIPTION_POOL_ID
from yap_server.meeting_transcription.result_revisions import (
    load_meeting_result_authority,
)
from yap_server.pools.batch_contract import AsrRouteDecision, BatchAsrJob


SERVER_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = load_meeting_result_authority(
    SERVER_ROOT / "meeting-transcription-runtime.lock.json"
)


class _Worker:
    def __init__(self) -> None:
        self.jobs: list[MeetingTranscriptionJob] = []
        self.cancellations: list[threading.Event] = []
        self.closed = False

    def run(
        self,
        job: MeetingTranscriptionJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        self.jobs.append(job)
        self.cancellations.append(cancellation)
        return {"meeting": {"segments": []}}

    def close(self) -> None:
        self.closed = True


def _route(*, pool_id: str = MEETING_TRANSCRIPTION_POOL_ID) -> AsrRouteDecision:
    return AsrRouteDecision(
        provider_id="tiron",
        pool_id=pool_id,
        execution_mode="fixedBatch",
        model_revision=AUTHORITY.provenance.model.revision,
        provider_language="en",
    )


class MeetingTranscriptionBatchWorkerTests(unittest.TestCase):
    def test_adapts_the_owned_batch_job_without_reimplementing_the_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.wav"
            input_path.write_bytes(b"private canonical input")
            worker = _Worker()
            adapter = MeetingTranscriptionBatchWorker(
                worker=worker,
                authority=AUTHORITY,
            )
            cancellation = threading.Event()
            result = adapter.run(
                BatchAsrJob(
                    job_id="job-1",
                    input_path=input_path,
                    result_path=root / "meeting-worker-result.json",
                    language="en-US",
                    input_sha256="b" * 64,
                    route=_route(),
                    capture_manifest_sha256="a" * 64,
                    source_frame_count=32_000,
                ),
                cancellation,
            )

            self.assertEqual(result, {"meeting": {"segments": []}})
            self.assertEqual(len(worker.jobs), 1)
            meeting_job = worker.jobs[0]
            self.assertEqual(meeting_job.capture_manifest_sha256, "a" * 64)
            self.assertEqual(meeting_job.input_sha256, "b" * 64)
            self.assertEqual(meeting_job.language, "en")
            self.assertEqual(meeting_job.max_speakers, 8)
            self.assertEqual(meeting_job.frame_count, 32_000)
            self.assertIs(worker.cancellations[0], cancellation)

            adapter.close()
            self.assertTrue(worker.closed)

    def test_rejects_a_different_pool_or_missing_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.wav"
            input_path.write_bytes(b"input")
            adapter = MeetingTranscriptionBatchWorker(
                worker=_Worker(),
                authority=AUTHORITY,
            )
            for label, route, capture, frames in (
                ("pool", _route(pool_id="cohere-batch"), "a" * 64, 160),
                ("identity", _route(), None, None),
            ):
                with self.subTest(label):
                    with self.assertRaises(ValueError):
                        adapter.run(
                            BatchAsrJob(
                                job_id="job-1",
                                input_path=input_path,
                                result_path=root / "result.json",
                                language="en-US",
                                input_sha256="b" * 64,
                                route=route,
                                capture_manifest_sha256=capture,
                                source_frame_count=frames,
                            ),
                            threading.Event(),
                        )


if __name__ == "__main__":
    unittest.main()
