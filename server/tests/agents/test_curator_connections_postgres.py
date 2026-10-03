import json
import threading
import time
import unittest
from dataclasses import replace

from yap_server.agents.curator_publisher import PostgresCuratorPublisher
from yap_server.agents.curator_service import CuratorServiceError
from yap_server.agents.librarian import (
    LibrarianRequest,
    PostgresLibrarianEvidenceReader,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancelled,
    ProposalCitation,
)
from tests.agents.curator_connections_fixtures import (
    CuratorConnectionFixture,
    DSN,
    connect,
)
from tests.agents.test_curator import _tool_response
from tests.agents.test_curator_postgres import _FailingAuditor, _runtime_identity
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class CuratorConnectionPostgresTests(CuratorConnectionFixture, unittest.TestCase):
    def setUp(self):
        self.prepare_connection_review()

    def test_actual_librarian_excerpts_round_trip_without_rewriting_source_proof(self):
        pack = PostgresLibrarianEvidenceReader(connect).read(
            LibrarianRequest("Decision", 3, self.generation.generation_sha256),
            principal=self.principal,
            cancellation=threading.Event(),
        )
        selected = tuple(
            next(item for item in pack.items if item.concept_id == concept_id)
            for concept_id in ("projects/voiceos", "decisions/public")
        )
        request = replace(
            self.request,
            source_citations=tuple(
                ProposalCitation(
                    concept_id=item.concept_id,
                    source_revision=item.source_revision,
                    content_sha256=item.content_sha256,
                    char_start=item.char_start,
                    char_end=item.char_end,
                )
                for item in selected
            ),
        )
        evidence = self.reader.read(
            request, principal=self.principal, cancellation=threading.Event()
        )
        self.assertEqual(
            {item.citation.concept_id: item.text for item in evidence.items},
            {item.concept_id: item.text for item in selected},
        )
        before = self.graph_identity()
        result = self.core.propose(
            request, principal=self.principal, cancellation=threading.Event()
        )
        self.assertEqual(result.status, "proposed")
        self.assertEqual(
            self.stored_connection_rows()[0][2],
            [citation.model_dump(mode="json") for citation in request.source_citations],
        )
        self.assertEqual(self.graph_identity(), before)

    def test_full_review_persists_a_relationship_atomically_and_replays_without_graph_mutation(
        self,
    ):
        before = self.graph_identity()
        result = self.core.propose(
            self.request, principal=self.principal, cancellation=threading.Event()
        )
        self.assertEqual(result.status, "proposed")
        row = self.stored_connection_rows()[0]
        self.assertEqual(
            row,
            (
                "relationship",
                self.request.reviewed_content,
                [
                    item.model_dump(mode="json")
                    for item in self.request.source_citations
                ],
                "proposed",
            ),
        )
        self.assertEqual(self.graph_identity(), before)
        replay = self.core.propose(
            replace(
                self.request,
                reviewed_content=json.dumps(self.candidate, indent=2),
                source_citations=self.request.source_citations[::-1],
            ),
            principal=self.principal,
            cancellation=threading.Event(),
        )
        self.assertEqual(replay, result)
        self.assertEqual(len(self.transport.payloads), 1)
        restarted = self.auditor.read(
            principal=self.principal, submission_id=self.request.submission_id
        )
        self.assertEqual(restarted.proposal_id, result.proposal_id)
        other = AuthenticatedPrincipal(
            self.tenant, "bob", "desktop", frozenset({"access_as_user"})
        )
        self.assertIsNone(
            self.auditor.read(principal=other, submission_id=self.request.submission_id)
        )
        changed = {**self.candidate, "rationale": "Different reviewed intent."}
        with self.assertRaises(CuratorServiceError):
            self.core.propose(
                replace(self.request, reviewed_content=json.dumps(changed)),
                principal=self.principal,
                cancellation=threading.Event(),
            )
        with connect() as connection:
            audits = connection.execute(
                "SELECT operation, outcome FROM yap_knowledge_tool_audit WHERE tenant_id = %s ORDER BY audit_id",
                (self.tenant,),
            ).fetchall()
        self.assertEqual(
            audits,
            [("reviewed-source-evidence", "succeeded"), ("propose", "succeeded")],
        )

    def test_hidden_or_changed_source_cannot_be_reviewed_or_published(self):
        hidden = self.core.propose(
            self.hidden_request(),
            principal=self.principal,
            cancellation=threading.Event(),
        )
        self.assertEqual(hidden.status, "failed")
        self.assertEqual(self.transport.payloads, [])
        self.assertEqual(self.stored_connection_rows(), [])
        evidence = self.frozen_evidence()
        for field, value in [
            ("source_revision", "stale-review"),
            ("content_sha256", "f" * 64),
            ("char_end", self.request.source_citations[0].char_end + 1),
        ]:
            citation = self.request.source_citations[0].model_copy(
                update={field: value}
            )
            changed = replace(
                self.request,
                source_citations=(citation, self.request.source_citations[1]),
            )
            with (
                self.subTest(field=field),
                self.assertRaises((LookupError, ValueError)),
            ):
                self.reader.read(
                    changed, principal=self.principal, cancellation=threading.Event()
                )
        with connect() as connection:
            activate_connection_fixture(connection, self.tenant, subject="charlie")
        with self.assertRaises(ValueError):
            self.publisher.publish(
                principal=self.principal,
                request_id="revoked-connection",
                request=self.request,
                evidence=evidence,
                provider_generation=9,
                started=time.monotonic(),
                deadline=time.monotonic() + 10,
                cancellation=threading.Event(),
            )
        self.assertEqual(self.stored_connection_rows(), [])

    def test_audit_failure_and_cancellation_leave_no_proposal_or_success_audit(self):
        evidence = self.frozen_evidence()
        failing = PostgresCuratorPublisher(
            connect, _FailingAuditor(connect, _runtime_identity())
        )
        arguments = dict(
            principal=self.principal,
            request_id="failed-connection",
            request=self.request,
            evidence=evidence,
            provider_generation=9,
            started=time.monotonic(),
            deadline=time.monotonic() + 10,
        )
        with self.assertRaisesRegex(RuntimeError, "injected audit failure"):
            failing.publish(**arguments, cancellation=threading.Event())
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(KnowledgeToolCancelled):
            self.publisher.publish(**arguments, cancellation=cancelled)
        self.assertEqual(self.stored_connection_rows(), [])
        with connect() as connection:
            proposals = connection.execute(
                "SELECT count(*) FROM yap_knowledge_tool_audit WHERE tenant_id = %s AND operation = 'propose' AND outcome = 'succeeded'",
                (self.tenant,),
            ).fetchone()[0]
            results = connection.execute(
                "SELECT count(*) FROM yap_curator_result_audit WHERE tenant_id = %s",
                (self.tenant,),
            ).fetchone()[0]
        self.assertEqual((proposals, results), (0, 0))

    def test_rejected_review_retains_source_bound_result_without_a_candidate(self):
        self.transport.response = _tool_response("reject")
        before = self.graph_identity()
        result = self.core.propose(
            self.request, principal=self.principal, cancellation=threading.Event()
        )
        self.assertEqual(
            (result.status, result.reason, result.proposal_id),
            ("rejected", "model-rejected", None),
        )
        self.assertEqual(self.stored_connection_rows(), [])
        self.assertEqual(self.graph_identity(), before)
        self.assertEqual(
            self.auditor.read(
                principal=self.principal, submission_id=self.request.submission_id
            ).status,
            "rejected",
        )
