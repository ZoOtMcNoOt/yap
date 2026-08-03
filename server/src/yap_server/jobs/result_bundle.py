from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

from yap_server.pools.batch_contract import AsrRouteDecision, validate_asr_route_id

from .contract_values import utc_timestamp, valid_sha256


@dataclass(frozen=True, slots=True)
class ResultRevisionBundle:
    transcript_result: dict[str, object]
    speaker_result: dict[str, object] | None
    created_at_utc: str
    worker_output_sha256: str
    result_shape: str

    def __post_init__(self) -> None:
        utc_timestamp(self.created_at_utc, "result bundle creation time")
        if not valid_sha256(self.worker_output_sha256):
            raise ValueError("result bundle worker output identity is invalid")
        if not isinstance(self.result_shape, str) or not self.result_shape:
            raise ValueError("result bundle shape is invalid")
        declares_speaker_result = "speakerResultSha256" in self.transcript_result
        if declares_speaker_result != (self.speaker_result is not None):
            raise ValueError("result bundle speaker companion is incomplete")

    def validate_companion_policy(self, requires_speaker_result: bool) -> None:
        if not isinstance(requires_speaker_result, bool):
            raise ValueError("result bundle companion policy must be boolean")
        if requires_speaker_result != (self.speaker_result is not None):
            raise ValueError(
                "adapted result companion differs from the frozen route policy"
            )


@runtime_checkable
class ResultBundleAdapter(Protocol):
    @property
    def pool_id(self) -> str: ...

    @property
    def requires_speaker_result(self) -> bool: ...

    def build_result_bundle(
        self,
        worker_result: Mapping[str, object],
        *,
        projection: Mapping[str, object],
        creation: Mapping[str, object],
        route: AsrRouteDecision,
        created_at_utc: str,
        language_bcp47: str,
        maximum_end_ms: int,
    ) -> ResultRevisionBundle: ...

    def validate_persisted_result_bundle(
        self,
        transcript_result: Mapping[str, object],
        speaker_result: Mapping[str, object] | None,
        *,
        projection: Mapping[str, object],
        creation: Mapping[str, object],
        route: AsrRouteDecision,
        maximum_end_ms: int,
    ) -> None: ...


class ResultBundleAdapterRegistry:
    """Immutable route-to-publication policy supplied by the composition root."""

    def __init__(
        self,
        adapters: Mapping[str, ResultBundleAdapter] | None = None,
    ) -> None:
        copied = dict(adapters or {})
        if len(copied) > 8:
            raise ValueError("result bundle adapter registry is oversized")
        for pool_id, adapter in copied.items():
            validate_asr_route_id(pool_id, "result bundle adapter pool ID")
            if not isinstance(adapter, ResultBundleAdapter):
                raise ValueError("result bundle adapter contract is incomplete")
            if adapter.pool_id != pool_id:
                raise ValueError(
                    "result bundle adapter is registered to the wrong pool"
                )
            if not isinstance(adapter.requires_speaker_result, bool):
                raise ValueError("result bundle companion policy must be boolean")
        self._adapters = MappingProxyType(copied)

    def for_route(self, route: AsrRouteDecision) -> ResultBundleAdapter | None:
        return self._adapters.get(route.pool_id)


def result_bundle_fingerprint(
    transcript_result: Mapping[str, object],
    speaker_result: Mapping[str, object] | None,
) -> dict[str, object] | Mapping[str, object]:
    if speaker_result is None:
        return transcript_result
    return {
        "transcriptResult": transcript_result,
        "speakerResult": speaker_result,
    }
