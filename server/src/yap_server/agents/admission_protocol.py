from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import socket
import stat
from typing import Protocol


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_RESPONSE_BYTES = 4 * 1024
_TRANSPORT_TIMEOUT_SECONDS = 2.0


class AgentRole(StrEnum):
    SCRIBE = "scribe"
    ARCHIVIST = "archivist"
    STUDENT = "student"
    CURATOR = "curator"
    AUDITOR = "auditor"
    LIBRARIAN = "librarian"
    ANALYST = "analyst"
    COORDINATOR = "coordinator"


class AgentPurpose(StrEnum):
    TRANSCRIPT_CORRECT = "transcript-correct"
    KNOWLEDGE_INGEST = "knowledge-ingest"
    LEARNING_QUESTIONS = "learning-questions"
    KNOWLEDGE_PROPOSE = "knowledge-propose"
    KNOWLEDGE_AUDIT = "knowledge-audit"
    KNOWLEDGE_READ = "knowledge-read"
    KNOWLEDGE_ANSWER = "knowledge-answer"
    CONVERSATION_COORDINATE = "conversation-coordinate"


class ExecutionRoute(StrEnum):
    SERVER_IO = "server-io"
    RAPID_AUTOMATION = "rapid-automation"
    COMPLEX_ORCHESTRATION = "complex-orchestration"


class SchedulingClass(StrEnum):
    HOT = "hot"
    INTERACTIVE = "interactive"
    BACKGROUND_IO = "background-io"
    BACKGROUND_LLM = "background-llm"
    IDLE_ONLY = "idle-only"


_ROLE_BINDINGS = {
    AgentRole.SCRIBE: (
        AgentPurpose.TRANSCRIPT_CORRECT,
        frozenset({ExecutionRoute.RAPID_AUTOMATION}),
        SchedulingClass.HOT,
    ),
    AgentRole.ARCHIVIST: (
        AgentPurpose.KNOWLEDGE_INGEST,
        frozenset({ExecutionRoute.SERVER_IO}),
        SchedulingClass.BACKGROUND_IO,
    ),
    AgentRole.STUDENT: (
        AgentPurpose.LEARNING_QUESTIONS,
        frozenset({ExecutionRoute.RAPID_AUTOMATION}),
        SchedulingClass.BACKGROUND_LLM,
    ),
    AgentRole.CURATOR: (
        AgentPurpose.KNOWLEDGE_PROPOSE,
        frozenset({ExecutionRoute.COMPLEX_ORCHESTRATION}),
        SchedulingClass.BACKGROUND_LLM,
    ),
    AgentRole.AUDITOR: (
        AgentPurpose.KNOWLEDGE_AUDIT,
        frozenset({ExecutionRoute.COMPLEX_ORCHESTRATION}),
        SchedulingClass.IDLE_ONLY,
    ),
    AgentRole.LIBRARIAN: (
        AgentPurpose.KNOWLEDGE_READ,
        frozenset({ExecutionRoute.SERVER_IO}),
        SchedulingClass.INTERACTIVE,
    ),
    AgentRole.ANALYST: (
        AgentPurpose.KNOWLEDGE_ANSWER,
        frozenset(
            {
                ExecutionRoute.RAPID_AUTOMATION,
                ExecutionRoute.COMPLEX_ORCHESTRATION,
            }
        ),
        SchedulingClass.INTERACTIVE,
    ),
    AgentRole.COORDINATOR: (
        AgentPurpose.CONVERSATION_COORDINATE,
        frozenset({ExecutionRoute.COMPLEX_ORCHESTRATION}),
        SchedulingClass.BACKGROUND_LLM,
    ),
}


@dataclass(frozen=True, slots=True)
class AgentWorkSpec:
    role: AgentRole
    purpose: AgentPurpose
    route: ExecutionRoute
    scheduling_class: SchedulingClass

    def __post_init__(self) -> None:
        if not all(
            (
                isinstance(self.role, AgentRole),
                isinstance(self.purpose, AgentPurpose),
                isinstance(self.route, ExecutionRoute),
                isinstance(self.scheduling_class, SchedulingClass),
            )
        ):
            raise TypeError("agent work specification types are invalid")
        expected_purpose, routes, expected_class = _ROLE_BINDINGS[self.role]
        if (
            self.purpose != expected_purpose
            or self.route not in routes
            or self.scheduling_class != expected_class
        ):
            raise ValueError("agent work specification differs from its role")


@dataclass(frozen=True, slots=True)
class AgentAdmissionTicket:
    request_id: str
    cancellation_token: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or _REQUEST_ID.fullmatch(self.request_id) is None
        ):
            raise ValueError("agent request identity is invalid")
        if not is_lower_sha256(self.cancellation_token):
            raise ValueError("agent cancellation identity is invalid")


