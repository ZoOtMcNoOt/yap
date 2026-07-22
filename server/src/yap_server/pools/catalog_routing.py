from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from yap_server.language_tags import canonical_bcp47
from yap_server.pools.batch_contract import AsrRouteDecision


class BatchCatalogRouter:
    """Resolve one immutable batch route from a verified catalog.

    Overlapping providers are rejected until the client supplies an explicit
    provider preference. Catalog order must never become an invisible routing
    policy.
    """

    def __init__(self, catalog: Mapping[str, object]) -> None:
        providers = catalog.get("providers")
        if (
            not isinstance(providers, Sequence)
            or isinstance(providers, (str, bytes, bytearray))
            or not providers
            or len(providers) > 8
        ):
            raise ValueError("verified ASR catalog providers are invalid")

        routes: dict[str, AsrRouteDecision] = {}
        for provider in providers:
            if not isinstance(provider, Mapping):
                raise ValueError("verified ASR catalog provider is invalid")
            provider_id = _text(provider.get("providerId"), "providerId")
            pool_id = _text(provider.get("poolId"), "poolId")
            model_revision = _text(
                provider.get("modelRevision"),
                "modelRevision",
            )
            capabilities = provider.get("capabilities")
            if (
                not isinstance(capabilities, Sequence)
                or isinstance(capabilities, (str, bytes, bytearray))
                or not capabilities
                or len(capabilities) > 256
            ):
                raise ValueError("verified ASR provider capabilities are invalid")
            for capability in capabilities:
                if not isinstance(capability, Mapping):
                    raise ValueError("verified ASR capability is invalid")
                mode = capability.get("mode")
                if mode not in {"fixedBatch", "dynamicBatch"}:
                    continue
                language = canonical_bcp47(
                    capability.get("languageBcp47"),
                    "capability languageBcp47",
                )
                provider_language_value = capability.get("providerLanguageCode")
                if mode == "dynamicBatch":
                    if provider_language_value != "auto":
                        raise ValueError("dynamic ASR capability must use automatic prompting")
                    provider_language = "auto"
                else:
                    provider_language = canonical_bcp47(
                        provider_language_value,
                        "capability providerLanguageCode",
                    )
                route = AsrRouteDecision(
                    provider_id=provider_id,
                    pool_id=pool_id,
                    execution_mode=mode,
                    model_revision=model_revision,
                    provider_language=provider_language,
                )
                if language in routes:
                    raise ValueError(
                        "batch ASR language has multiple providers without an "
                        "explicit routing preference"
                    )
                routes[language] = route
        if not routes:
            raise ValueError("verified ASR catalog has no batch routes")
        self._routes = MappingProxyType(routes)

    @property
    def supported_languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))

    def __call__(self, language_bcp47: str) -> AsrRouteDecision:
        language = canonical_bcp47(language_bcp47, "batch language")
        try:
            return self._routes[language]
        except KeyError as error:
            raise ValueError("batch language has no promoted ASR route") from error


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"verified ASR catalog {field} is invalid")
    return value
