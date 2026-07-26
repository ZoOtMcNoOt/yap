from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import threading
import unittest

from yap_server.pools.batch_asr import (
    AsrRouteDecision,
    BatchAsrJob,
    BatchAsrPool,
    DurableAsrRouting,
    ProviderBatchWorkerRegistry,
    WorkerExecutionError,
)

from .batch_asr_fixtures import AUDIO_SHA256


MODEL_REVISION = "a" * 40
CATALOG_REVISION = "c" * 64


def _route(
    provider_id: str,
    *,
    pool_id: str | None = None,
    execution_mode: str = "fixedBatch",
    provider_language: str = "en",
) -> AsrRouteDecision:
    return AsrRouteDecision(
        provider_id=provider_id,
        pool_id=pool_id or f"{provider_id}-batch",
        execution_mode=execution_mode,
        model_revision=MODEL_REVISION,
        provider_language=provider_language,
    )


def _job(job_id: str, route: AsrRouteDecision) -> BatchAsrJob:
    dynamic = route.execution_mode == "dynamicBatch"
    return BatchAsrJob(
        job_id=job_id,
        input_path=Path(f"{job_id}.wav"),
        result_path=Path(f"{job_id}.json"),
        language="und" if dynamic else "en",
        input_sha256=AUDIO_SHA256,
        route=route,
        utterance_plan_path=(Path(f"{job_id}-utterance-plan.json") if dynamic else None),
        utterance_plan_sha256=("d" * 64 if dynamic else None),
    )


class _ConcurrencyProbe:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0


class _ProviderWorker:
    def __init__(self, provider_id: str, probe: _ConcurrencyProbe) -> None:
        self.provider_id = provider_id
        self.probe = probe
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.jobs: list[BatchAsrJob] = []

    def run(
        self,
        job: BatchAsrJob,
        _cancellation: threading.Event,
    ) -> dict[str, object]:
        with self.probe.lock:
            self.probe.active += 1
            self.probe.maximum = max(self.probe.maximum, self.probe.active)
        self.jobs.append(job)
        self.started.set()
        try:
            if not self.release.wait(timeout=2):
                raise TimeoutError(f"{self.provider_id} worker was not released")
            return {
                "schemaVersion": 1,
                "jobId": job.job_id,
                "providerId": self.provider_id,
            }
        finally:
            with self.probe.lock:
                self.probe.active -= 1

    def close(self) -> None:
        self.closed.set()
        self.release.set()


