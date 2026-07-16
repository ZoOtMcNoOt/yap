from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from yap_server.bounded_file import read_regular_text
from yap_server.pools.model_lock import ModelPoolLock, verify_model_artifacts


_MAX_CAPABILITY_LOCK_BYTES = 256 * 1024
_MAX_SERIALIZED_CATALOG_BYTES = 256 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_BCP47 = re.compile(
    r"^[a-z]{2,3}"
    r"(?:-[A-Z][a-z]{3})?"
    r"(?:-(?:[A-Z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*$"
)
_EXECUTION_MODES = frozenset(
    {"dynamicBatch", "fixedBatch", "localLive", "serverLive"}
)
_QUALITY_TIERS = frozenset({"broadCoverage", "preview", "transcriptionReady"})


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _exact_fields(value: dict[str, Any], field: str, allowed: set[str]) -> None:
    unsupported = sorted(set(value) - allowed)
    if unsupported:
        raise ValueError(
            f"{field} contains unsupported fields: {', '.join(unsupported)}"
        )


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _bounded_string(value: Any, field: str, maximum: int) -> str:
    text = _string(value, field)
    if len(text) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return text


def _bounded_ascii_string(value: Any, field: str, maximum: int) -> str:
    text = _bounded_string(value, field, maximum)
    if any(character < " " or character > "~" for character in text):
        raise ValueError(f"{field} must contain printable ASCII")
    return text


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _revision(value: Any, field: str) -> str:
    revision = _string(value, field)
    if _REVISION.fullmatch(revision) is None:
        raise ValueError(f"{field} must be a full immutable commit")
    return revision


def _http_url(value: Any, field: str) -> str:
    source = _bounded_ascii_string(value, field, 2048)
    try:
        parsed = urlsplit(source)
        hostname = parsed.hostname
    except ValueError:
        hostname = None
        parsed = None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field} must be an absolute HTTP URL")
    return source


def _bcp47(value: Any, field: str) -> str:
    language = _string(value, field)
    if len(language) > 35 or _BCP47.fullmatch(language) is None:
        raise ValueError(f"{field} must be a canonical BCP 47 tag")
    return language


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return value


def _bounded_array(value: Any, field: str, maximum: int) -> list[Any]:
    items = _array(value, field)
    if len(items) > maximum:
        raise ValueError(f"{field} exceeds {maximum} items")
    return items


