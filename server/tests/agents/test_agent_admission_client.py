from __future__ import annotations

import json
import unittest

from yap_server.agents.admission_client import (
    AgentAdmissionClient,
    AgentAdmissionProtocolError,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.auth import AuthenticatedPrincipal


class _RecordingTransport:
    def __init__(self, *responses: dict[str, object] | bytes) -> None:
        self.requests: list[bytes] = []
        self._responses = list(responses)

    def exchange(self, request: bytes) -> bytes:
        self.requests.append(request)
        response = self._responses.pop(0)
        if isinstance(response, bytes):
            return response
        return json.dumps(response, separators=(",", ":")).encode() + b"\n"


class AgentAdmissionClientTests(unittest.TestCase):
    def test_submit_binds_authenticated_owner_and_exact_role_contract(self) -> None:
        transport = _RecordingTransport(
            {
                "schemaVersion": 1,
                "outcome": "admitted",
                "route": "rapid-automation",
                "providerGeneration": 7,
                "queueDurationMs": 12,
            }
        )
        client = AgentAdmissionClient(transport)
        ticket = client.new_ticket()
        result = client.submit(
            ticket,
            principal=principal(),
            work=scribe_work(),
            source_sha256="a" * 64,
            remaining_deadline_ms=30_000,
        )

        self.assertEqual(result.ticket, ticket)
        self.assertEqual(result.route, ExecutionRoute.RAPID_AUTOMATION)
        self.assertEqual(result.provider_generation, 7)
        self.assertEqual(result.queue_duration_ms, 12)
        request = json.loads(transport.requests[0])
        self.assertEqual(request["tenantId"], "tenant-a")
        self.assertEqual(request["subjectId"], "alice")
        self.assertEqual(request["role"], "scribe")
        self.assertEqual(request["purpose"], "transcript-correct")
        self.assertEqual(request["route"], "rapid-automation")
        self.assertEqual(request["schedulingClass"], "hot")
        self.assertNotIn("clientId", request)
        self.assertNotIn("scopes", request)
        self.assertRegex(ticket.request_id, r"^agent-[0-9a-f]{32}$")
        self.assertRegex(ticket.cancellation_token, r"^[0-9a-f]{64}$")

    def test_duplicate_submit_recovers_by_polling_the_same_ticket(self) -> None:
        transport = _RecordingTransport(
            {"schemaVersion": 1, "outcome": "duplicate-request"},
            {"schemaVersion": 1, "outcome": "queued"},
        )
        client = AgentAdmissionClient(transport)
        ticket = client.new_ticket()

        result = client.submit(
            ticket,
            principal=principal(),
            work=scribe_work(),
            source_sha256="b" * 64,
            remaining_deadline_ms=30_000,
        )

        self.assertEqual(result.outcome, "queued")
        self.assertEqual(json.loads(transport.requests[1])["command"], "status")
        self.assertEqual(
            json.loads(transport.requests[1])["cancellationToken"],
            ticket.cancellation_token,
        )

    def test_control_operations_reuse_only_the_private_ticket(self) -> None:
        transport = _RecordingTransport(
            {
                "schemaVersion": 1,
                "outcome": "cancellation-requested",
                "reason": "client-requested",
            },
            {"schemaVersion": 1, "outcome": "cancelled"},
        )
        client = AgentAdmissionClient(transport)
        ticket = client.new_ticket()

        requested = client.cancel(ticket)
        terminal = client.acknowledge_cancellation(ticket)

        self.assertEqual(requested.cancellation_reason, "client-requested")
        self.assertEqual(terminal.outcome, "cancelled")
        for request in transport.requests:
            payload = json.loads(request)
            self.assertEqual(set(payload), {
                "cancellationToken",
                "command",
                "requestId",
                "schemaVersion",
            })

    def test_response_shape_types_duplicates_and_framing_fail_closed(self) -> None:
        invalid_responses = [
            b'{"schemaVersion":1,"outcome":"queued"}',
            b'{"schemaVersion":1,"outcome":"queued","extra":true}\n',
            b'{"schemaVersion":1,"schemaVersion":1,"outcome":"queued"}\n',
            b'{"schemaVersion":1,"outcome":"admitted","route":"rapid-automation",'
            b'"providerGeneration":true,"queueDurationMs":0}\n',
            b'{"schemaVersion":1,"outcome":"provider-unavailable",'
            b'"route":"server-io"}\n',
        ]
        for response in invalid_responses:
            with self.subTest(response=response):
                client = AgentAdmissionClient(_RecordingTransport(response))
                with self.assertRaises(AgentAdmissionProtocolError):
                    client.status(client.new_ticket())

    def test_wrong_role_binding_and_source_identity_are_rejected_before_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "differs from its role"):
            AgentWorkSpec(
                role=AgentRole.SCRIBE,
                purpose=AgentPurpose.TRANSCRIPT_CORRECT,
                route=ExecutionRoute.COMPLEX_ORCHESTRATION,
                scheduling_class=SchedulingClass.HOT,
            )
        transport = _RecordingTransport()
        client = AgentAdmissionClient(transport)
        with self.assertRaisesRegex(ValueError, "source identity"):
            client.submit(
                client.new_ticket(),
                principal=principal(),
                work=scribe_work(),
                source_sha256="not-a-digest",
                remaining_deadline_ms=30_000,
            )
        self.assertEqual(transport.requests, [])


def principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id="alice",
        client_id="desktop-client",
        scopes=frozenset({"agent.invoke"}),
    )


def scribe_work() -> AgentWorkSpec:
    return AgentWorkSpec(
        role=AgentRole.SCRIBE,
        purpose=AgentPurpose.TRANSCRIPT_CORRECT,
        route=ExecutionRoute.RAPID_AUTOMATION,
        scheduling_class=SchedulingClass.HOT,
    )
