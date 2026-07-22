from __future__ import annotations

import unittest
from pathlib import Path

from yap_server.evaluation.resident_provider_readiness import (
    wait_for_resident_provider_readiness,
)
from yap_server.pools.batch_contract import (
    ProviderServiceUnavailable,
    WorkerExecutionError,
)
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Worker:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    def verify_ready(self) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise ProviderServiceUnavailable("not ready")


def _lock() -> ModelPoolLock:
    return load_model_pool_lock(
        REPOSITORY_ROOT / "server" / "cohere-vllm-serving.lock.json"
    )


class ResidentProviderReadinessTests(unittest.TestCase):
    def test_retries_until_the_exact_locked_provider_is_ready(self) -> None:
        clock = _Clock()
        worker = _Worker(failures=2)

        readiness = wait_for_resident_provider_readiness(
            worker,
            _lock(),
            system_id="vllm-cohere-batch",
            timeout_seconds=2,
            poll_seconds=0.25,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        self.assertEqual(readiness.attempt_count, 3)
        self.assertEqual(readiness.ready_after_ms, 500)
        evidence = readiness.public_evidence()
        self.assertEqual(evidence["systemId"], "vllm-cohere-batch")
        self.assertEqual(
            evidence["readinessBoundary"],
            "probe-start-to-exact-model-ready",
        )
        self.assertTrue(evidence["passed"])
        self.assertNotIn("not ready", str(evidence))

    def test_fails_closed_when_readiness_never_arrives(self) -> None:
        clock = _Clock()

        with self.assertRaisesRegex(TimeoutError, "readiness timed out"):
            wait_for_resident_provider_readiness(
                _Worker(failures=100),
                _lock(),
                system_id="vllm-cohere-batch",
                timeout_seconds=0.5,
                poll_seconds=0.25,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
            )

    def test_fails_immediately_when_the_served_identity_is_wrong(self) -> None:
        class WrongIdentityWorker:
            def verify_ready(self) -> None:
                raise WorkerExecutionError("served model differs from lock")

        clock = _Clock()
        with self.assertRaisesRegex(WorkerExecutionError, "differs from lock"):
            wait_for_resident_provider_readiness(
                WrongIdentityWorker(),
                _lock(),
                system_id="vllm-cohere-batch",
                timeout_seconds=2,
                poll_seconds=0.25,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
            )

        self.assertEqual(clock.value, 0)

    def test_rejects_nonfinite_timing(self) -> None:
        with self.assertRaisesRegex(ValueError, "timing is invalid"):
            wait_for_resident_provider_readiness(
                _Worker(failures=0),
                _lock(),
                system_id="vllm-cohere-batch",
                timeout_seconds=float("nan"),
                poll_seconds=0.25,
            )


if __name__ == "__main__":
    unittest.main()