def load_asr_capability_catalog(
    path: Path,
    model_locks: Iterable[ModelPoolLock],
) -> dict[str, object]:
    """Load one bounded catalog and join it to immutable model-pool identity."""

    payload = _mapping(
        json.loads(read_regular_text(path, _MAX_CAPABILITY_LOCK_BYTES)),
        "root",
    )
    _exact_fields(payload, "root", {"schemaVersion", "providers"})
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported ASR capability lock schema")

    loaded_locks = tuple(model_locks)
    locks_by_pool = {lock.pool_id: lock for lock in loaded_locks}
    if len(locks_by_pool) != len(loaded_locks):
        raise ValueError("loaded model pool IDs must be unique")
    providers: list[dict[str, object]] = []
    seen_provider_ids: set[str] = set()
    seen_pool_ids: set[str] = set()
    for provider_index, raw_provider in enumerate(
        _bounded_array(payload.get("providers"), "providers", 8)
    ):
        field = f"providers[{provider_index}]"
        provider = _mapping(raw_provider, field)
        _exact_fields(
            provider,
            field,
            {
                "capabilities",
                "poolId",
                "providerId",
            },
        )
        provider_id = _bounded_ascii_string(
            provider.get("providerId"),
            f"{field}.providerId",
            64,
        )
        pool_id = _bounded_ascii_string(
            provider.get("poolId"),
            f"{field}.poolId",
            64,
        )
        if provider_id in seen_provider_ids or pool_id in seen_pool_ids:
            raise ValueError("providers providerId and poolId must be unique")
        seen_provider_ids.add(provider_id)
        seen_pool_ids.add(pool_id)
        try:
            model_lock = locks_by_pool[pool_id]
        except KeyError as error:
            raise ValueError(f"{field}.poolId is not a loaded model pool") from error
        model_id = _bounded_ascii_string(
            model_lock.model_id,
            f"{field}.modelId",
            256,
        )
        model_license = _bounded_ascii_string(
            model_lock.model_license,
            f"{field}.modelLicense",
            128,
        )
        model_source = _http_url(
            model_lock.model_source,
            f"{field}.modelSource",
        )
        model_revision = _revision(
            model_lock.model_revision,
            f"{field}.modelRevision",
        )

        capabilities: list[dict[str, object]] = []
        seen_locale_modes: set[tuple[str, str]] = set()
        for capability_index, raw_capability in enumerate(
            _bounded_array(
                provider.get("capabilities"),
                f"{field}.capabilities",
                256,
            )
        ):
            capability_field = f"{field}.capabilities[{capability_index}]"
            capability = _mapping(raw_capability, capability_field)
            _exact_fields(
                capability,
                capability_field,
                {
                    "languageBcp47",
                    "languageSuggestion",
                    "mode",
                    "promotionEvidenceRevision",
                    "providerLanguageCode",
                    "qualityTier",
                    "segmentLanguageTags",
                    "wordAlignment",
                },
            )
            mode = _string(
                capability.get("mode"),
                f"{capability_field}.mode",
            )
            if mode not in _EXECUTION_MODES:
                raise ValueError(f"{capability_field}.mode is unsupported")
            provider_language_code = _string(
                capability.get("providerLanguageCode"),
                f"{capability_field}.providerLanguageCode",
            )
            if provider_language_code not in model_lock.supported_languages:
                raise ValueError(
                    f"{capability_field}.providerLanguageCode is not supported "
                    f"by pool {pool_id}"
                )
            language_bcp47 = _bcp47(
                capability.get("languageBcp47"),
                f"{capability_field}.languageBcp47",
            )
            locale_mode = (language_bcp47, mode)
            if locale_mode in seen_locale_modes:
                raise ValueError(
                    f"{field}.capabilities must contain unique locale and mode pairs"
                )
            seen_locale_modes.add(locale_mode)
            quality_tier = _string(
                capability.get("qualityTier"),
                f"{capability_field}.qualityTier",
            )
            if quality_tier not in _QUALITY_TIERS:
                raise ValueError(f"{capability_field}.qualityTier is unsupported")
            segment_language_tags = _boolean(
                capability.get("segmentLanguageTags"),
                f"{capability_field}.segmentLanguageTags",
            )
            if mode == "dynamicBatch" and not segment_language_tags:
                raise ValueError(
                    f"{capability_field} dynamic modes require segmentLanguageTags"
                )
            capabilities.append(
                {
                    "languageBcp47": language_bcp47,
                    "providerLanguageCode": provider_language_code,
                    "mode": mode,
                    "qualityTier": quality_tier,
                    "languageSuggestion": _boolean(
                        capability.get("languageSuggestion"),
                        f"{capability_field}.languageSuggestion",
                    ),
                    "segmentLanguageTags": segment_language_tags,
                    "wordAlignment": _boolean(
                        capability.get("wordAlignment"),
                        f"{capability_field}.wordAlignment",
                    ),
                    "promotionEvidenceRevision": _revision(
                        capability.get("promotionEvidenceRevision"),
                        f"{capability_field}.promotionEvidenceRevision",
                    ),
                }
            )

        providers.append(
            {
                "providerId": provider_id,
                "poolId": pool_id,
                "modelId": model_id,
                "modelRevision": model_revision,
                "modelLicense": model_license,
                "modelSource": model_source,
                "capabilities": capabilities,
            }
        )

    if seen_pool_ids != set(locks_by_pool):
        raise ValueError("catalog must represent every loaded model pool")

    revision_source = {"schemaVersion": 1, "providers": providers}
    catalog_revision = hashlib.sha256(
        json.dumps(
            revision_source,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    catalog = {
        "schemaVersion": 1,
        "catalogRevision": catalog_revision,
        "providers": providers,
    }
    if (
        len(
            json.dumps(
                catalog,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        > _MAX_SERIALIZED_CATALOG_BYTES
    ):
        raise ValueError(
            "serialized ASR capability catalog exceeds "
            f"{_MAX_SERIALIZED_CATALOG_BYTES} bytes"
        )
    return catalog


def load_verified_asr_capability_catalog(
    path: Path,
    model_artifacts: Iterable[tuple[ModelPoolLock, Path]],
) -> dict[str, object]:
    """Publish capabilities only after their locked model artifacts verify."""

    verified_locks: list[ModelPoolLock] = []
    for model_lock, model_dir in model_artifacts:
        verify_model_artifacts(model_lock, model_dir)
        verified_locks.append(model_lock)
    return load_asr_capability_catalog(path, verified_locks)
