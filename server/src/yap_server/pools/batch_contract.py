from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
import re
import threading
from typing import Callable, Literal, Mapping, Protocol, TypeAlias, cast

from yap_server.language_tags import canonical_bcp47


_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROUTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MODEL_REVISION = re.compile(r"^[0-9a-f]{40}$")
_CATALOG_REVISION = re.compile(r"^[0-9a-f]{64}$")
_BATCH_EXECUTION_MODES = frozenset({"dynamicBatch", "fixedBatch"})


class PoolBackpressure(RuntimeError):
    """Raised when every worker and bounded queue slot is occupied."""


class PoolFenced(PoolBackpressure):
    """Raised when worker containment is uncertain and capacity is quarantined."""


class DuplicatePoolJob(ValueError):
    """Raised when a job is already running or queued in the pool."""


class WorkerExecutionError(RuntimeError):
    """Raised when the isolated GPU worker fails or returns invalid output."""


class ProviderServiceUnavailable(WorkerExecutionError):
    """Raised when a resident provider is unreachable or not ready."""


class ProviderCapacityUnavailable(WorkerExecutionError):
    """Raised when a resident inference provider rejects bounded admission."""


class WorkerCancellationAcknowledged(WorkerExecutionError):
    """Raised when a worker confirms that one dispatched request was cancelled."""


class WorkerContainmentError(WorkerExecutionError):
    """Raised when an owned worker container cannot be proven absent."""


@dataclass(frozen=True, slots=True)
class AsrRouteDecision:
    """Exact private worker route resolved before a batch job is admitted."""

    provider_id: str
    pool_id: str
    execution_mode: Literal["dynamicBatch", "fixedBatch"]
    model_revision: str
    provider_language: str

    def __post_init__(self) -> None:
        validate_asr_route_id(self.provider_id, "provider_id")
        validate_asr_route_id(self.pool_id, "pool_id")
        if self.execution_mode not in _BATCH_EXECUTION_MODES:
            raise ValueError("execution_mode must be a supported batch mode")
        if _MODEL_REVISION.fullmatch(self.model_revision) is None:
            raise ValueError("model_revision must be a full immutable commit")
        if self.provider_language != "auto":
            canonical_bcp47(self.provider_language, "provider_language")

    def to_persisted(self) -> dict[str, str]:
        return {
            "providerId": self.provider_id,
            "poolId": self.pool_id,
            "executionMode": self.execution_mode,
            "modelRevision": self.model_revision,
            "providerLanguage": self.provider_language,
        }

    @classmethod
    def from_persisted(cls, value: object) -> AsrRouteDecision:
        if not isinstance(value, Mapping) or set(value) != {
            "providerId",
            "poolId",
            "executionMode",
            "modelRevision",
            "providerLanguage",
        }:
            raise ValueError("persisted ASR route fields are invalid")
        fields = tuple(value[field] for field in value)
        if not all(isinstance(field, str) for field in fields):
            raise ValueError("persisted ASR route values must be strings")
        execution_mode = cast(str, value["executionMode"])
        return cls(
            provider_id=cast(str, value["providerId"]),
            pool_id=cast(str, value["poolId"]),
            execution_mode=cast(
                Literal["dynamicBatch", "fixedBatch"],
                execution_mode,
            ),
            model_revision=cast(str, value["modelRevision"]),
            provider_language=cast(str, value["providerLanguage"]),
        )


@dataclass(frozen=True, slots=True)
class DurableAsrRouting:
    """Private restart-stable route and the catalog that selected it."""

    route: AsrRouteDecision
    asr_catalog_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.route, AsrRouteDecision):
            raise ValueError("durable ASR routing requires an immutable route")
        validate_asr_catalog_revision(self.asr_catalog_revision)

    def to_persisted(self) -> dict[str, object]:
        return {
            "asrCatalogRevision": self.asr_catalog_revision,
            "route": self.route.to_persisted(),
        }

    @classmethod
    def from_persisted(cls, value: object) -> DurableAsrRouting:
        if not isinstance(value, Mapping) or set(value) != {
            "asrCatalogRevision",
            "route",
        }:
            raise ValueError("persisted ASR routing fields are invalid")
        revision = value["asrCatalogRevision"]
        if not isinstance(revision, str):
            raise ValueError("persisted ASR catalog revision must be a string")
        return cls(
            route=AsrRouteDecision.from_persisted(value["route"]),
            asr_catalog_revision=revision,
        )


