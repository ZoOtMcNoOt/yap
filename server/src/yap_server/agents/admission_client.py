from __future__ import annotations

import json
import secrets
from uuid import uuid4

from yap_server.agents.admission_protocol import (
    AgentAdmission,
    AgentAdmissionProtocolError,
    AgentAdmissionTicket,
    AgentAdmissionTransport,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
    UnixAgentAdmissionTransport,
    decode_admission_response,
    is_lower_sha256,
)
from yap_server.auth import AuthenticatedPrincipal


class AgentAdmissionClient:
    def __init__(self, transport: AgentAdmissionTransport) -> None:
        self._transport = transport

    @staticmethod
    def new_ticket() -> AgentAdmissionTicket:
        return AgentAdmissionTicket(
            request_id=f"agent-{uuid4().hex}",
            cancellation_token=secrets.token_hex(32),
        )

    def submit(
        self,
        ticket: AgentAdmissionTicket,
        *,
        principal: AuthenticatedPrincipal,
        work: AgentWorkSpec,
        source_sha256: str,
        remaining_deadline_ms: int,
    ) -> AgentAdmission:
        if not is_lower_sha256(source_sha256):
            raise ValueError("agent source identity is invalid")
        if (
            isinstance(remaining_deadline_ms, bool)
            or not isinstance(remaining_deadline_ms, int)
            or remaining_deadline_ms <= 0
        ):
            raise ValueError("agent remaining deadline is invalid")
        admission = self._exchange(
            ticket,
            {
                "schemaVersion": 1,
                "command": "submit",
                "requestId": ticket.request_id,
                "tenantId": principal.tenant_id,
                "subjectId": principal.subject_id,
                "purpose": work.purpose.value,
                "role": work.role.value,
                "sourceSha256": source_sha256,
                "route": work.route.value,
                "schedulingClass": work.scheduling_class.value,
                "cancellationToken": ticket.cancellation_token,
                "remainingDeadlineMs": remaining_deadline_ms,
            },
        )
        return self.status(ticket) if admission.outcome == "duplicate-request" else admission

    def status(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        return self._control(ticket, "status")

    def cancel(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        return self._control(ticket, "cancel")

    def complete(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        return self._control(ticket, "complete")

    def acknowledge_cancellation(
        self,
        ticket: AgentAdmissionTicket,
    ) -> AgentAdmission:
        return self._control(ticket, "acknowledge-cancellation")

    def _control(self, ticket: AgentAdmissionTicket, command: str) -> AgentAdmission:
        return self._exchange(
            ticket,
            {
                "schemaVersion": 1,
                "command": command,
                "requestId": ticket.request_id,
                "cancellationToken": ticket.cancellation_token,
            },
        )

    def _exchange(
        self,
        ticket: AgentAdmissionTicket,
        payload: dict[str, object],
    ) -> AgentAdmission:
        request = (
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            + b"\n"
        )
        return decode_admission_response(ticket, self._transport.exchange(request))


__all__ = [
    "AgentAdmission",
    "AgentAdmissionClient",
    "AgentAdmissionProtocolError",
    "AgentAdmissionTicket",
    "AgentPurpose",
    "AgentRole",
    "AgentWorkSpec",
    "ExecutionRoute",
    "SchedulingClass",
    "UnixAgentAdmissionTransport",
]
