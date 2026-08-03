from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from yap_server.auth import PrincipalKey

from .contract_values import exact_keys, identifier, mapping
from .stage_attempts import validate_stage_attempts


PERSISTED_JOB_STATE_SCHEMA_VERSION = 6


@dataclass(frozen=True, slots=True)
class PersistedJobStateMetadata:
    owner: PrincipalKey
    create_idempotency_key: str | None
    cancellation_requested: bool
    asr_routing: object | None
    stage_history_complete: bool
    stage_attempts: list[dict[str, object]]
    projection_revision: int


def persisted_state_metadata(
    state: Mapping[str, object],
) -> PersistedJobStateMetadata:
    if state.get("schemaVersion") != PERSISTED_JOB_STATE_SCHEMA_VERSION:
        raise ValueError("persisted job state has an unsupported schema")
    exact_keys(
        state,
        {
            "schemaVersion",
            "owner",
            "createIdempotencyKey",
            "cancellationRequested",
            "asrRouting",
            "stageHistoryComplete",
            "stageAttempts",
            "projectionRevision",
            "creation",
            "projection",
            "receipts",
        },
        "persisted job state",
    )
    owner_value = mapping(state.get("owner"), "persisted owner")
    exact_keys(
        owner_value,
        {"tenantId", "subjectId"},
        "persisted owner",
    )
    owner = PrincipalKey(
        tenant_id=identifier(
            owner_value.get("tenantId"),
            128,
            "persisted owner tenant",
        ),
        subject_id=identifier(
            owner_value.get("subjectId"),
            128,
            "persisted owner subject",
        ),
    )
    raw_create_key = state.get("createIdempotencyKey")
    create_idempotency_key = (
        None
        if raw_create_key is None
        else identifier(raw_create_key, 128, "create idempotency key")
    )
    cancellation_requested = state.get("cancellationRequested")
    if not isinstance(cancellation_requested, bool):
        raise ValueError("persisted cancellation request is invalid")
    stage_history_complete = state.get("stageHistoryComplete")
    if not isinstance(stage_history_complete, bool):
        raise ValueError("persisted stage-history completeness is invalid")
    projection_revision = state.get("projectionRevision")
    if (
        isinstance(projection_revision, bool)
        or not isinstance(projection_revision, int)
        or projection_revision < 1
    ):
        raise ValueError("persisted projection revision is invalid")
    return PersistedJobStateMetadata(
        owner=owner,
        create_idempotency_key=create_idempotency_key,
        cancellation_requested=cancellation_requested,
        asr_routing=state.get("asrRouting"),
        stage_history_complete=stage_history_complete,
        stage_attempts=validate_stage_attempts(state.get("stageAttempts")),
        projection_revision=projection_revision,
    )
