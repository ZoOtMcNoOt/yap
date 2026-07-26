from __future__ import annotations

from yap_server.pools.batch_contract import AsrRouteDecision


TEST_MODEL_REVISION = "b" * 40
TEST_ASR_CATALOG_REVISION = "c" * 64


def test_asr_route(provider_language: str = "en") -> AsrRouteDecision:
    provider_language = provider_language.split("-", 1)[0].lower()
    return AsrRouteDecision(
        provider_id="cohere",
        pool_id="cohere-batch",
        execution_mode="fixedBatch",
        model_revision=TEST_MODEL_REVISION,
        provider_language=provider_language,
    )


test_asr_route.__test__ = False