@dataclass(frozen=True, slots=True)
class AgentAdmission:
    ticket: AgentAdmissionTicket
    outcome: str
    route: ExecutionRoute | None = None
    provider_generation: int | None = None
    queue_duration_ms: int | None = None
    cancellation_reason: str | None = None


class AgentAdmissionTransport(Protocol):
    def exchange(self, request: bytes) -> bytes: ...


class UnixAgentAdmissionTransport:
    def __init__(self, socket_path: Path) -> None:
        if not socket_path.is_absolute():
            raise ValueError("agent admission socket path must be absolute")
        self._socket_path = socket_path

    def exchange(self, request: bytes) -> bytes:
        _validate_socket(self._socket_path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(_TRANSPORT_TIMEOUT_SECONDS)
            client.connect(str(self._socket_path))
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                part = client.recv(_MAXIMUM_RESPONSE_BYTES + 1 - len(response))
                if not part:
                    break
                response.extend(part)
                if len(response) > _MAXIMUM_RESPONSE_BYTES:
                    raise AgentAdmissionProtocolError(
                        "agent admission response is too large"
                    )
        return bytes(response)


class AgentAdmissionProtocolError(RuntimeError):
    pass


def is_lower_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def decode_admission_response(
    ticket: AgentAdmissionTicket,
    body: bytes,
) -> AgentAdmission:
    if (
        not isinstance(body, bytes)
        or not 1 <= len(body) <= _MAXIMUM_RESPONSE_BYTES
        or not body.endswith(b"\n")
        or b"\n" in body[:-1]
    ):
        raise AgentAdmissionProtocolError("agent admission response framing is invalid")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        _DuplicateKey,
    ) as error:
        raise AgentAdmissionProtocolError("agent admission response is invalid") from error
    if (
        not isinstance(value, dict)
        or isinstance(value.get("schemaVersion"), bool)
        or value.get("schemaVersion") != 1
    ):
        raise AgentAdmissionProtocolError("agent admission response schema differs")
    outcome = value.get("outcome")
    if not isinstance(outcome, str):
        raise AgentAdmissionProtocolError("agent admission outcome is invalid")

    base_keys = {"schemaVersion", "outcome"}
    if outcome == "admitted":
        if set(value) != base_keys | {
            "route",
            "providerGeneration",
            "queueDurationMs",
        }:
            raise AgentAdmissionProtocolError("agent admission fields differ")
        try:
            route = ExecutionRoute(value["route"])
        except (TypeError, ValueError) as error:
            raise AgentAdmissionProtocolError("agent admission route is invalid") from error
        generation = value["providerGeneration"]
        queue_duration = value["queueDurationMs"]
        if (
            isinstance(queue_duration, bool)
            or not isinstance(queue_duration, int)
            or not 0 <= queue_duration <= 300_000
            or (route == ExecutionRoute.SERVER_IO and generation is not None)
            or (
                route != ExecutionRoute.SERVER_IO
                and (
                    isinstance(generation, bool)
                    or not isinstance(generation, int)
                    or generation < 1
                )
            )
        ):
            raise AgentAdmissionProtocolError("agent admission lease is invalid")
        return AgentAdmission(
            ticket,
            outcome,
            route=route,
            provider_generation=generation,
            queue_duration_ms=queue_duration,
        )

    if outcome == "cancellation-requested":
        if set(value) != base_keys | {"reason"} or value["reason"] not in {
            "client-requested",
            "deadline-exceeded",
            "provider-unavailable",
        }:
            raise AgentAdmissionProtocolError("agent cancellation response is invalid")
        return AgentAdmission(ticket, outcome, cancellation_reason=value["reason"])

    if outcome == "provider-unavailable":
        if set(value) != base_keys | {"route"}:
            raise AgentAdmissionProtocolError("agent provider response fields differ")
        try:
            route = ExecutionRoute(value["route"])
        except (TypeError, ValueError) as error:
            raise AgentAdmissionProtocolError("agent provider route is invalid") from error
        if route == ExecutionRoute.SERVER_IO:
            raise AgentAdmissionProtocolError("server IO cannot be a provider route")
        return AgentAdmission(ticket, outcome, route=route)

    if outcome not in {
        "queued",
        "completed",
        "cancelled",
        "deadline-exceeded",
        "duplicate-request",
        "owner-queue-full",
        "queue-full",
        "broker-busy",
        "not-found-or-unauthorized",
        "invalid-request",
    } or set(value) != base_keys:
        raise AgentAdmissionProtocolError("agent admission outcome fields differ")
    return AgentAdmission(ticket, outcome)


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _validate_socket(path: Path) -> None:
    try:
        requested = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise AgentAdmissionProtocolError(
            "agent admission socket is unavailable"
        ) from error
    if requested != resolved or not stat.S_ISSOCK(metadata.st_mode):
        raise AgentAdmissionProtocolError("agent admission socket is invalid")
    if os.name == "posix" and (
        stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != os.geteuid()
    ):
        raise AgentAdmissionProtocolError("agent admission socket is not owner-private")