@dataclass(frozen=True)
class BatchAsrJob:
    job_id: str
    input_path: Path
    result_path: Path
    language: str
    input_sha256: str
    route: AsrRouteDecision
    capture_manifest_sha256: str | None = None
    source_frame_count: int | None = None
    punctuation: bool = True
    utterance_plan_path: Path | None = None
    utterance_plan_sha256: str | None = None

    def __post_init__(self) -> None:
        if not _JOB_ID.fullmatch(self.job_id):
            raise ValueError("job_id must be an opaque path-safe identifier")
        canonical_bcp47(self.language, "language")
        if not _SHA256.fullmatch(self.input_sha256):
            raise ValueError("input_sha256 must be a lowercase SHA-256 digest")
        if (self.capture_manifest_sha256 is None) != (self.source_frame_count is None):
            raise ValueError(
                "capture manifest identity and source frame count must be supplied together"
            )
        if self.capture_manifest_sha256 is not None and (
            _SHA256.fullmatch(self.capture_manifest_sha256) is None
            or not isinstance(self.source_frame_count, int)
            or isinstance(self.source_frame_count, bool)
            or self.source_frame_count < 1
        ):
            raise ValueError("batch source identity is invalid")
        if (self.utterance_plan_path is None) != (self.utterance_plan_sha256 is None):
            raise ValueError(
                "utterance plan path and identity must be supplied together"
            )
        if (
            self.utterance_plan_sha256 is not None
            and _SHA256.fullmatch(self.utterance_plan_sha256) is None
        ):
            raise ValueError("utterance_plan_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.route, AsrRouteDecision):
            raise ValueError("route must be an immutable ASR route decision")
        if self.route.execution_mode == "fixedBatch":
            if self.language == "und":
                raise ValueError("fixed batch jobs cannot use the und language tag")
            validate_fixed_batch_route_language(self.route, self.language)
        elif (
            self.language != "und"
            or self.route.provider_language != "auto"
            or self.utterance_plan_path is None
        ):
            raise ValueError(
                "dynamic batch jobs require und, provider auto, and a bounded utterance plan"
            )


class BatchWorker(Protocol):
    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]: ...

    def close(self) -> None: ...


BatchJobFactory: TypeAlias = Callable[[threading.Event], BatchAsrJob]
AsrRouteResolver: TypeAlias = Callable[[str], AsrRouteDecision]


def validate_fixed_batch_route_language(
    route: AsrRouteDecision,
    language_bcp47: str,
) -> None:
    language = canonical_bcp47(language_bcp47, "fixed batch language")
    provider_language = route.provider_language
    route_matches_language = (
        provider_language == language
        if "-" in provider_language
        else provider_language == language.split("-", 1)[0]
    )
    if route.execution_mode != "fixedBatch" or not route_matches_language:
        raise ValueError("fixed batch route language must match the selected language")


class BatchReservation(Protocol):
    """One bounded pool slot reserved before expensive input preparation."""

    def start(self, factory: BatchJobFactory) -> Future[dict[str, object]]: ...

    def abort(self) -> None: ...


def validate_batch_job_id(job_id: str) -> None:
    if not _JOB_ID.fullmatch(job_id):
        raise ValueError("job_id must be an opaque path-safe identifier")


def validate_asr_route_id(value: str, field: str) -> None:
    if _ROUTE_ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded path-safe identifier")


def validate_asr_catalog_revision(value: str) -> None:
    if _CATALOG_REVISION.fullmatch(value) is None:
        raise ValueError("asr_catalog_revision must be a lowercase SHA-256 digest")
