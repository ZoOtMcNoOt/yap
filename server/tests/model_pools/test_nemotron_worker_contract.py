from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from yap_server.alignment_contract import (
    COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
    AlignmentUnavailableReason,
    unavailable_alignment,
)
from yap_server.language_span_contract import (
    ServerUtteranceLanguageObservation,
    build_server_language_span_evidence,
)
from yap_server.pools.batch_asr import ContainerBatchAsrWorker
from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    BatchAsrJob,
    WorkerExecutionError,
)
from yap_server.pools.batch_result import validate_result
from .batch_asr_fixtures import (
    AUDIO_SHA256,
    CHECKED_HEAD,
    IMAGE_ID,
    STORAGE_NAMESPACE,
    test_lock as _test_lock,
)


def _nemotron_lock():
    return replace(
        _test_lock(),
        pool_id="nemotron-batch",
        model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
        model_revision="d" * 40,
        model_license="OpenMDW-1.1",
        supported_languages=("auto", "en-US", "fr-FR"),
    )


def _dynamic_route() -> AsrRouteDecision:
    return AsrRouteDecision(
        provider_id="nemotron",
        pool_id="nemotron-batch",
        execution_mode="dynamicBatch",
        model_revision="d" * 40,
        provider_language="auto",
    )


def _dynamic_job() -> BatchAsrJob:
    return BatchAsrJob(
        job_id="job-1",
        input_path=Path("speech.wav"),
        result_path=Path("result.json"),
        language="und",
        input_sha256=AUDIO_SHA256,
        route=_dynamic_route(),
        utterance_plan_path=Path("utterance-plan.json"),
        utterance_plan_sha256="e" * 64,
    )


def _dynamic_result() -> dict[str, object]:
    lock = _nemotron_lock()
    segments: list[dict[str, object]] = [
        {
            "index": 0,
            "sourceSpanIndex": 0,
            "text": "hello",
            "status": "detected",
            "languageBcp47": "en-US",
            "rawLanguageTag": "en-US",
            "reason": None,
        },
        {
            "index": 1,
            "sourceSpanIndex": 0,
            "text": "bonjour",
            "status": "unknown",
            "languageBcp47": None,
            "rawLanguageTag": "el-GR",
            "reason": "DISABLED_LANGUAGE_TAG",
        },
    ]
    return {
        "schemaVersion": 1,
        "jobId": "job-1",
        "model": {
            "poolId": lock.pool_id,
            "id": lock.model_id,
            "revision": lock.model_revision,
        },
        "audio": {
            "sha256": AUDIO_SHA256,
            "durationMs": 1_000,
            "sampleRateHz": 16_000,
        },
        "transcript": {
            "text": "hello bonjour",
            "language": "auto",
            "punctuation": True,
            "languageSegments": segments,
            "languageSpanEvidence": build_server_language_span_evidence(
                source_end_sample=16_000,
                provider_id="nemotron",
                pool_id=lock.pool_id,
                model_id=lock.model_id,
                model_revision=lock.model_revision,
                utterance_plan_sha256="e" * 64,
                utterances=(
                    ServerUtteranceLanguageObservation(
                        start_sample=0,
                        end_sample=16_000,
                        language_segments=segments,
                    ),
                ),
            ),
        },
        "alignment": unavailable_alignment(
            AlignmentUnavailableReason.PROVIDER_UNSUPPORTED,
            component_revision=COHERE_ATTENTION_ALIGNMENT_CANDIDATE_REVISION,
        ),
        "runtime": {
            "device": "cuda",
            "pythonVersion": "3.12.9",
            "torchVersion": lock.runtime_torch_version,
            "torchCudaVersion": lock.runtime_torch_cuda_version,
            "overlayPackages": dict(lock.runtime_overlay_packages),
            "dtype": "bfloat16",
        },
    }


