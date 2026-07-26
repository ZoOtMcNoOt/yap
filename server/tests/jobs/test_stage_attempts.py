from __future__ import annotations

from copy import deepcopy
import unittest

from yap_server.jobs.stage_attempts import (
    finish_stage,
    latest_stage_projection,
    start_stage,
    validate_stage_attempts,
)


class StageAttemptContractTests(unittest.TestCase):
    def test_attempts_are_append_only_contiguous_and_project_latest_state(self) -> None:
        attempts: list[dict[str, object]] = []
        first = start_stage(
            attempts,
            stage="asr",
            input_fingerprint_sha256="a" * 64,
            component_id="cohere-batch",
            component_revision="b" * 40,
            started_at_utc="2026-07-16T12:00:00Z",
        )
        finish_stage(
            attempts,
            stage="asr",
            attempt=first,
            state="failed",
            completed_at_utc="2026-07-16T12:00:01Z",
            retryable=True,
            reason="ASR_WORKER_FAILED",
            evidence={"workerExit": "bounded_failure"},
        )
        second = start_stage(
            attempts,
            stage="asr",
            input_fingerprint_sha256="a" * 64,
            component_id="cohere-batch",
            component_revision="b" * 40,
            started_at_utc="2026-07-16T12:00:02Z",
        )

        self.assertEqual((first, second), (1, 2))
        self.assertEqual(validate_stage_attempts(attempts), attempts)
        self.assertEqual(
            latest_stage_projection(attempts),
            [
                {
                    "stage": "asr",
                    "attempt": 2,
                    "state": "running",
                    "updatedAtUtc": "2026-07-16T12:00:02Z",
                    "retryable": None,
                    "reason": None,
                }
            ],
        )

    def test_tampered_evidence_and_overlapping_attempts_fail_closed(self) -> None:
        attempts: list[dict[str, object]] = []
        attempt = start_stage(
            attempts,
            stage="alignment",
            input_fingerprint_sha256="c" * 64,
            component_id="alignment-gate",
            component_revision="alignment-unavailable-test-v1",
            started_at_utc="2026-07-16T12:01:00Z",
        )
        with self.assertRaisesRegex(ValueError, "already has a running"):
            start_stage(
                attempts,
                stage="alignment",
                input_fingerprint_sha256="c" * 64,
                component_id="alignment-gate",
                component_revision="alignment-unavailable-test-v1",
                started_at_utc="2026-07-16T12:01:01Z",
            )
        finish_stage(
            attempts,
            stage="alignment",
            attempt=attempt,
            state="unavailable",
            completed_at_utc="2026-07-16T12:01:02Z",
            retryable=False,
            reason="ALIGNMENT_UNAVAILABLE",
            evidence={"language": "en-US"},
        )
        attempts[0]["evidence"] = {"language": "fr-FR"}
        with self.assertRaisesRegex(ValueError, "evidence identity"):
            validate_stage_attempts(attempts)

    def test_terminal_retryability_and_reason_codes_match_the_wire_projection(self) -> None:
        attempts: list[dict[str, object]] = []
        attempt = start_stage(
            attempts,
            stage="asr",
            input_fingerprint_sha256="a" * 64,
            component_id="cohere-batch",
            component_revision="b" * 40,
            started_at_utc="2026-07-16T12:02:00Z",
        )
        finish_stage(
            attempts,
            stage="asr",
            attempt=attempt,
            state="failed",
            completed_at_utc="2026-07-16T12:02:01Z",
            retryable=True,
            reason="ASR_WORKER_FAILED",
        )

        injected_reason = deepcopy(attempts)
        injected_reason[0]["reason"] = "asr-worker-failed\nforged"
        with self.assertRaisesRegex(ValueError, "reason"):
            validate_stage_attempts(injected_reason)

        invalid_success = deepcopy(attempts)
        invalid_success[0]["state"] = "succeeded"
        with self.assertRaisesRegex(ValueError, "succeeded stage metadata"):
            validate_stage_attempts(invalid_success)


if __name__ == "__main__":
    unittest.main()
