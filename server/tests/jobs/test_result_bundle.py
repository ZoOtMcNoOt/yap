from __future__ import annotations

from types import SimpleNamespace
import unittest

from yap_server.jobs.result_bundle import (
    ResultBundleAdapterRegistry,
    ResultRevisionBundle,
)
from yap_server.pools.batch_contract import AsrRouteDecision


def _route(pool_id: str) -> AsrRouteDecision:
    return AsrRouteDecision(
        provider_id="provider-a",
        pool_id=pool_id,
        execution_mode="fixedBatch",
        model_revision="a" * 40,
        provider_language="en",
    )


class ResultBundleTests(unittest.TestCase):
    def test_registry_binds_each_adapter_to_its_declared_pool(self) -> None:
        adapter = SimpleNamespace(
            pool_id="pool-a",
            requires_speaker_result=True,
            build_result_bundle=lambda *_args, **_kwargs: None,
            validate_persisted_result_bundle=lambda *_args, **_kwargs: None,
        )
        registry = ResultBundleAdapterRegistry(
            {"pool-a": adapter},  # type: ignore[dict-item]
        )

        self.assertIs(registry.for_route(_route("pool-a")), adapter)
        self.assertIsNone(registry.for_route(_route("pool-b")))
        with self.assertRaisesRegex(ValueError, "wrong pool"):
            ResultBundleAdapterRegistry(
                {"pool-b": adapter},  # type: ignore[dict-item]
            )

    def test_bundle_requires_its_declared_speaker_companion(self) -> None:
        transcript_result = {
            "createdAtUtc": "2026-08-03T03:00:00Z",
            "speakerResultSha256": "a" * 64,
        }
        with self.assertRaisesRegex(ValueError, "speaker companion"):
            ResultRevisionBundle(
                transcript_result=transcript_result,
                speaker_result=None,
                created_at_utc="2026-08-03T03:00:00Z",
                worker_output_sha256="b" * 64,
                result_shape="joint_speaker_transcript_v1",
            )

    def test_bundle_must_match_the_frozen_route_companion_policy(self) -> None:
        bundle = ResultRevisionBundle(
            transcript_result={"createdAtUtc": "2026-08-03T03:00:00Z"},
            speaker_result=None,
            created_at_utc="2026-08-03T03:00:00Z",
            worker_output_sha256="b" * 64,
            result_shape="raw_transcript_v1",
        )

        bundle.validate_companion_policy(False)
        with self.assertRaisesRegex(ValueError, "frozen route policy"):
            bundle.validate_companion_policy(True)


if __name__ == "__main__":
    unittest.main()
