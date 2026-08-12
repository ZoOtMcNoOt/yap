from __future__ import annotations

import hashlib
import threading
import time
import unittest
from unittest import mock

from yap_server.agents import (
    AgentAdmission,
    AgentAdmissionTicket,
    ExecutionRoute,
)
from yap_server.agents.transcript_correction import (
    BoundTranscriptCorrectionRequest,
    TranscriptCorrectionRequest,
    TranscriptCorrectionTerminology,
    correction_request_sha256,
    parse_transcript_correction_response,
    validate_transcript_correction,
)
from yap_server.agents.transcript_correction_model import TranscriptCorrectionCancelled
import yap_server.agents.transcript_correction_service as transcript_correction_service
from yap_server.agents.transcript_correction_service import (
    TranscriptCorrectionContainmentError,
    TranscriptCorrectionService,
    TranscriptCorrectionServiceError,
    TranscriptCorrectionTerminologyUnavailable,
)
from yap_server.auth import AuthenticatedPrincipal


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _principal(subject: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> TranscriptCorrectionRequest:
    text = "Um, the dosage is 25 mg."
    return TranscriptCorrectionRequest.from_wire(
        {
            "schemaVersion": 1,
            "sourceRevisionSha256": "a" * 64,
            "sourceSha256": _sha256(text),
            "segments": [
                {
                    "segmentId": "segment-0001",
                    "startCharacter": 0,
                    "endCharacter": len(text),
                    "startMilliseconds": 0,
                    "endMilliseconds": 1_500,
                    "languageBcp47": "en-US",
                    "text": text,
                    "textSha256": _sha256(text),
                }
            ],
        }
    )


def _correction(request: BoundTranscriptCorrectionRequest):
    return validate_transcript_correction(
        request,
        parse_transcript_correction_response(
            {
                "schemaVersion": 1,
                "requestSha256": correction_request_sha256(request),
                "sourceSha256": request.source_sha256,
                "uncertain": False,
                "edits": [
                    {
                        "segmentId": "segment-0001",
                        "segmentSha256": request.segments[0].text_sha256,
                        "startCharacter": 0,
                        "endCharacter": 5,
                        "sourceText": "Um, t",
                        "replacementText": "T",
                    }
                ],
            }
        ),
    )


class _Admission:
    def __init__(self, *, initially_queued: bool = False) -> None:
        self.initially_queued = initially_queued
        self._next = 0
        self._outcomes: dict[str, str] = {}
        self._cancellation_reasons: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.generation = 7
        self._lock = threading.Lock()

    def new_ticket(self) -> AgentAdmissionTicket:
        with self._lock:
            self._next += 1
            value = self._next
        return AgentAdmissionTicket(f"scribe-{value}", f"{value:064x}")

    def submit(self, ticket, **kwargs):
        del kwargs
        with self._lock:
            outcome = "queued" if self.initially_queued else "admitted"
            self._outcomes[ticket.request_id] = outcome
            self.calls.append(("submit", ticket.request_id))
        return self._admission(ticket, outcome)

    def status(self, ticket):
        with self._lock:
            outcome = self._outcomes[ticket.request_id]
            self.calls.append(("status", ticket.request_id))
        return self._admission(ticket, outcome)

    def admit(self, request_id: str) -> None:
        with self._lock:
            self._outcomes[request_id] = "admitted"

    def cancel(self, ticket):
        with self._lock:
            if self._outcomes[ticket.request_id] != "cancellation-requested":
                self._outcomes[ticket.request_id] = "cancellation-requested"
                self._cancellation_reasons[ticket.request_id] = "client-requested"
            reason = self._cancellation_reasons[ticket.request_id]
            self.calls.append(("cancel", ticket.request_id))
        return AgentAdmission(
            ticket,
            "cancellation-requested",
            cancellation_reason=reason,
        )

    def acknowledge_cancellation(self, ticket):
        with self._lock:
            reason = self._cancellation_reasons[ticket.request_id]
            outcome = {
                "client-requested": "cancelled",
                "deadline-exceeded": "deadline-exceeded",
                "provider-unavailable": "provider-unavailable",
            }[reason]
            self._outcomes[ticket.request_id] = outcome
            self.calls.append(("acknowledge-cancellation", ticket.request_id))
        return AgentAdmission(ticket, outcome)

    def complete(self, ticket):
        with self._lock:
            self._outcomes[ticket.request_id] = "completed"
            self.calls.append(("complete", ticket.request_id))
        return AgentAdmission(ticket, "completed")

    def request_cancellation(self, request_id: str, reason: str) -> None:
        with self._lock:
            self._outcomes[request_id] = "cancellation-requested"
            self._cancellation_reasons[request_id] = reason

    def _admission(self, ticket, outcome: str):
        if outcome == "admitted":
            return AgentAdmission(
                ticket,
                outcome,
                route=ExecutionRoute.RAPID_AUTOMATION,
                provider_generation=self.generation,
                queue_duration_ms=0,
            )
        if outcome == "cancellation-requested":
            return AgentAdmission(
                ticket,
                outcome,
                cancellation_reason=self._cancellation_reasons[ticket.request_id],
            )
        return AgentAdmission(ticket, outcome)


class _Model:
    def __init__(self) -> None:
        self.calls = 0
        self.last_request = None

    def correct(self, request, *, cancellation):
        self.calls += 1
        self.last_request = request
        if cancellation.is_set():
            raise TranscriptCorrectionCancelled("cancelled")
        return _correction(request)


class _BlockingModel:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def correct(self, request, *, cancellation):
        del request
        self.started.set()
        cancellation.wait(2.0)
        self.stopped.set()
        raise TranscriptCorrectionCancelled("cancelled")


class _InvalidModel:
    def correct(self, request, *, cancellation):
        del request, cancellation
        raise ValueError("private model output must not escape")


class _NoChangeModel:
    def correct(self, request, *, cancellation):
        del cancellation
        return validate_transcript_correction(
            request,
            parse_transcript_correction_response(
                {
                    "schemaVersion": 1,
                    "requestSha256": correction_request_sha256(request),
                    "sourceSha256": request.source_sha256,
                    "uncertain": False,
                    "edits": [],
                }
            ),
        )


class _Terminology:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve(self, *, principal, locale):
        self.calls.append((principal.subject_id, locale))
        return TranscriptCorrectionTerminology("c" * 64, ("dosage",))


def _service(*, admission, model, terminology=None):
    return TranscriptCorrectionService(
        admission=admission,
        model=model,
        terminology=terminology or _Terminology(),
    )


def _wait_for(service, request_id: str, owner, status: str):
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        view = service.get(request_id, principal=owner)
        if view is not None and view.status == status:
            return view
        time.sleep(0.01)
    raise AssertionError(f"request did not reach {status}")


class TranscriptCorrectionServiceTests(unittest.TestCase):
    def test_queued_job_waits_for_admission_then_completes_exact_lease(self) -> None:
        admission = _Admission(initially_queued=True)
        model = _Model()
        service = _service(
            admission=admission,
            model=model,
        )
        self.addCleanup(service.close)

        submitted = service.submit(_request(), principal=_principal("alice"))
        self.assertEqual(submitted.status, "queued")
        self.assertEqual(model.calls, 0)
        admission.admit(submitted.request_id)

        completed = _wait_for(service, submitted.request_id, _principal("alice"), "complete")
        self.assertTrue(completed.applied)
        self.assertEqual(completed.terminology_snapshot_sha256, "c" * 64)
        self.assertEqual(completed.corrected_text, "The dosage is 25 mg.")
        self.assertEqual(model.calls, 1)
        self.assertEqual(model.last_request.approved_terminology, ("dosage",))
        self.assertEqual(
            [call[0] for call in admission.calls if call[0] in {"submit", "complete"}],
            ["submit", "complete"],
        )

    def test_terminology_is_server_derived_before_broker_admission(self) -> None:
        admission = _Admission()
        terminology = _Terminology()
        service = _service(
            admission=admission,
            model=_Model(),
            terminology=terminology,
        )
        self.addCleanup(service.close)

        submitted = service.submit(_request(), principal=_principal("alice"))

        self.assertEqual(
            terminology.calls,
            [("alice", "en-US")],
        )
        self.assertEqual(admission.calls[0], ("submit", submitted.request_id))

    def test_terminology_failure_does_not_enter_the_shared_broker(self) -> None:
        class _UnavailableTerminology:
            def resolve(self, **kwargs):
                del kwargs
                raise TranscriptCorrectionTerminologyUnavailable("private detail")

        admission = _Admission()
        service = _service(
            admission=admission,
            model=_Model(),
            terminology=_UnavailableTerminology(),
        )
        self.addCleanup(service.close)

        with self.assertRaises(TranscriptCorrectionServiceError) as raised:
            service.submit(_request(), principal=_principal("alice"))

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(
            raised.exception.code,
            "TRANSCRIPT_CORRECTION_TERMINOLOGY_UNAVAILABLE",
        )
        self.assertNotIn("private", raised.exception.message)
        self.assertEqual(admission.calls, [])

    def test_terminology_resolution_is_inside_the_total_deadline(self) -> None:
        class _SlowTerminology(_Terminology):
            def resolve(self, **kwargs):
                time.sleep(0.06)
                return super().resolve(**kwargs)

        admission = _Admission()
        with mock.patch.object(
            transcript_correction_service,
            "_JOB_DEADLINE_SECONDS",
            0.05,
        ):
            service = _service(
                admission=admission,
                model=_Model(),
                terminology=_SlowTerminology(),
            )
            self.addCleanup(service.close)
            with self.assertRaises(TranscriptCorrectionServiceError) as raised:
                service.submit(_request(), principal=_principal("alice"))

        self.assertEqual(raised.exception.status, 504)
        self.assertEqual(admission.calls, [])

    def test_terminal_history_does_not_consume_inflight_capacity(self) -> None:
        with mock.patch.object(
            transcript_correction_service,
            "_MAXIMUM_INFLIGHT_JOBS",
            1,
        ):
            service = _service(admission=_Admission(), model=_Model())
            self.addCleanup(service.close)
            first = service.submit(_request(), principal=_principal("alice"))
            _wait_for(service, first.request_id, _principal("alice"), "complete")

            second = service.submit(_request(), principal=_principal("bob"))
            completed = _wait_for(
                service,
                second.request_id,
                _principal("bob"),
                "complete",
            )

        self.assertTrue(completed.applied)

    def test_terminal_history_is_bounded_without_evicting_inflight_work(self) -> None:
        with mock.patch.object(
            transcript_correction_service,
            "_MAXIMUM_RETAINED_TERMINAL_JOBS",
            1,
        ):
            service = _service(admission=_Admission(), model=_Model())
            self.addCleanup(service.close)
            first = service.submit(_request(), principal=_principal("alice"))
            _wait_for(service, first.request_id, _principal("alice"), "complete")
            second = service.submit(_request(), principal=_principal("bob"))
            _wait_for(service, second.request_id, _principal("bob"), "complete")

            third = service.submit(_request(), principal=_principal("carol"))

        self.assertIsNone(
            service.get(first.request_id, principal=_principal("alice"))
        )
        self.assertIsNotNone(
            service.get(second.request_id, principal=_principal("bob"))
        )
        self.assertIsNotNone(
            service.get(third.request_id, principal=_principal("carol"))
        )

    def test_concurrent_users_share_one_bounded_inflight_capacity(self) -> None:
        class _BlockingTerminology(_Terminology):
            def __init__(self) -> None:
                super().__init__()
                self.entered = threading.Event()
                self.release = threading.Event()

            def resolve(self, **kwargs):
                self.entered.set()
                self.release.wait(2.0)
                return super().resolve(**kwargs)

        terminology = _BlockingTerminology()
        with mock.patch.object(
            transcript_correction_service,
            "_MAXIMUM_INFLIGHT_JOBS",
            1,
        ):
            service = _service(
                admission=_Admission(),
                model=_Model(),
                terminology=terminology,
            )
            self.addCleanup(service.close)
            first_result: list[object] = []

            def submit_first_user() -> None:
                first_result.append(
                    service.submit(_request(), principal=_principal("alice"))
                )

            first_thread = threading.Thread(target=submit_first_user)
            first_thread.start()
            self.assertTrue(terminology.entered.wait(1.0))

            with self.assertRaises(TranscriptCorrectionServiceError) as raised:
                service.submit(_request(), principal=_principal("bob"))

            terminology.release.set()
            first_thread.join(2.0)

        self.assertFalse(first_thread.is_alive())
        self.assertEqual(len(first_result), 1)
        self.assertEqual(raised.exception.status, 429)

    def test_owner_isolation_hides_status_and_cancellation(self) -> None:
        admission = _Admission(initially_queued=True)
        service = _service(admission=admission, model=_Model())
        self.addCleanup(service.close)
        submitted = service.submit(_request(), principal=_principal("alice"))

        self.assertIsNone(service.get(submitted.request_id, principal=_principal("bob")))
        self.assertFalse(service.cancel(submitted.request_id, principal=_principal("bob")))
        self.assertTrue(service.cancel(submitted.request_id, principal=_principal("alice")))
        _wait_for(service, submitted.request_id, _principal("alice"), "cancelled")

    def test_running_cancellation_is_acknowledged_only_after_model_stops(self) -> None:
        admission = _Admission()
        model = _BlockingModel()
        service = _service(admission=admission, model=model)
        self.addCleanup(service.close)
        submitted = service.submit(_request(), principal=_principal("alice"))
        self.assertTrue(model.started.wait(1.0))

        self.assertTrue(service.cancel(submitted.request_id, principal=_principal("alice")))
        cancelled = _wait_for(
            service,
            submitted.request_id,
            _principal("alice"),
            "cancelled",
        )

        self.assertFalse(cancelled.applied)
        self.assertTrue(model.stopped.is_set())
        operations = [operation for operation, _ in admission.calls]
        self.assertLess(operations.index("cancel"), operations.index("acknowledge-cancellation"))

    def test_total_deadline_cancels_running_model_before_acknowledgement(self) -> None:
        admission = _Admission()
        model = _BlockingModel()
        with mock.patch.object(
            transcript_correction_service,
            "_JOB_DEADLINE_SECONDS",
            0.05,
        ):
            service = _service(admission=admission, model=model)
            self.addCleanup(service.close)
            request = _request()
            submitted = service.submit(request, principal=_principal("alice"))
            self.assertTrue(model.started.wait(1.0))

            completed = _wait_for(
                service,
                submitted.request_id,
                _principal("alice"),
                "complete",
            )

        self.assertFalse(completed.applied)
        self.assertEqual(completed.corrected_text, request.source_text)
        self.assertEqual(completed.reason, "deadline-exceeded")
        self.assertTrue(model.stopped.is_set())
        operations = [operation for operation, _ in admission.calls]
        self.assertLess(operations.index("cancel"), operations.index("acknowledge-cancellation"))
        self.assertFalse(
            any(
                thread.name == f"scribe-deadline-{submitted.request_id}"
                and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    def test_broker_deadline_terminal_is_acknowledged_without_fencing(self) -> None:
        model = _Model()

        class _BrokerDeadlineAdmission(_Admission):
            def status(self, ticket):
                if model.calls:
                    self.request_cancellation(ticket.request_id, "deadline-exceeded")
                return super().status(ticket)

        admission = _BrokerDeadlineAdmission()
        service = _service(admission=admission, model=model)
        self.addCleanup(service.close)
        request = _request()
        submitted = service.submit(request, principal=_principal("alice"))

        completed = _wait_for(service, submitted.request_id, _principal("alice"), "complete")

        self.assertFalse(completed.applied)
        self.assertEqual(completed.corrected_text, request.source_text)
        self.assertEqual(completed.reason, "deadline-exceeded")
        operations = [operation for operation, _ in admission.calls]
        self.assertEqual(
            [
                operation
                for operation in operations
                if operation in {"cancel", "acknowledge-cancellation", "complete"}
            ],
            ["cancel", "acknowledge-cancellation"],
        )

    def test_success_disarms_deadline_watcher(self) -> None:
        admission = _Admission()
        with mock.patch.object(
            transcript_correction_service,
            "_JOB_DEADLINE_SECONDS",
            0.05,
        ):
            service = _service(admission=admission, model=_Model())
            self.addCleanup(service.close)
            submitted = service.submit(_request(), principal=_principal("alice"))
            completed = _wait_for(
                service,
                submitted.request_id,
                _principal("alice"),
                "complete",
            )
            time.sleep(0.08)

        self.assertTrue(completed.applied)
        current = service.get(submitted.request_id, principal=_principal("alice"))
        self.assertIsNotNone(current)
        self.assertTrue(current.applied)
        self.assertNotIn("cancel", [operation for operation, _ in admission.calls])
        self.assertFalse(
            any(
                thread.name == f"scribe-deadline-{submitted.request_id}"
                and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    def test_client_cancellation_reason_is_not_overwritten_by_deadline(self) -> None:
        admission = _Admission()
        model = _BlockingModel()
        with mock.patch.object(
            transcript_correction_service,
            "_JOB_DEADLINE_SECONDS",
            0.2,
        ):
            service = _service(admission=admission, model=model)
            self.addCleanup(service.close)
            submitted = service.submit(_request(), principal=_principal("alice"))
            self.assertTrue(model.started.wait(1.0))
            self.assertTrue(service.cancel(submitted.request_id, principal=_principal("alice")))
            cancelled = _wait_for(
                service,
                submitted.request_id,
                _principal("alice"),
                "cancelled",
            )
            time.sleep(0.25)

        self.assertEqual(cancelled.reason, "client-cancelled")
        current = service.get(submitted.request_id, principal=_principal("alice"))
        self.assertIsNotNone(current)
        self.assertEqual(current.status, "cancelled")
        self.assertEqual(current.reason, "client-cancelled")

    def test_deadline_during_completion_never_publishes_model_output(self) -> None:
        class _SlowCompleteAdmission(_Admission):
            def __init__(self) -> None:
                super().__init__()
                self.completing = threading.Event()

            def complete(self, ticket):
                self.completing.set()
                time.sleep(0.08)
                return super().complete(ticket)

        admission = _SlowCompleteAdmission()
        with mock.patch.object(
            transcript_correction_service,
            "_JOB_DEADLINE_SECONDS",
            0.05,
        ):
            service = _service(admission=admission, model=_Model())
            self.addCleanup(service.close)
            request = _request()
            submitted = service.submit(request, principal=_principal("alice"))
            self.assertTrue(admission.completing.wait(1.0))
            self.assertFalse(service.cancel(submitted.request_id, principal=_principal("alice")))
            completed = _wait_for(
                service,
                submitted.request_id,
                _principal("alice"),
                "complete",
            )

        self.assertFalse(completed.applied)
        self.assertEqual(completed.corrected_text, request.source_text)
        self.assertEqual(completed.reason, "deadline-exceeded")

    def test_invalid_model_output_returns_unchanged_source_without_detail(self) -> None:
        service = _service(
            admission=_Admission(),
            model=_InvalidModel(),
        )
        self.addCleanup(service.close)
        request = _request()
        submitted = service.submit(request, principal=_principal("alice"))

        completed = _wait_for(service, submitted.request_id, _principal("alice"), "complete")
        self.assertFalse(completed.applied)
        self.assertEqual(completed.reason, "invalid-output")
        self.assertEqual(completed.corrected_text, request.source_text)
        self.assertNotIn("private", str(completed.to_wire()))

    def test_valid_no_change_response_is_distinct_from_invalid_output(self) -> None:
        service = _service(
            admission=_Admission(),
            model=_NoChangeModel(),
        )
        self.addCleanup(service.close)
        request = _request()
        submitted = service.submit(request, principal=_principal("alice"))

        completed = _wait_for(
            service,
            submitted.request_id,
            _principal("alice"),
            "complete",
        )
        self.assertFalse(completed.applied)
        self.assertEqual(completed.reason, "unchanged")
        self.assertEqual(completed.corrected_text, request.source_text)

    def test_provider_generation_change_discards_completed_model_output(self) -> None:
        admission = _Admission()
        model = _Model()

        class _ChangingAdmission(_Admission):
            def status(self, ticket):
                result = super().status(ticket)
                if self._outcomes[ticket.request_id] == "admitted":
                    return AgentAdmission(
                        ticket,
                        "admitted",
                        route=ExecutionRoute.RAPID_AUTOMATION,
                        provider_generation=self.generation + 1,
                        queue_duration_ms=0,
                    )
                return result

        admission = _ChangingAdmission()
        service = _service(admission=admission, model=model)
        self.addCleanup(service.close)
        request = _request()
        submitted = service.submit(request, principal=_principal("alice"))

        completed = _wait_for(service, submitted.request_id, _principal("alice"), "complete")
        self.assertFalse(completed.applied)
        self.assertEqual(completed.reason, "provider-changed")
        self.assertEqual(completed.corrected_text, request.source_text)

    def test_close_contains_queued_work_and_rejects_new_submissions(self) -> None:
        admission = _Admission(initially_queued=True)
        service = _service(admission=admission, model=_Model())
        submitted = service.submit(_request(), principal=_principal("alice"))

        service.close()
        closed = service.get(submitted.request_id, principal=_principal("alice"))
        self.assertIsNotNone(closed)
        self.assertEqual(closed.status, "cancelled")
        with self.assertRaisesRegex(RuntimeError, "closed"):
            service.submit(_request(), principal=_principal("alice"))

    def test_close_waits_for_inflight_admission_and_contains_accepted_ticket(self) -> None:
        class _SlowAdmission(_Admission):
            def __init__(self) -> None:
                super().__init__(initially_queued=True)
                self.entered = threading.Event()
                self.release = threading.Event()

            def submit(self, ticket, **kwargs):
                result = super().submit(ticket, **kwargs)
                self.entered.set()
                self.release.wait(2.0)
                return result

        admission = _SlowAdmission()
        service = _service(admission=admission, model=_Model())
        submit_error: list[BaseException] = []
        close_error: list[BaseException] = []

        def submit() -> None:
            try:
                service.submit(_request(), principal=_principal("alice"))
            except BaseException as error:
                submit_error.append(error)

        def close() -> None:
            try:
                service.close()
            except BaseException as error:
                close_error.append(error)

        submit_thread = threading.Thread(target=submit)
        submit_thread.start()
        self.assertTrue(admission.entered.wait(1.0))
        close_thread = threading.Thread(target=close)
        close_thread.start()
        time.sleep(0.05)
        self.assertTrue(close_thread.is_alive())
        admission.release.set()
        submit_thread.join(2.0)
        close_thread.join(2.0)

        self.assertFalse(submit_thread.is_alive())
        self.assertFalse(close_thread.is_alive())
        self.assertEqual(close_error, [])
        self.assertEqual(len(submit_error), 1)
        self.assertIn("closed", str(submit_error[0]))
        operations = [operation for operation, _ in admission.calls]
        self.assertEqual(operations, ["submit", "cancel", "acknowledge-cancellation"])

    def test_uncontained_model_fences_service_and_close_fails(self) -> None:
        class _UncontainedModel:
            def correct(self, request, *, cancellation):
                del request, cancellation
                raise RuntimeError("transport did not stop")

        service = _service(
            admission=_Admission(),
            model=_UncontainedModel(),
        )
        submitted = service.submit(_request(), principal=_principal("alice"))
        _wait_for(service, submitted.request_id, _principal("alice"), "failed")
        with self.assertRaises(TranscriptCorrectionContainmentError):
            service.close()


if __name__ == "__main__":
    unittest.main()