class AsrRouteDecisionTests(unittest.TestCase):
    def test_route_is_immutable_and_bounds_all_provider_metadata(self) -> None:
        route = _route(
            "nemotron",
            execution_mode="dynamicBatch",
            provider_language="auto",
        )

        self.assertEqual(route.provider_id, "nemotron")
        self.assertEqual(route.pool_id, "nemotron-batch")
        self.assertEqual(route.execution_mode, "dynamicBatch")
        self.assertEqual(route.model_revision, MODEL_REVISION)
        self.assertEqual(route.provider_language, "auto")
        with self.assertRaises(FrozenInstanceError):
            route.provider_id = "cohere"  # type: ignore[misc]

        invalid_overrides = (
            {"provider_id": ""},
            {"provider_id": "a" * 65},
            {"provider_id": "cohere\n"},
            {"pool_id": ""},
            {"pool_id": "a" * 65},
            {"execution_mode": "serverLive"},
            {"model_revision": "not-a-revision"},
            {"provider_language": "EN"},
            {"provider_language": "../en"},
            {"provider_language": "a" * 33},
        )
        baseline = {
            "provider_id": "cohere",
            "pool_id": "cohere-batch",
            "execution_mode": "fixedBatch",
            "model_revision": MODEL_REVISION,
            "provider_language": "en",
        }
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    AsrRouteDecision(**(baseline | overrides))

    def test_route_and_catalog_revision_round_trip_through_private_state(self) -> None:
        routing = DurableAsrRouting(
            route=_route("cohere"),
            asr_catalog_revision=CATALOG_REVISION,
        )

        persisted = routing.to_persisted()

        self.assertEqual(DurableAsrRouting.from_persisted(persisted), routing)
        self.assertEqual(persisted["route"], routing.route.to_persisted())
        with self.assertRaises(ValueError):
            DurableAsrRouting.from_persisted(
                {"asrCatalogRevision": CATALOG_REVISION}
            )

    def test_fixed_job_language_must_match_its_provider_route(self) -> None:
        with self.assertRaisesRegex(ValueError, "route language"):
            BatchAsrJob(
                job_id="job-mismatch",
                input_path=Path("mismatch.wav"),
                result_path=Path("mismatch.json"),
                language="en",
                input_sha256=AUDIO_SHA256,
                route=_route("cohere", provider_language="fr"),
            )

    def test_dynamic_job_requires_und_and_a_hash_bound_utterance_plan(self) -> None:
        route = _route(
            "nemotron",
            execution_mode="dynamicBatch",
            provider_language="auto",
        )
        for language, plan_path, plan_sha256 in (
            ("en-US", Path("plan.json"), "d" * 64),
            ("und", None, None),
            ("und", Path("plan.json"), None),
        ):
            with self.subTest(language=language, plan_path=plan_path):
                with self.assertRaises(ValueError):
                    BatchAsrJob(
                        job_id="job-dynamic",
                        input_path=Path("dynamic.wav"),
                        result_path=Path("dynamic.json"),
                        language=language,
                        input_sha256=AUDIO_SHA256,
                        route=route,
                        utterance_plan_path=plan_path,
                        utterance_plan_sha256=plan_sha256,
                    )


class ProviderBatchWorkerRegistryTests(unittest.TestCase):
    def test_two_provider_routes_share_one_physical_admission_bound(self) -> None:
        probe = _ConcurrencyProbe()
        cohere = _ProviderWorker("cohere", probe)
        nemotron = _ProviderWorker("nemotron", probe)
        registry = ProviderBatchWorkerRegistry(
            {"cohere": cohere, "nemotron": nemotron}
        )
        pool = BatchAsrPool(
            registry,
            route_resolver=lambda provider_language: _route(
                "cohere",
                provider_language=provider_language,
            ),
            asr_catalog_revision=CATALOG_REVISION,
            max_workers=1,
            max_queued=1,
        )
        try:
            first = pool.submit(_job("job-cohere", _route("cohere")))
            self.assertTrue(cohere.started.wait(timeout=2))

            second = pool.submit(
                _job(
                    "job-nemotron",
                    _route(
                        "nemotron",
                        execution_mode="dynamicBatch",
                        provider_language="auto",
                    ),
                )
            )
            self.assertFalse(nemotron.started.wait(timeout=0.05))
            self.assertEqual(probe.maximum, 1)

            cohere.release.set()
            self.assertEqual(first.result(timeout=2)["providerId"], "cohere")
            self.assertTrue(nemotron.started.wait(timeout=2))
            self.assertEqual(probe.maximum, 1)
            nemotron.release.set()
            self.assertEqual(second.result(timeout=2)["providerId"], "nemotron")
            self.assertEqual(cohere.jobs[0].route.provider_id, "cohere")
            self.assertEqual(nemotron.jobs[0].route.provider_id, "nemotron")
        finally:
            cohere.release.set()
            nemotron.release.set()
            pool.shutdown()

        self.assertTrue(cohere.closed.is_set())
        self.assertTrue(nemotron.closed.is_set())

    def test_registry_rejects_unknown_provider_jobs(self) -> None:
        worker = _ProviderWorker("cohere", _ConcurrencyProbe())
        registry = ProviderBatchWorkerRegistry({"cohere": worker})
        cancellation = threading.Event()
        try:
            with self.assertRaisesRegex(WorkerExecutionError, "registered"):
                registry.run(
                    _job("job-unknown", _route("unknown")),
                    cancellation,
                )
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
