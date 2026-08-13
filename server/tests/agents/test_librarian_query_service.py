from __future__ import annotations

import hashlib
import threading
import time
import unittest

from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
    LibrarianRequest,
)
from yap_server.agents.librarian_query_service import (
    LibrarianQueryContainmentError,
    LibrarianQueryService,
)
from yap_server.agents.librarian_service import (
    LibrarianContainmentError,
    LibrarianJobView,
)
from yap_server.auth import AuthenticatedPrincipal


def _principal(subject: str = "alice") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id="tenant-a",
        subject_id=subject,
        client_id="desktop",
        scopes=frozenset(),
    )


def _request() -> LibrarianRequest:
    return LibrarianRequest(
        search_text="reviewed launch decision",
        maximum_results=3,
        expected_generation_sha256="a" * 64,
    )


def _evidence() -> LibrarianEvidencePack:
    text = "The reviewed launch decision requires approval."
    item = LibrarianEvidenceItem(
        concept_id="meetings/launch-review",
        source_revision="revision-1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        char_start=0,
        char_end=len(text),
        text=text,
    )
    return LibrarianEvidencePack.create(
        generation_sha256="a" * 64,
        permission_hash="b" * 64,
        authorization_hash="c" * 64,
        items=(item,),
        output_budget_exhausted=False,
    )


class _ControlledLibrarian:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[LibrarianRequest, AuthenticatedPrincipal]] = []
        self.result = LibrarianJobView(
            request_id="internal-librarian-1",
            status="complete",
            evidence=_evidence(),
        )
        self.error: BaseException | None = None

    def query(self, request, *, principal, cancellation):
        self.calls.append((request, principal))
        self.started.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return LibrarianJobView(
                    request_id="internal-librarian-1",
                    status="cancelled",
                    reason="client-cancelled",
                )
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            return LibrarianJobView(
                request_id="internal-librarian-1",
                status="cancelled",
                reason="client-cancelled",
            )
        return self.result


def _wait_for_terminal(
    service: LibrarianQueryService,
    request_id: str,
    principal: AuthenticatedPrincipal,
):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        view = service.get(request_id, principal=principal)
        if view is not None and view.status not in {
            "queued",
            "running",
            "cancellation-requested",
        }:
            return view
        time.sleep(0.01)
    raise AssertionError("librarian product query did not finish")


class LibrarianQueryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = _ControlledLibrarian()
        self.service = LibrarianQueryService(librarian=self.inner)

    def tearDown(self) -> None:
        self.inner.release.set()
        self.service.close()

    def test_submit_returns_product_identity_and_projects_safe_terminal_pack(
        self,
    ) -> None:
        initial = self.service.submit(_request(), principal=_principal())

        self.assertEqual(initial.status, "queued")
        self.assertRegex(initial.request_id, r"^librarian-query-[0-9a-f]{32}$")
        self.assertNotEqual(initial.request_id, "internal-librarian-1")
        self.assertEqual(
            initial.to_wire(),
            {
                "schemaVersion": 1,
                "requestId": initial.request_id,
                "status": "queued",
            },
        )
        self.assertTrue(self.inner.started.wait(1))
        self.inner.release.set()

        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "complete")
        self.assertEqual(terminal.evidence, _evidence())
        self.assertEqual(
            terminal.to_wire()["evidencePack"],
            _evidence().to_wire(),
        )
        self.assertEqual(self.inner.calls, [(_request(), _principal())])

    def test_status_and_cancel_are_owner_scoped_and_cancel_is_terminal(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())
        self.assertTrue(self.inner.started.wait(1))

        self.assertIsNone(
            self.service.get(initial.request_id, principal=_principal("bob"))
        )
        self.assertFalse(
            self.service.cancel(initial.request_id, principal=_principal("bob"))
        )
        self.assertTrue(self.service.cancel(initial.request_id, principal=_principal()))
        requested = self.service.get(initial.request_id, principal=_principal())
        self.assertIsNotNone(requested)
        self.assertEqual(requested.status, "cancellation-requested")

        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "cancelled")
        self.assertEqual(terminal.reason, "client-cancelled")
        self.assertIsNone(terminal.evidence)
        self.assertFalse(
            self.service.cancel(initial.request_id, principal=_principal())
        )

    def test_evidence_unavailable_remains_typed_without_pack(self) -> None:
        self.inner.result = LibrarianJobView(
            request_id="internal-librarian-1",
            status="evidence-unavailable",
            reason="empty-result",
        )
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "evidence-unavailable")
        self.assertEqual(terminal.reason, "empty-result")
        self.assertNotIn("evidencePack", terminal.to_wire())

    def test_inner_containment_failure_fences_future_product_queries(self) -> None:
        self.inner.error = LibrarianContainmentError("worker escaped")
        initial = self.service.submit(_request(), principal=_principal())
        self.inner.release.set()

        terminal = _wait_for_terminal(
            self.service,
            initial.request_id,
            _principal(),
        )
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.reason, "service-unavailable")
        with self.assertRaises(LibrarianQueryContainmentError):
            self.service.submit(_request(), principal=_principal())
        with self.assertRaises(LibrarianQueryContainmentError):
            self.service.close()

        self.service = LibrarianQueryService(librarian=_ControlledLibrarian())

    def test_close_requests_cancellation_and_contains_worker(self) -> None:
        initial = self.service.submit(_request(), principal=_principal())
        self.assertTrue(self.inner.started.wait(1))

        self.service.close()

        terminal = self.service.get(initial.request_id, principal=_principal())
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal.status, "cancelled")
        self.assertEqual(terminal.reason, "client-cancelled")
        with self.assertRaises(LibrarianQueryContainmentError):
            self.service.submit(_request(), principal=_principal())


if __name__ == "__main__":
    unittest.main()