class NemotronWorkerContractTests(unittest.TestCase):
    def test_dynamic_route_uses_the_pool_specific_baked_lock(self) -> None:
        lock = replace(_nemotron_lock(), engine="nemo")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            model_dir.mkdir()
            input_path = root / "speech.wav"
            input_path.write_bytes(b"wav")
            utterance_plan_path = root / "utterance-plan.json"
            utterance_plan_path.write_bytes(b"{}\n")
            worker = ContainerBatchAsrWorker(
                image=IMAGE_ID,
                model_dir=model_dir,
                lock=lock,
                run_as_uid=1000,
                run_as_gid=1000,
                checked_head=CHECKED_HEAD,
                storage_namespace=STORAGE_NAMESPACE,
            )
            job = replace(
                _dynamic_job(),
                input_path=input_path,
                result_path=root / "result.json",
                utterance_plan_path=utterance_plan_path,
            )

            rendered = " ".join(worker.build_command(job))

            self.assertIn(
                "--lock /opt/yap-server/model-locks/nemotron-batch.json",
                rendered,
            )
            self.assertIn(
                "--tmpfs /tmp:rw,nosuid,nodev,noexec,size=4g",
                rendered,
            )
            self.assertIn("--language auto", rendered)
            self.assertIn(
                f"src={utterance_plan_path},dst=/input/utterance-plan.json,readonly",
                rendered,
            )
            self.assertIn(
                "--utterance-plan /input/utterance-plan.json "
                f"--utterance-plan-sha256 {'e' * 64}",
                rendered,
            )

    def test_dynamic_result_preserves_detected_and_unknown_language_evidence(self) -> None:
        validate_result(_dynamic_result(), _dynamic_job(), _nemotron_lock())

    def test_dynamic_result_rejects_primary_fallback_or_text_loss(self) -> None:
        payload = _dynamic_result()
        transcript = payload["transcript"]
        assert isinstance(transcript, dict)
        segments = transcript["languageSegments"]
        assert isinstance(segments, list)
        unknown = segments[1]
        assert isinstance(unknown, dict)
        unknown["languageBcp47"] = "en-US"

        with self.assertRaisesRegex(WorkerExecutionError, "language segments"):
            validate_result(payload, _dynamic_job(), _nemotron_lock())

    def test_dynamic_result_rejects_unbound_or_mismatched_source_evidence(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []

        unbound = _dynamic_result()
        unbound["transcript"]["languageSegments"][0]["sourceSpanIndex"] = 1  # type: ignore[index]
        cases.append(("unbound segment", unbound, "text and source"))

        wrong_plan = _dynamic_result()
        wrong_plan["transcript"]["languageSpanEvidence"][  # type: ignore[index]
            "utterancePlanSha256"
        ] = "f" * 64
        cases.append(("wrong plan", wrong_plan, "span evidence"))

        wrong_source = _dynamic_result()
        wrong_source["transcript"]["languageSpanEvidence"]["sourceEndSample"] = 8_000  # type: ignore[index]
        wrong_source["transcript"]["languageSpanEvidence"]["spans"][0][  # type: ignore[index]
            "endSample"
        ] = 8_000
        cases.append(("wrong source", wrong_source, "differs from the input"))

        mismatched_decision = _dynamic_result()
        mismatched_decision["transcript"]["languageSpanEvidence"]["spans"][0].update(  # type: ignore[index]
            {
                "languageBcp47": "en-US",
                "disposition": "serverDetected",
            }
        )
        cases.append(
            ("mismatched text decision", mismatched_decision, "text and source")
        )

        for label, payload, message in cases:
            with self.subTest(label):
                with self.assertRaisesRegex(WorkerExecutionError, message):
                    validate_result(deepcopy(payload), _dynamic_job(), _nemotron_lock())

        payload = _dynamic_result()
        transcript = payload["transcript"]
        assert isinstance(transcript, dict)
        transcript["text"] = "hello"
        with self.assertRaisesRegex(WorkerExecutionError, "language segments"):
            validate_result(payload, _dynamic_job(), _nemotron_lock())


if __name__ == "__main__":
    unittest.main()
