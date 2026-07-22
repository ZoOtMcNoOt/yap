from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Mapping

from yap_server.bounded_file import read_regular_text
from yap_server.evaluation.fleurs_corpus import FleursReleaseLock
from yap_server.language_tags import canonical_bcp47
from yap_server.pools.model_lock import ModelPoolLock


_MAX_PLAN_BYTES = 128 * 1024
_MAX_CASES = 100_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


@dataclass(frozen=True, slots=True)
class FleursComparatorSelection:
    identifier: str
    case_count: int
    selection: str


@dataclass(frozen=True, slots=True)
class FleursCohereComparatorPlan:
    source_release_lock_sha256: str
    dataset_id: str
    dataset_revision: str
    dataset_config: str
    split: str
    evaluation_locale_bcp47: str
    model_lock_sha256: str
    pool_id: str
    model_id: str
    model_revision: str
    provider_language: str
    punctuation: bool
    promotion_eligible: bool
    exposure_status: str
    batch_size: int
    warmup_cases: int
    selections: tuple[FleursComparatorSelection, ...]
    scoring_profile: str


def load_fleurs_cohere_comparator_plan(path: Path) -> FleursCohereComparatorPlan:
    try:
        payload = json.loads(read_regular_text(path, _MAX_PLAN_BYTES))
    except json.JSONDecodeError as error:
        raise ValueError("FLEURS Cohere comparator plan is not valid JSON") from error
    root = _object(
        payload,
        {
            "schemaVersion",
            "purpose",
            "promotionEligible",
            "exposureStatus",
            "source",
            "candidate",
            "route",
            "execution",
            "scoring",
            "privacy",
        },
        "FLEURS Cohere comparator plan",
    )
    if (
        root["schemaVersion"] != 1
        or root["purpose"] != "locked-public-comparator"
        or root["promotionEligible"] is not False
        or root["exposureStatus"] != "unknown"
    ):
        raise ValueError("FLEURS Cohere comparator purpose is invalid")

    source = _object(
        root["source"],
        {
            "releaseLockSha256",
            "datasetId",
            "datasetRevision",
            "datasetConfig",
            "split",
            "evaluationLocaleBcp47",
        },
        "FLEURS comparator source",
    )
    dataset_id = _text(source["datasetId"], "FLEURS dataset ID", 256)
    if dataset_id != "google/fleurs":
        raise ValueError("FLEURS comparator dataset is unsupported")
    dataset_revision = _fullmatch(
        source["datasetRevision"],
        _REVISION,
        "FLEURS dataset revision",
    )
    dataset_config = _text(source["datasetConfig"], "FLEURS dataset config", 32)
    split = _text(source["split"], "FLEURS split", 32)
    evaluation_locale = canonical_bcp47(
        source["evaluationLocaleBcp47"],
        "FLEURS evaluation locale",
    )

    candidate = _object(
        root["candidate"],
        {"modelLockSha256", "poolId", "modelId", "modelRevision"},
        "FLEURS comparator candidate",
    )
    pool_id = _text(candidate["poolId"], "Cohere pool ID", 128)
    if pool_id != "cohere-batch":
        raise ValueError("FLEURS comparator candidate must use the Cohere pool")
    model_id = _text(candidate["modelId"], "Cohere model ID", 256)
    model_revision = _fullmatch(
        candidate["modelRevision"],
        _REVISION,
        "Cohere model revision",
    )

    route = _object(
        root["route"],
        {"providerLanguage", "punctuation"},
        "FLEURS comparator route",
    )
    provider_language = canonical_bcp47(
        route["providerLanguage"],
        "Cohere provider language",
    )
    if not isinstance(route["punctuation"], bool):
        raise ValueError("FLEURS comparator punctuation flag is invalid")

    execution = _object(
        root["execution"],
        {"batchSize", "warmupCases", "selections"},
        "FLEURS comparator execution",
    )
    batch_size = _bounded_positive_int(
        execution["batchSize"],
        "FLEURS comparator batch size",
        maximum=8,
    )
    warmup_cases = _bounded_positive_int(
        execution["warmupCases"],
        "FLEURS comparator warmup count",
        maximum=8,
    )
    selections: list[FleursComparatorSelection] = []
    for value in _array(execution["selections"], "FLEURS comparator selections"):
        selection = _object(
            value,
            {"id", "caseCount", "selection"},
            "FLEURS comparator selection",
        )
        selections.append(
            FleursComparatorSelection(
                identifier=_identifier(selection["id"], "selection ID"),
                case_count=_bounded_positive_int(
                    selection["caseCount"],
                    "selection case count",
                    maximum=_MAX_CASES,
                ),
                selection=_text(
                    selection["selection"],
                    "selection rule",
                    64,
                ),
            )
        )
    if (
        [(item.identifier, item.selection) for item in selections]
        != [
            ("screen", "metadata-prefix-v1"),
            ("full", "all-cases-v1"),
        ]
        or selections[0].case_count > selections[1].case_count
    ):
        raise ValueError("FLEURS comparator selections differ from the contract")

    scoring = _object(
        root["scoring"],
        {"profile", "qualityDecision", "promotionThresholds"},
        "FLEURS comparator scoring",
    )
    if (
        scoring["profile"] != "word-primary-v1"
        or scoring["qualityDecision"] != "descriptive-baseline-only"
        or scoring["promotionThresholds"] is not None
    ):
        raise ValueError("FLEURS comparator scoring policy is invalid")
    privacy = _object(
        root["privacy"],
        {
            "cacheEnvironment",
            "repositoryFallback",
            "terminalOutput",
            "caseEvidence",
        },
        "FLEURS comparator privacy policy",
    )
    if privacy != {
        "cacheEnvironment": "YAP_EVAL_CACHE",
        "repositoryFallback": False,
        "terminalOutput": "aggregate-only",
        "caseEvidence": "private-only",
    }:
        raise ValueError("FLEURS comparator privacy policy is invalid")

    return FleursCohereComparatorPlan(
        source_release_lock_sha256=_sha256(
            source["releaseLockSha256"],
            "FLEURS release lock SHA-256",
        ),
        dataset_id=dataset_id,
        dataset_revision=dataset_revision,
        dataset_config=dataset_config,
        split=split,
        evaluation_locale_bcp47=evaluation_locale,
        model_lock_sha256=_sha256(
            candidate["modelLockSha256"],
            "Cohere model lock SHA-256",
        ),
        pool_id=pool_id,
        model_id=model_id,
        model_revision=model_revision,
        provider_language=provider_language,
        punctuation=route["punctuation"],
        promotion_eligible=False,
        exposure_status="unknown",
        batch_size=batch_size,
        warmup_cases=warmup_cases,
        selections=tuple(selections),
        scoring_profile="word-primary-v1",
    )


