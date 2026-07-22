from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Mapping, Sequence

from .contract_values import exact_keys, identifier, utc_timestamp, valid_sha256


SERVER_STAGES = ("asr", "alignment", "result_publication")
TERMINAL_STAGE_STATES = frozenset(
    {"succeeded", "unavailable", "failed", "cancelled"}
)
MAX_STAGE_ATTEMPTS = 64
MAX_STAGE_HISTORY_BYTES = 64 * 1024
MAX_STAGE_REASON_CHARS = 512
MAX_COMPONENT_REVISION_CHARS = 128
_STAGE_REASON = re.compile(r"^[A-Z0-9_]+$")

_ATTEMPT_KEYS = {
    "stage",
    "attempt",
    "state",
    "inputFingerprintSha256",
    "outputFingerprintSha256",
    "componentId",
    "componentRevision",
    "startedAtUtc",
    "completedAtUtc",
    "retryable",
    "reason",
    "evidence",
    "evidenceSha256",
}


class StageAttemptCapacityError(ValueError):
    """The bounded durable history cannot accept another stage attempt."""


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def validate_stage_attempts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > len(SERVER_STAGES) * MAX_STAGE_ATTEMPTS:
        raise ValueError("persisted stage attempts are invalid or oversized")
    if len(_canonical_json(value)) > MAX_STAGE_HISTORY_BYTES:
        raise ValueError("persisted stage attempts are oversized")

    expected_attempt = {stage: 1 for stage in SERVER_STAGES}
    running = set()
    validated: list[dict[str, object]] = []
    for raw_attempt in value:
        attempt = dict(_mapping(raw_attempt, "persisted stage attempt"))
        exact_keys(attempt, _ATTEMPT_KEYS, "persisted stage attempt")
        stage = attempt.get("stage")
        if stage not in SERVER_STAGES:
            raise ValueError("persisted stage name is invalid")
        number = attempt.get("attempt")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or number != expected_attempt[stage]
            or number > MAX_STAGE_ATTEMPTS
        ):
            raise ValueError("persisted stage attempt sequence is invalid")
        expected_attempt[stage] += 1
        if stage in running:
            raise ValueError("persisted stage has overlapping attempts")

        state = attempt.get("state")
        if state not in {"running", *TERMINAL_STAGE_STATES}:
            raise ValueError("persisted stage state is invalid")
        input_fingerprint = attempt.get("inputFingerprintSha256")
        output_fingerprint = attempt.get("outputFingerprintSha256")
        if not valid_sha256(input_fingerprint) or (
            output_fingerprint is not None and not valid_sha256(output_fingerprint)
        ):
            raise ValueError("persisted stage fingerprint is invalid")
        identifier(attempt.get("componentId"), 128, "stage component id")
        component_revision = attempt.get("componentRevision")
        if (
            not isinstance(component_revision, str)
            or not component_revision
            or len(component_revision) > MAX_COMPONENT_REVISION_CHARS
        ):
            raise ValueError("persisted stage component revision is invalid")
        started_at = utc_timestamp(attempt.get("startedAtUtc"), "stage startedAtUtc")

        completed_at_raw = attempt.get("completedAtUtc")
        retryable = attempt.get("retryable")
        reason = attempt.get("reason")
        evidence = attempt.get("evidence")
        evidence_sha256 = attempt.get("evidenceSha256")
        if state == "running":
            if any(
                field is not None
                for field in (
                    output_fingerprint,
                    completed_at_raw,
                    retryable,
                    reason,
                    evidence,
                    evidence_sha256,
                )
            ):
                raise ValueError("running stage attempt contains terminal evidence")
            running.add(stage)
        else:
            completed_at = utc_timestamp(completed_at_raw, "stage completedAtUtc")
            if completed_at < started_at or not isinstance(retryable, bool):
                raise ValueError("terminal stage attempt metadata is invalid")
            if reason is not None and (
                not isinstance(reason, str)
                or not reason
                or len(reason) > MAX_STAGE_REASON_CHARS
                or _STAGE_REASON.fullmatch(reason) is None
            ):
                raise ValueError("terminal stage reason is invalid")
            if state == "succeeded":
                if retryable is not False or reason is not None:
                    raise ValueError("succeeded stage metadata is invalid")
            elif reason is None:
                raise ValueError("non-success stage requires a reason")
            elif state in {"unavailable", "cancelled"} and retryable is not False:
                raise ValueError("terminal stage retryability is invalid")
            if evidence is None:
                if evidence_sha256 is not None:
                    raise ValueError("stage evidence hash has no evidence")
            elif (
                not valid_sha256(evidence_sha256)
                or canonical_json_sha256(evidence) != evidence_sha256
            ):
                raise ValueError("stage evidence identity is invalid")
            running.discard(stage)
        validated.append(attempt)
    return validated


