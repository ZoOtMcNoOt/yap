from __future__ import annotations

import unittest

from yap_server.pools.catalog_routing import BatchCatalogRouter


def _provider(
    *,
    provider_id: str,
    pool_id: str,
    model_revision: str,
    language: str,
    provider_language: str,
) -> dict[str, object]:
    return {
        "providerId": provider_id,
        "poolId": pool_id,
        "modelRevision": model_revision,
        "capabilities": [
            {
                "languageBcp47": language,
                "providerLanguageCode": provider_language,
                "mode": "fixedBatch",
            }
        ],
    }


class BatchCatalogRouterTests(unittest.TestCase):
    def test_resolves_provider_specific_prompt_without_losing_region(self) -> None:
        router = BatchCatalogRouter(
            {
                "providers": [
                    _provider(
                        provider_id="cohere",
                        pool_id="cohere-batch",
                        model_revision="a" * 40,
                        language="en-US",
                        provider_language="en",
                    ),
                    _provider(
                        provider_id="nemotron",
                        pool_id="nemotron-batch",
                        model_revision="b" * 40,
                        language="bg-BG",
                        provider_language="bg-BG",
                    ),
                ]
            }
        )

        english = router("en-US")
        bulgarian = router("bg-BG")

        self.assertEqual(router.supported_languages, ("bg-BG", "en-US"))
        self.assertEqual(english.provider_id, "cohere")
        self.assertEqual(english.provider_language, "en")
        self.assertEqual(bulgarian.provider_id, "nemotron")
        self.assertEqual(bulgarian.provider_language, "bg-BG")

    def test_rejects_hidden_overlap_and_unpromoted_locale(self) -> None:
        provider = _provider(
            provider_id="cohere",
            pool_id="cohere-batch",
            model_revision="a" * 40,
            language="en-US",
            provider_language="en",
        )
        overlap = _provider(
            provider_id="nemotron",
            pool_id="nemotron-batch",
            model_revision="b" * 40,
            language="en-US",
            provider_language="en-US",
        )
        with self.assertRaisesRegex(ValueError, "explicit routing preference"):
            BatchCatalogRouter({"providers": [provider, overlap]})

        router = BatchCatalogRouter({"providers": [provider]})
        with self.assertRaisesRegex(ValueError, "no promoted ASR"):
            router("fr-FR")

    def test_resolves_one_explicit_automatic_route(self) -> None:
        provider = _provider(
            provider_id="nemotron",
            pool_id="nemotron-batch",
            model_revision="b" * 40,
            language="und",
            provider_language="auto",
        )
        capability = provider["capabilities"][0]
        assert isinstance(capability, dict)
        capability["mode"] = "dynamicBatch"

        route = BatchCatalogRouter({"providers": [provider]})("und")

        self.assertEqual(route.execution_mode, "dynamicBatch")
        self.assertEqual(route.provider_language, "auto")


if __name__ == "__main__":
    unittest.main()