def select_fleurs_comparator_run(
    plan: FleursCohereComparatorPlan,
    selection_id: str,
) -> FleursComparatorSelection:
    matches = [item for item in plan.selections if item.identifier == selection_id]
    if len(matches) != 1:
        raise ValueError("FLEURS comparator selection ID is invalid")
    return matches[0]


def bind_fleurs_comparator_release(
    plan: FleursCohereComparatorPlan,
    lock: FleursReleaseLock,
    selection: FleursComparatorSelection,
) -> None:
    observed = (
        lock.dataset_id,
        lock.dataset_revision,
        lock.dataset_config,
        lock.split,
        lock.locale_bcp47,
    )
    expected = (
        plan.dataset_id,
        plan.dataset_revision,
        plan.dataset_config,
        plan.split,
        plan.evaluation_locale_bcp47,
    )
    if observed != expected:
        raise ValueError("FLEURS release identity differs from the comparator plan")
    if selection.case_count > lock.expected_case_count:
        raise ValueError("FLEURS comparator selection exceeds the release")
    if (
        selection.selection == "all-cases-v1"
        and selection.case_count != lock.expected_case_count
    ):
        raise ValueError("FLEURS full comparator selection is incomplete")


def bind_fleurs_comparator_model(
    plan: FleursCohereComparatorPlan,
    lock: ModelPoolLock,
) -> None:
    if (
        (lock.pool_id, lock.model_id, lock.model_revision)
        != (plan.pool_id, plan.model_id, plan.model_revision)
        or plan.provider_language not in lock.supported_languages
    ):
        raise ValueError("Cohere candidate identity or route differs from the plan")


def _object(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{field} fields differ from the contract")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a nonempty array")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must be bounded text")
    return value


def _identifier(value: object, field: str) -> str:
    text = _text(value, field, 64)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(f"{field} is invalid")
    return text


def _fullmatch(value: object, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _sha256(value: object, field: str) -> str:
    return _fullmatch(value, _SHA256, field)


def _bounded_positive_int(value: object, field: str, *, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= maximum
    ):
        raise ValueError(f"{field} is outside the bound")
    return value