def start_stage(
    attempts: list[dict[str, object]],
    *,
    stage: str,
    input_fingerprint_sha256: str,
    component_id: str,
    component_revision: str,
    started_at_utc: str,
) -> int:
    validate_stage_attempts(attempts)
    if stage not in SERVER_STAGES:
        raise ValueError("stage name is invalid")
    if any(
        attempt["stage"] == stage and attempt["state"] == "running"
        for attempt in attempts
    ):
        raise ValueError("stage already has a running attempt")
    attempt_number = 1 + sum(attempt["stage"] == stage for attempt in attempts)
    if attempt_number > MAX_STAGE_ATTEMPTS:
        raise StageAttemptCapacityError("stage attempt limit is exhausted")
    candidate: dict[str, object] = {
        "stage": stage,
        "attempt": attempt_number,
        "state": "running",
        "inputFingerprintSha256": input_fingerprint_sha256,
        "outputFingerprintSha256": None,
        "componentId": component_id,
        "componentRevision": component_revision,
        "startedAtUtc": started_at_utc,
        "completedAtUtc": None,
        "retryable": None,
        "reason": None,
        "evidence": None,
        "evidenceSha256": None,
    }
    candidate_history = [*attempts, candidate]
    if len(_canonical_json(candidate_history)) > MAX_STAGE_HISTORY_BYTES:
        raise StageAttemptCapacityError("stage history byte limit is exhausted")
    validate_stage_attempts(candidate_history)
    attempts.append(candidate)
    return attempt_number


def finish_stage(
    attempts: list[dict[str, object]],
    *,
    stage: str,
    attempt: int,
    state: str,
    completed_at_utc: str,
    retryable: bool,
    output_fingerprint_sha256: str | None = None,
    reason: str | None = None,
    evidence: object | None = None,
) -> None:
    validate_stage_attempts(attempts)
    if state not in TERMINAL_STAGE_STATES:
        raise ValueError("terminal stage state is invalid")
    current = next(
        (
            item
            for item in attempts
            if item["stage"] == stage and item["attempt"] == attempt
        ),
        None,
    )
    if current is None or current["state"] != "running":
        raise ValueError("stage attempt is not running")
    terminal = {
        **current,
        "state": state,
        "outputFingerprintSha256": output_fingerprint_sha256,
        "completedAtUtc": completed_at_utc,
        "retryable": retryable,
        "reason": reason,
        "evidence": deepcopy(evidence),
        "evidenceSha256": None if evidence is None else canonical_json_sha256(evidence),
    }
    updated = [terminal if item is current else item for item in attempts]
    validate_stage_attempts(updated)
    current.clear()
    current.update(terminal)


def latest_stage_projection(
    attempts: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    validated = validate_stage_attempts([dict(attempt) for attempt in attempts])
    latest: dict[str, dict[str, object]] = {}
    for attempt in validated:
        latest[str(attempt["stage"])] = attempt
    return [
        {
            "stage": stage,
            "attempt": latest[stage]["attempt"],
            "state": latest[stage]["state"],
            "updatedAtUtc": latest[stage]["completedAtUtc"]
            or latest[stage]["startedAtUtc"],
            "retryable": latest[stage]["retryable"],
            "reason": latest[stage]["reason"],
        }
        for stage in SERVER_STAGES
        if stage in latest
    ]


def validate_stage_projection(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > len(SERVER_STAGES):
        raise ValueError("server stage projection is invalid")
    expected_order = iter(SERVER_STAGES)
    allowed = set(SERVER_STAGES)
    observed: list[dict[str, object]] = []
    for raw in value:
        projection = dict(_mapping(raw, "server stage projection"))
        exact_keys(
            projection,
            {"stage", "attempt", "state", "updatedAtUtc", "retryable", "reason"},
            "server stage projection",
        )
        stage = projection.get("stage")
        while True:
            try:
                expected = next(expected_order)
            except StopIteration as error:
                raise ValueError("server stage projection order is invalid") from error
            if expected == stage:
                break
        if stage not in allowed:
            raise ValueError("server stage projection name is invalid")
        allowed.remove(stage)
        attempt = projection.get("attempt")
        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or not 1 <= attempt <= MAX_STAGE_ATTEMPTS
            or projection.get("state") not in {"running", *TERMINAL_STAGE_STATES}
        ):
            raise ValueError("server stage projection state is invalid")
        utc_timestamp(projection.get("updatedAtUtc"), "server stage updatedAtUtc")
        retryable = projection.get("retryable")
        if retryable is not None and not isinstance(retryable, bool):
            raise ValueError("server stage projection retryability is invalid")
        reason = projection.get("reason")
        if reason is not None and (
            not isinstance(reason, str)
            or not reason
            or len(reason) > MAX_STAGE_REASON_CHARS
            or _STAGE_REASON.fullmatch(reason) is None
        ):
            raise ValueError("server stage projection reason is invalid")
        state = projection["state"]
        if state == "running":
            if retryable is not None or reason is not None:
                raise ValueError("running stage projection metadata is invalid")
        elif state == "succeeded":
            if retryable is not False or reason is not None:
                raise ValueError("succeeded stage projection metadata is invalid")
        elif reason is None or retryable is None:
            raise ValueError("terminal stage projection metadata is invalid")
        elif state in {"unavailable", "cancelled"} and retryable is not False:
            raise ValueError("terminal stage projection retryability is invalid")
        observed.append(projection)
    return observed


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("stage evidence must be bounded JSON") from error


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value
