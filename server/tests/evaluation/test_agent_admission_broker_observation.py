from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.agents.admission_protocol import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
)
from yap_server.evaluation import agent_admission_broker_observation as observation


class AgentAdmissionBrokerObservationTests(unittest.TestCase):
    def test_capacity_probe_holds_exact_route_queues_overflow_and_contains(self) -> None:
        client = _CapacityClient(admit_count=4)
        state = {"identity": "unchanged"}

        observed = observation.probe_agent_admission_broker_capacity(
            client,  # type: ignore[arg-type]
            work=_student_work(),
            expected_route=ExecutionRoute.RAPID_AUTOMATION,
            expected_capacity=4,
            tenant_id="student-qualification",
            run_scope="run-12345678",
            observe_provider_state=lambda: state,
            observe_broker_state=lambda: state,
        )

        self.assertEqual(observed["admittedOwnerCount"], 4)
        self.assertTrue(observed["expectedCapacityObserved"])
        self.assertTrue(observed["expectedRouteObserved"])
        self.assertTrue(observed["overflowOwnerQueued"])
        self.assertTrue(observed["contained"])
        self.assertEqual(len(set(client.owners)), 5)
        self.assertTrue(
            all(item.outcome == "cancelled" for item in client.state.values())
        )
        self.assertEqual(len(client.acknowledged), 4)

    def test_capacity_probe_rejects_reduced_or_unbounded_capacity(self) -> None:
        state = {"identity": "unchanged"}
        for admitted, message in (
            (3, "did not admit"),
            (5, "exceeded"),
        ):
            client = _CapacityClient(admit_count=admitted)
            with self.subTest(admitted=admitted), self.assertRaisesRegex(
                RuntimeError,
                message,
            ):
                observation.probe_agent_admission_broker_capacity(
                    client,  # type: ignore[arg-type]
                    work=_student_work(),
                    expected_route=ExecutionRoute.RAPID_AUTOMATION,
                    expected_capacity=4,
                    tenant_id="student-qualification",
                    run_scope="run-12345678",
                    observe_provider_state=lambda: state,
                    observe_broker_state=lambda: state,
                )
            self.assertTrue(
                all(item.outcome == "cancelled" for item in client.state.values())
            )

    def test_capacity_probe_rejects_unproven_cleanup_identity(self) -> None:
        client = _CapacityClient(admit_count=4, unproven_status=True)
        with self.assertRaisesRegex(RuntimeError, "not contained"):
            observation.probe_agent_admission_broker_capacity(
                client,  # type: ignore[arg-type]
                work=_student_work(),
                expected_route=ExecutionRoute.RAPID_AUTOMATION,
                expected_capacity=4,
                tenant_id="student-qualification",
                run_scope="run-12345678",
                observe_provider_state=lambda: {"identity": "unchanged"},
                observe_broker_state=lambda: {"identity": "unchanged"},
            )

    @unittest.skipUnless(os.name == "posix", "Unix peer credentials are POSIX-only")
    def test_observation_binds_socket_process_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "admission.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(1)

            def accept_once() -> None:
                connection, _address = server.accept()
                connection.close()

            thread = threading.Thread(target=accept_once)
            thread.start()
            try:
                expected = observation.process_binary_sha256(os.getpid())
                with mock.patch.object(
                    observation,
                    "_validate_broker_command_line",
                ):
                    observed = observation.observe_admission_broker(
                        path,
                        expected_binary_sha256=expected,
                        expected_candidate_lock_sha256="a" * 64,
                        expected_rapid_profile_sha256="b" * 64,
                        expected_rapid_state_path=root,
                    )
            finally:
                thread.join(timeout=2)
                server.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(observed["processId"], os.getpid())
            self.assertEqual(observed["binarySha256"], expected)
            self.assertGreater(observed["processStartTicks"], 0)


def _student_work() -> AgentWorkSpec:
    return AgentWorkSpec(
        role=AgentRole.STUDENT,
        purpose=AgentPurpose.LEARNING_QUESTIONS,
        route=ExecutionRoute.RAPID_AUTOMATION,
        scheduling_class=SchedulingClass.BACKGROUND_LLM,
    )


class _CapacityClient:
    def __init__(self, *, admit_count: int, unproven_status: bool = False) -> None:
        self.counter = 0
        self.admit_count = admit_count
        self.unproven_status = unproven_status
        self.owners: list[str] = []
        self.state: dict[str, AgentAdmission] = {}
        self.acknowledged: list[str] = []

    def new_ticket(self) -> AgentAdmissionTicket:
        ticket = AgentAdmissionTicket(
            f"capacity-{self.counter}",
            f"{self.counter + 1:064x}",
        )
        self.counter += 1
        return ticket

    def submit(self, ticket, *, principal, work, source_sha256, remaining_deadline_ms):
        self.owners.append(principal.subject_id)
        assert work == _student_work()
        assert len(source_sha256) == 64
        assert remaining_deadline_ms == 60_000
        admission = (
            AgentAdmission(
                ticket,
                "admitted",
                route=ExecutionRoute.RAPID_AUTOMATION,
                provider_generation=7,
                queue_duration_ms=0,
            )
            if len(self.owners) <= self.admit_count
            else AgentAdmission(ticket, "queued")
        )
        self.state[ticket.request_id] = admission
        return admission

    def status(self, ticket):
        if self.unproven_status:
            return AgentAdmission(ticket, "not-found-or-unauthorized")
        return self.state[ticket.request_id]

    def cancel(self, ticket):
        current = self.state[ticket.request_id]
        if current.outcome == "queued":
            result = AgentAdmission(ticket, "cancelled")
        else:
            result = AgentAdmission(
                ticket,
                "cancellation-requested",
                cancellation_reason="client-requested",
            )
        self.state[ticket.request_id] = result
        return result

    def acknowledge_cancellation(self, ticket):
        self.acknowledged.append(ticket.request_id)
        result = AgentAdmission(ticket, "cancelled")
        self.state[ticket.request_id] = result
        return result


if __name__ == "__main__":
    unittest.main()
