import json
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from yap_server.knowledge import knowledge_connections_service as runtime
from yap_server.knowledge.knowledge_proposals import store_knowledge_proposal
from tests.agents.curator_connections_fixtures import CuratorConnectionFixture, DSN, connect
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class ConnectionProposalDiscardTests(CuratorConnectionFixture, unittest.TestCase):
    def setUp(self):
        self.prepare_connection_review()
        self.reference = self.core.propose(
            self.request, principal=self.principal, cancellation=threading.Event()
        ).proposal_id
        self.service = runtime.KnowledgeConnectionsService(connect)

    def discard(self, principal=None, reference=None):
        return self.service.discard(
            principal=principal or self.principal,
            proposal_id=reference or self.reference,
        )

    def failure(self, status, **kwargs):
        with self.assertRaises(runtime.KnowledgeConnectionsError) as caught:
            self.discard(**kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception.code, caught.exception.message

    def audit(self):
        with connect() as connection:
            return connection.execute(
                "SELECT outcome, result_count, generation_sha256, permission_hash, authorization_hash "
                "FROM yap_knowledge_tool_audit WHERE tenant_id = %s "
                "AND operation = 'discard-connection-proposal' ORDER BY audit_id",
                (self.tenant,),
            ).fetchall()

    def test_idempotent_discard_retains_sources_provenance_timestamp_and_graph(self):
        graph, rows = self.graph_identity(), self.stored_connection_rows()
        first = self.discard()
        self.assertEqual(first, {
            "schemaVersion": 1, "proposalId": self.reference,
            "generationSha256": self.generation.generation_sha256, "status": "discarded",
        })
        with connect() as connection:
            timestamp = connection.execute(
                "SELECT discarded_at FROM yap_knowledge_proposals WHERE tenant_id = %s",
                (self.tenant,),
            ).fetchone()
        self.assertIsNotNone(timestamp[0])
        self.assertEqual(self.discard(), first)
        with connect() as connection:
            self.assertEqual(connection.execute(
                "SELECT discarded_at FROM yap_knowledge_proposals WHERE tenant_id = %s",
                (self.tenant,),
            ).fetchone(), timestamp)
        self.assertEqual(self.graph_identity(), graph)
        self.assertEqual(self.stored_connection_rows(), [(*rows[0][:3], "discarded")])
        self.assertEqual(self.audit(), [
            ("succeeded", 1, self.generation.generation_sha256, None, None),
        ] * 2)
        with self.assertRaises(runtime.KnowledgeConnectionsError) as caught:
            self.service.proposal(principal=self.principal, proposal_id=self.reference)
        self.assertEqual(caught.exception.status, 404)

    def test_unknown_foreign_tenant_owner_and_wrong_type_share_unavailable(self):
        before = self.stored_connection_rows()
        expected = self.failure(404, reference="f" * 64)
        for principal in [replace(self.principal, subject_id="bob"),
                          replace(self.principal, tenant_id="other-tenant")]:
            self.assertEqual(self.failure(404, principal=principal), expected)
        self.assertEqual(self.stored_connection_rows(), before)
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposal_type = 'summary' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(self.failure(404), expected)
        self.assertEqual(self.stored_connection_rows()[0][3], "proposed")
        self.assertTrue(all(row[0] == "failed" for row in self.audit()))

    def test_hidden_or_stale_owned_sources_can_be_retired_without_reading_them(self):
        with connect() as connection:
            activate_connection_fixture(connection, self.tenant, subject="charlie")
            connection.execute(
                "DELETE FROM yap_knowledge_permission_audience WHERE tenant_id = %s AND subject_id = 'alice'",
                (self.tenant,),
            )
        before = self.graph_identity()
        with self.assertRaises(runtime.KnowledgeConnectionsError):
            self.service.proposal(principal=self.principal, proposal_id=self.reference)
        self.assertEqual(self.discard()["status"], "discarded")
        self.assertEqual(self.graph_identity(), before)

    def test_success_audit_failure_rolls_back_discard_and_retry_uses_released_slot(self):
        real = runtime.record_knowledge_tool_audit
        def fail_success(*args, **kwargs):
            if kwargs["outcome"] == "succeeded":
                raise RuntimeError("private audit failure")
            return real(*args, **kwargs)
        before = self.stored_connection_rows()
        with patch.object(runtime, "record_knowledge_tool_audit", side_effect=fail_success):
            self.failure(503)
        self.assertEqual(self.stored_connection_rows(), before)
        self.assertEqual(self.audit(), [("failed", 0, None, None, None)])
        self.assertEqual(self.discard()["status"], "discarded")

    def test_busy_and_invalid_requests_do_not_change_the_journal(self):
        before = self.stored_connection_rows()
        for value in ["../source", "a" * 63, "A" * 64]:
            self.failure(400, reference=value)
        self.service._requests.acquire()
        self.service._requests.acquire()
        try:
            self.failure(429)
        finally:
            self.service._requests.release()
            self.service._requests.release()
        self.assertEqual(self.stored_connection_rows(), before)
        self.assertEqual(self.audit(), [])

    def test_discard_releases_full_owner_capacity_without_resurrecting_old_truth(self):
        def propose(index):
            with connect() as connection:
                return store_knowledge_proposal(
                    connection, principal=self.principal.key, purpose="knowledge.read",
                    agent_id="curator", agent_capabilities=frozenset({"knowledge.propose"}),
                    proposal_type="relationship",
                    proposed_content=json.dumps({**self.candidate, "rationale": f"Reviewed connection {index}."}),
                    source_citations=self.request.source_citations,
                    expected_generation_sha256=self.generation.generation_sha256,
                )
        for index in range(63):
            propose(index)
        with self.assertRaisesRegex(RuntimeError, "capacity"):
            propose(63)
        self.discard()
        self.assertIsNotNone(propose(63).proposal_id)
        with connect() as connection:
            unresolved = connection.execute(
                "SELECT count(*) FROM yap_knowledge_proposals WHERE tenant_id = %s AND status = 'proposed'",
                (self.tenant,),
            ).fetchone()[0]
        self.assertEqual(unresolved, 64)
        self.assertEqual(self.discard()["status"], "discarded")
        with self.assertRaisesRegex(ValueError, "conflicts with stored truth"):
            with connect() as connection:
                store_knowledge_proposal(
                    connection, principal=self.principal.key, purpose="knowledge.read",
                    agent_id="curator", agent_capabilities=frozenset({"knowledge.propose"}),
                    proposal_type="relationship", proposed_content=json.dumps(self.candidate),
                    source_citations=self.request.source_citations,
                    expected_generation_sha256=self.generation.generation_sha256,
                )
