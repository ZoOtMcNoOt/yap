import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable, cast
import unittest

from yap_server.capabilities import (
    load_asr_capability_catalog,
    load_verified_asr_capability_catalog,
)
from yap_server.pools.model_lock import (
    ModelArtifactError,
    ModelPoolLock,
    load_model_pool_lock,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]


def _valid_capability_lock() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "providers": [
            {
                "providerId": "cohere",
                "poolId": "cohere-batch",
                "capabilities": [
                    {
                        "languageBcp47": "en-US",
                        "providerLanguageCode": "en",
                        "mode": "fixedBatch",
                        "qualityTier": "transcriptionReady",
                        "languageSuggestion": False,
                        "segmentLanguageTags": False,
                        "wordAlignment": False,
                        "promotionEvidenceRevision": "c" * 40,
                    }
                ],
            }
        ],
    }


def _load_catalog(
    payload: dict[str, object],
    model_lock: ModelPoolLock,
) -> dict[str, object]:
    return _load_catalogs(payload, (model_lock,))


def _load_catalogs(
    payload: dict[str, object],
    model_locks: Iterable[ModelPoolLock],
) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "asr-capabilities.lock.json"
        path.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
        return load_asr_capability_catalog(path, model_locks)


def _first_provider(payload: dict[str, object]) -> dict[str, Any]:
    providers = cast(list[Any], payload["providers"])
    return cast(dict[str, Any], providers[0])


def _first_capability(payload: dict[str, object]) -> dict[str, Any]:
    capabilities = cast(list[Any], _first_provider(payload)["capabilities"])
    return cast(dict[str, Any], capabilities[0])


