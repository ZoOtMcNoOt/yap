from __future__ import annotations

from typing import Mapping

from .contract_values import exact_keys, identifier
from .stage_attempts import validate_stage_attempts


def persisted_state_metadata(
    state: Mapping[str, object],
) -> tuple[
    int,
    str | None,
    bool,
    object | None,
    bool,
    list[dict[str, object]],
    int,
]:
    schema_version = state.get("schemaVersion")
    if schema_version == 1:
        exact_keys(
            state,
            {"schemaVersion", "creation", "projection", "receipts"},
            "persisted job state",
        )
        return 1, None, False, None, False, [], 0
    if schema_version == 2:
        exact_keys(
            state,
            {
                "schemaVersion",
                "createIdempotencyKey",
                "creation",
                "projection",
                "receipts",
            },
            "persisted job state",
        )
        cancellation_requested = False
    elif schema_version in {3, 4, 5}:
        expected_keys = {
            "schemaVersion",
            "createIdempotencyKey",
            "cancellationRequested",
            "creation",
            "projection",
            "receipts",
        }
        if schema_version in {4, 5}:
            expected_keys.add("asrRouting")
        if schema_version == 5:
            expected_keys.update(
                {"stageHistoryComplete", "stageAttempts", "projectionRevision"}
            )
        exact_keys(
            state,
            expected_keys,
            "persisted job state",
        )
        cancellation_requested = state.get("cancellationRequested")
        if not isinstance(cancellation_requested, bool):
            raise ValueError("persisted cancellation request is invalid")
    else:
        raise ValueError("persisted job state has an unsupported schema")
    raw_create_key = state.get("createIdempotencyKey")
    create_idempotency_key = (
        None
        if raw_create_key is None
        else identifier(raw_create_key, 128, "create idempotency key")
    )
    routing = state.get("asrRouting") if schema_version in {4, 5} else None
    if schema_version == 5:
        stage_history_complete = state.get("stageHistoryComplete")
        if not isinstance(stage_history_complete, bool):
            raise ValueError("persisted stage-history completeness is invalid")
        stage_attempts = validate_stage_attempts(state.get("stageAttempts"))
        projection_revision = state.get("projectionRevision")
        if (
            isinstance(projection_revision, bool)
            or not isinstance(projection_revision, int)
            or projection_revision < 1
        ):
            raise ValueError("persisted projection revision is invalid")
    else:
        stage_history_complete = False
        stage_attempts = []
        projection_revision = 0
    return (
        schema_version,
        create_idempotency_key,
        cancellation_requested,
        routing,
        stage_history_complete,
        stage_attempts,
        projection_revision,
    )
