from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

from yap_server.meeting_transcription.container_worker import (
    ContainerMeetingTranscriptionWorker,
    MeetingTranscriptionJob,
)
from yap_server.pools.batch_contract import WorkerExecutionError


SERVER_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK = SERVER_ROOT / "meeting-transcription-runtime.lock.json"
RUNTIME_LOCK_SHA256 = hashlib.sha256(RUNTIME_LOCK.read_bytes()).hexdigest()
CHECKED_HEAD = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64


def _write_wav(path: Path, *, frames: int = 16_000) -> str:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * frames)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job(root: Path, *, frames: int = 16_000) -> MeetingTranscriptionJob:
    input_path = root / "meeting.wav"
    input_sha256 = _write_wav(input_path, frames=frames)
    return MeetingTranscriptionJob(
        job_id="meeting-1",
        input_path=input_path,
        result_path=root / "meeting-result.json",
        input_sha256=input_sha256,
        capture_manifest_sha256="c" * 64,
        language="en",
        frame_count=frames,
    )


def _result(job: MeetingTranscriptionJob) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "jobId": job.job_id,
        "captureManifestSha256": job.capture_manifest_sha256,
        "model": {
            "id": "Trelis/tiron",
            "revision": "90bc0a4d198cd5cf6679b0e478375ba3a0040575",
            "runtimeHarnessRevision": "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
            "speakerEncoderRevision": "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
            "applicationRevision": CHECKED_HEAD,
            "runtimeLockSha256": RUNTIME_LOCK_SHA256,
        },
        "audio": {
            "sha256": job.input_sha256,
            "durationMs": job.duration_ms,
            "sampleRateHz": 16_000,
            "frameCount": job.frame_count,
        },
        "meeting": {
            "language": "en",
            "sessionSpeakerIds": ["speaker-1"],
            "turns": [
                {
                    "index": 0,
                    "sessionSpeakerId": "speaker-1",
                    "startSample": 0,
                    "endSample": 13_760,
                    "text": "hello there",
                }
            ],
            "numDecodeWindows": 1,
            "sourceTimeUnit": "samples",
            "speakerCapacityDegradation": None,
        },
        "runtime": {
            "device": "cuda:0",
            "dtype": "bfloat16",
            "constrainedDecoding": True,
            "twoPass": True,
        },
    }