class AsrCapabilityCatalogTests(unittest.TestCase):
    def test_repository_catalog_advertises_only_promoted_capabilities(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")

        catalog = load_asr_capability_catalog(
            SERVER_ROOT / "asr-capabilities.lock.json",
            (model_lock,),
        )

        self.assertEqual(
            catalog,
            json.loads(
                (
                    SERVER_ROOT / "openapi" / "examples" / "asr-capabilities.ok.json"
                ).read_text(encoding="utf-8")
            ),
        )

        self.assertEqual(
            _first_provider(catalog)["capabilities"],
            [
                {
                    "languageBcp47": "en-US",
                    "providerLanguageCode": "en",
                    "mode": "fixedBatch",
                    "qualityTier": "transcriptionReady",
                    "languageSuggestion": False,
                    "segmentLanguageTags": False,
                    "wordAlignment": False,
                    "promotionEvidenceRevision": (
                        "4771d9be60562fa009ccecbcd3c7111b699883a5"
                    ),
                }
            ],
        )

    def test_runtime_artifacts_are_verified_before_catalog_publication(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid_catalog = root / "invalid-capabilities.json"
            invalid_catalog.write_text("not json", encoding="utf-8")

            with self.assertRaisesRegex(
                ModelArtifactError,
                r"missing locked artifact",
            ):
                load_verified_asr_capability_catalog(
                    invalid_catalog,
                    ((model_lock, root),),
                )

    def test_valid_lock_joins_immutable_model_identity_and_fingerprints_catalog(
        self,
    ) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        providers = [
            {
                "providerId": "cohere",
                "poolId": "cohere-batch",
                "modelId": model_lock.model_id,
                "modelRevision": model_lock.model_revision,
                "modelLicense": model_lock.model_license,
                "modelSource": model_lock.model_source,
                "capabilities": capability_lock["providers"][0]["capabilities"],
            }
        ]
        revision_source = {"schemaVersion": 1, "providers": providers}
        expected = {
            "schemaVersion": 1,
            "catalogRevision": hashlib.sha256(
                json.dumps(
                    revision_source,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "providers": providers,
        }

        actual = _load_catalog(capability_lock, model_lock)

        self.assertEqual(actual, expected)

    def test_promotion_evidence_must_be_an_immutable_commit(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_capability(capability_lock)["promotionEvidenceRevision"] = "main"

        with self.assertRaisesRegex(
            ValueError,
            r"promotionEvidenceRevision must be a full immutable commit",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_preview_may_explicitly_have_no_promotion_evidence(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        capability = _first_capability(capability_lock)
        capability["qualityTier"] = "preview"
        capability["promotionEvidenceRevision"] = None

        catalog = _load_catalog(capability_lock, model_lock)

        self.assertIsNone(
            catalog["providers"][0]["capabilities"][0]["promotionEvidenceRevision"]
        )

    def test_transcription_ready_requires_promotion_evidence(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_capability(capability_lock)["promotionEvidenceRevision"] = None

        with self.assertRaisesRegex(
            ValueError,
            r"promotionEvidenceRevision must be a non-empty string",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_language_tag_must_be_canonical_bcp47(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_capability(capability_lock)["languageBcp47"] = "english_US"

        with self.assertRaisesRegex(
            ValueError,
            r"languageBcp47 must be a canonical BCP 47 tag",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_provider_language_must_exist_in_the_model_pool_lock(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_capability(capability_lock)["providerLanguageCode"] = "xx"

        with self.assertRaisesRegex(
            ValueError,
            r"providerLanguageCode is not supported by pool cohere-batch",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_execution_mode_must_be_supported_by_the_catalog_schema(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_capability(capability_lock)["mode"] = "magicRouter"

        with self.assertRaisesRegex(
            ValueError,
            r"mode is unsupported",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_quality_tier_must_be_supported_by_the_catalog_schema(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_capability(capability_lock)["qualityTier"] = "perfect"

        with self.assertRaisesRegex(
            ValueError,
            r"qualityTier is unsupported",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_locale_and_mode_pairs_must_be_unique(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        provider = _first_provider(capability_lock)
        capabilities = cast(list[dict[str, Any]], provider["capabilities"])
        capabilities.append(dict(capabilities[0]))

        with self.assertRaisesRegex(
            ValueError,
            r"capabilities must contain unique locale and mode pairs",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_dynamic_mode_requires_segment_language_evidence(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        capability = _first_capability(capability_lock)
        capability["mode"] = "dynamicBatch"
        capability["segmentLanguageTags"] = False

        with self.assertRaisesRegex(
            ValueError,
            r"dynamic modes require segmentLanguageTags",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_provider_identifier_is_bounded(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_provider(capability_lock)["providerId"] = "p" * 65

        with self.assertRaisesRegex(
            ValueError,
            r"providerId exceeds 64 characters",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_pool_identifier_is_bounded(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_provider(capability_lock)["poolId"] = "p" * 65

        with self.assertRaisesRegex(
            ValueError,
            r"poolId exceeds 64 characters",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_provider_count_is_bounded(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        provider = _first_provider(capability_lock)
        capability_lock["providers"] = [copy.deepcopy(provider) for _ in range(9)]

        with self.assertRaisesRegex(
            ValueError,
            r"providers exceeds 8 items",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_provider_and_pool_identities_must_be_unique(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        provider = _first_provider(capability_lock)
        capability_lock["providers"] = [provider, copy.deepcopy(provider)]

        with self.assertRaisesRegex(
            ValueError,
            r"providerId and poolId must be unique",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_catalog_cannot_advertise_an_unloaded_model_pool(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_provider(capability_lock)["poolId"] = "unverified-pool"

        with self.assertRaisesRegex(
            ValueError,
            r"poolId is not a loaded model pool",
        ):
            _load_catalog(capability_lock, model_lock)

    def test_loaded_model_pool_identities_must_be_unique(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")

        with self.assertRaisesRegex(
            ValueError,
            r"loaded model pool IDs must be unique",
        ):
            _load_catalogs(
                _valid_capability_lock(),
                (model_lock, replace(model_lock, model_id="replacement/model")),
            )

    def test_every_loaded_model_pool_must_be_represented(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        extra_lock = replace(
            model_lock,
            pool_id="unadvertised-pool",
            model_id="replacement/model",
        )

        with self.assertRaisesRegex(
            ValueError,
            r"catalog must represent every loaded model pool",
        ):
            _load_catalogs(
                _valid_capability_lock(),
                (model_lock, extra_lock),
            )

    def test_joined_model_metadata_is_bounded(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        model_lock = replace(model_lock, model_source="s" * 2049)

        with self.assertRaisesRegex(
            ValueError,
            r"modelSource exceeds 2048 characters",
        ):
            _load_catalog(_valid_capability_lock(), model_lock)

    def test_joined_model_revision_must_remain_immutable(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        model_lock = replace(model_lock, model_revision="main")

        with self.assertRaisesRegex(
            ValueError,
            r"modelRevision must be a full immutable commit",
        ):
            _load_catalog(_valid_capability_lock(), model_lock)

    def test_model_provenance_source_must_be_an_absolute_http_url(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        model_lock = replace(model_lock, model_source="relative/model-card")

        with self.assertRaisesRegex(
            ValueError,
            r"modelSource must be an absolute HTTP URL",
        ):
            _load_catalog(_valid_capability_lock(), model_lock)

    def test_identity_and_provenance_text_must_be_printable_ascii(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        model_lock = replace(model_lock, model_license="Apache\n2.0")

        with self.assertRaisesRegex(
            ValueError,
            r"modelLicense must contain printable ASCII",
        ):
            _load_catalog(_valid_capability_lock(), model_lock)

    def test_serialized_catalog_is_bounded_after_model_metadata_is_joined(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        source_prefix = "https://example.com/"
        providers: list[dict[str, object]] = []
        locks: list[ModelPoolLock] = []
        modes = ("fixedBatch", "dynamicBatch", "localLive", "serverLive")
        for provider_index in range(8):
            pool_id = f"pool-{provider_index}"
            capabilities: list[dict[str, object]] = []
            for capability_index in range(120):
                mode = modes[capability_index % len(modes)]
                capabilities.append(
                    {
                        "languageBcp47": f"en-{capability_index // 4:03d}",
                        "providerLanguageCode": "en",
                        "mode": mode,
                        "qualityTier": "transcriptionReady",
                        "languageSuggestion": False,
                        "segmentLanguageTags": mode == "dynamicBatch",
                        "wordAlignment": False,
                        "promotionEvidenceRevision": "c" * 40,
                    }
                )
            providers.append(
                {
                    "providerId": f"provider-{provider_index}",
                    "poolId": pool_id,
                    "capabilities": capabilities,
                }
            )
            locks.append(
                replace(
                    model_lock,
                    pool_id=pool_id,
                    model_id="m" * 256,
                    model_license="l" * 128,
                    model_source=source_prefix + ("s" * (2048 - len(source_prefix))),
                )
            )

        with self.assertRaisesRegex(
            ValueError,
            r"serialized ASR capability catalog exceeds 262144 bytes",
        ):
            _load_catalogs(
                {"schemaVersion": 1, "providers": providers},
                locks,
            )

    def test_lock_rejects_fields_outside_the_versioned_schema(self) -> None:
        model_lock = load_model_pool_lock(SERVER_ROOT / "model-pools.lock.json")
        capability_lock = _valid_capability_lock()
        _first_provider(capability_lock)["displayName"] = "mutable marketing text"

        with self.assertRaisesRegex(
            ValueError,
            r"providers\[0\] contains unsupported fields: displayName",
        ):
            _load_catalog(capability_lock, model_lock)