class ContainerMeetingTranscriptionWorkerTests(unittest.TestCase):
    def _worker(
        self,
        root: Path,
        *,
        runner: object | None = None,
    ) -> ContainerMeetingTranscriptionWorker:
        root.mkdir(parents=True, exist_ok=True)
        model_dir = root / "tiron"
        speaker_encoder_dir = root / "ecapa"
        model_dir.mkdir()
        speaker_encoder_dir.mkdir()
        return ContainerMeetingTranscriptionWorker(
            image=IMAGE_ID,
            model_dir=model_dir,
            speaker_encoder_dir=speaker_encoder_dir,
            runtime_lock_path=RUNTIME_LOCK,
            run_as_uid=1000,
            run_as_gid=1001,
            checked_head=CHECKED_HEAD,
            storage_namespace="storage-test",
            runtime_instance_id="d" * 32,
            runner=runner,
        )

    def test_command_runs_the_upstream_runtime_offline_and_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = _job(root)
            worker = self._worker(root)

            rendered = " ".join(worker.build_command(job))

            self.assertRegex(
                rendered,
                r"--name yap-meeting-transcription-[0-9a-f]{32}",
            )
            for expected in (
                "--network none",
                "--read-only",
                "--cap-drop ALL",
                "--security-opt no-new-privileges",
                "--user 1000:1001",
                "--pull never",
                "--memory 48g",
                "--memory-swap 48g",
                "--cpus 8",
                "nvidia.com/gpu=all",
                "HF_HUB_OFFLINE=1",
                "TRANSFORMERS_OFFLINE=1",
                "com.mcnatg1.yap.owner=batch-asr",
                "com.mcnatg1.yap.storage=storage-test",
                "com.mcnatg1.yap.runtime=" + "d" * 32,
                "com.mcnatg1.yap.job=meeting-1",
                "org.opencontainers.image.revision=" + CHECKED_HEAD,
                "dst=/models/tiron,readonly",
                "dst=/models/ecapa,readonly",
                "--runtime-lock /opt/yap-server/meeting-transcription-runtime.lock.json",
                "--model-dir /models/tiron",
                "--speaker-encoder-dir /models/ecapa",
                "--capture-manifest-sha256 " + "c" * 64,
                "--language en",
                "--application-revision " + CHECKED_HEAD,
            ):
                self.assertIn(expected, rendered)
            self.assertNotIn("--max-speakers", rendered)
            self.assertNotIn(str(job.result_path), rendered)

    def test_validates_and_atomically_publishes_one_source_bound_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = _job(root)

            def runner(
                *args: object, **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                del args, kwargs
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout=json.dumps(_result(job)) + "\n",
                    stderr="upstream diagnostics",
                )

            worker = self._worker(root, runner=runner)

            result = worker.run(job)

            self.assertEqual(result["jobId"], job.job_id)
            self.assertEqual(
                json.loads(job.result_path.read_text(encoding="utf-8")),
                result,
            )
            self.assertEqual(list(root.glob(".meeting-result.json.*.tmp")), [])

    def test_accepts_silence_snapped_window_count_at_container_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = _job(root, frames=58 * 16_000)
            payload = _result(job)
            payload["meeting"]["numDecodeWindows"] = 3  # type: ignore[index]

            def runner(
                *args: object, **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                del args, kwargs
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout=json.dumps(payload) + "\n",
                    stderr="",
                )

            worker = self._worker(root, runner=runner)

            result = worker.run(job)

            self.assertEqual(result["meeting"]["numDecodeWindows"], 3)  # type: ignore[index]

    def test_rejects_forged_runtime_or_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = _job(root)
            cases = {
                "runtime lock": ("model", "runtimeLockSha256", "0" * 64),
                "audio": ("audio", "sha256", "0" * 64),
                "source bounds": (
                    "meeting",
                    "turns",
                    [
                        {
                            "index": 0,
                            "sessionSpeakerId": "speaker-1",
                            "startSample": 0,
                            "endSample": 16_001,
                            "text": "hello there",
                        }
                    ],
                ),
            }
            for label, (section, field, value) in cases.items():
                with self.subTest(label):
                    payload = deepcopy(_result(job))
                    payload[section][field] = value  # type: ignore[index]

                    def runner(
                        *args: object,
                        **kwargs: object,
                    ) -> subprocess.CompletedProcess[str]:
                        del args, kwargs
                        return subprocess.CompletedProcess(
                            args=["docker"],
                            returncode=0,
                            stdout=json.dumps(payload),
                            stderr="",
                        )

                    worker = self._worker(root / label.replace(" ", "-"), runner=runner)
                    with self.assertRaises(WorkerExecutionError):
                        worker.run(job)
                    self.assertFalse(job.result_path.exists())

    def test_rejects_a_noncanonical_decode_window_capacity_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = _job(root)
            payload = _result(job)
            payload["meeting"]["speakerCapacityDegradation"] = {  # type: ignore[index]
                "code": "SPEAKER_CAPACITY_REACHED",
                "scope": "decode_window",
                "startSample": 1,
                "endSample": job.frame_count,
                "observedSpeakerCount": 8,
                "speakerLimit": 8,
            }

            def runner(
                *args: object, **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                del args, kwargs
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout=json.dumps(payload),
                    stderr="",
                )

            worker = self._worker(root / "forged-capacity", runner=runner)
            with self.assertRaises(WorkerExecutionError):
                worker.run(job)


if __name__ == "__main__":
    unittest.main()
