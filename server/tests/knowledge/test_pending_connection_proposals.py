import json
import threading
import unittest
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch

from yap_server.knowledge import knowledge_connections_service as runtime
from yap_server.knowledge.knowledge_proposals import store_knowledge_proposal
from tests.agents.curator_connections_fixtures import (
    CuratorConnectionFixture,
    DSN,
    connect,
)
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PendingConnectionProposalTests(CuratorConnectionFixture, unittest.TestCase):
    def setUp(self):
        self.prepare_connection_review()
        self.reference = self.core.propose(
            self.request, principal=self.principal, cancellation=threading.Event()
        ).proposal_id
        self.service = runtime.KnowledgeConnectionsService(connect)

    def pending(self, principal=None):
        return self.service.pending(principal=principal or self.principal)

    def audit(self):
        with connect() as connection:
            return connection.execute(
                "SELECT outcome, result_count, generation_sha256, permission_hash, authorization_hash "
                "FROM yap_knowledge_tool_audit WHERE tenant_id = %s "
                "AND operation = 'list-connection-proposals' ORDER BY audit_id",
                (self.tenant,),
            ).fetchall()

    def fail(self, status):
        with self.assertRaises(runtime.KnowledgeConnectionsError) as caught:
            self.pending()
        self.assertEqual(caught.exception.status, status)
        self.assertNotIn(self.reference, caught.exception.message)

    def test_owned_metadata_is_complete_utc_content_free_and_read_only(self):
        before, graph = self.stored_connection_rows(), self.graph_identity()
        result = self.pending()
        self.assertEqual(set(result), {"schemaVersion", "proposals"})
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(len(result["proposals"]), 1)
        entry = result["proposals"][0]
        self.assertEqual(set(entry), {"proposalId", "createdAtUtc"})
        self.assertEqual(entry["proposalId"], self.reference)
        self.assertTrue(entry["createdAtUtc"].endswith("Z"))
        self.assertIsNotNone(datetime.fromisoformat(entry["createdAtUtc"]).utcoffset())
        self.assertEqual(self.pending(), result)
        self.assertEqual(self.stored_connection_rows(), before)
        self.assertEqual(self.graph_identity(), graph)
        self.assertEqual(self.audit(), [("succeeded", 1, None, None, None)] * 2)

    def test_foreign_owners_other_types_and_discarded_rows_do_not_appear(self):
        empty = {"schemaVersion": 1, "proposals": []}
        for principal in [
            replace(self.principal, subject_id="bob"),
            replace(self.principal, tenant_id="other-tenant"),
        ]:
            self.assertEqual(self.pending(principal), empty)
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposal_type = 'summary' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(self.pending(), empty)
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposal_type = 'relationship' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.service.discard(principal=self.principal, proposal_id=self.reference)
        self.assertEqual(self.pending(), empty)

    def test_hidden_stale_owned_metadata_does_not_grant_source_access(self):
        with connect() as connection:
            activate_connection_fixture(connection, self.tenant, subject="charlie")
            connection.execute(
                "DELETE FROM yap_knowledge_permission_audience WHERE tenant_id = %s AND subject_id = 'alice'",
                (self.tenant,),
            )
        before = self.stored_connection_rows(), self.graph_identity()
        self.assertEqual(self.pending()["proposals"][0]["proposalId"], self.reference)
        with self.assertRaises(runtime.KnowledgeConnectionsError):
            self.service.proposal(principal=self.principal, proposal_id=self.reference)
        self.assertEqual((self.stored_connection_rows(), self.graph_identity()), before)
        self.service.discard(principal=self.principal, proposal_id=self.reference)
        self.assertEqual(self.pending()["proposals"], [])

    def test_newest_first_and_reference_ties_are_stable(self):
        with connect() as connection:
            second = store_knowledge_proposal(
                connection,
                principal=self.principal.key,
                purpose="knowledge.read",
                agent_id="curator",
                agent_capabilities=frozenset({"knowledge.propose"}),
                proposal_type="relationship",
                proposed_content=json.dumps(
                    {**self.candidate, "rationale": "Another reviewed connection."}
                ),
                source_citations=self.request.source_citations,
                expected_generation_sha256=self.generation.generation_sha256,
            ).proposal_id
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET created_at = '2026-10-03T00:00:00Z' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(
            [entry["proposalId"] for entry in self.pending()["proposals"]],
            sorted([self.reference, second]),
        )
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET created_at = '2026-10-04T00:00:00Z' "
                "WHERE tenant_id = %s AND proposal_id = %s",
                (self.tenant, second),
            )
        self.assertEqual(
            [entry["proposalId"] for entry in self.pending()["proposals"]],
            [second, self.reference],
        )

    def test_invalid_metadata_refuses_the_whole_list_without_a_success_audit(self):
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposal_id = 'corrupt-reference' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.fail(503)
        self.assertEqual(self.audit(), [("failed", 0, None, None, None)])

    def test_excess_capacity_refuses_partial_truth_and_releases_admission(self):
        # Inject an invalid capacity state into this isolated journal; public
        # creation correctly refuses the 65th row, so cannot construct this case.
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO yap_knowledge_proposals
                       (tenant_id, proposal_id, generation_sha256, proposer_subject_id,
                        proposer_agent_id, proposal_type, proposed_content, source_citations,
                        inherited_policy, inherited_permission_sha256, status)
                       SELECT tenant_id, %s, generation_sha256, proposer_subject_id,
                              proposer_agent_id, proposal_type, proposed_content, source_citations,
                              inherited_policy, inherited_permission_sha256, status
                       FROM yap_knowledge_proposals WHERE tenant_id = %s AND proposal_id = %s""",
                    [
                        (f"{index:064x}", self.tenant, self.reference)
                        for index in range(64)
                    ],
                )
        self.fail(503)
        self.assertEqual(self.audit(), [("failed", 0, None, None, None)])
        with connect() as connection:
            connection.execute(
                "DELETE FROM yap_knowledge_proposals WHERE tenant_id = %s AND proposal_id <> %s",
                (self.tenant, self.reference),
            )
        self.assertEqual(len(self.pending()["proposals"]), 1)

    def test_infinite_journal_timestamp_refuses_the_whole_list(self):
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET created_at = 'infinity' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.fail(503)
        self.assertEqual(self.audit(), [("failed", 0, None, None, None)])

    def test_audit_failure_and_busy_admission_never_mutate_the_journal(self):
        before = self.stored_connection_rows(), self.graph_identity()
        self.service._requests.acquire()
        self.service._requests.acquire()
        try:
            self.fail(429)
        finally:
            self.service._requests.release()
            self.service._requests.release()
        self.assertEqual(self.audit(), [])
        real = runtime.record_knowledge_tool_audit

        def fail_success(*args, **kwargs):
            if kwargs["outcome"] == "succeeded":
                raise RuntimeError("private audit failure")
            return real(*args, **kwargs)

        with patch.object(
            runtime, "record_knowledge_tool_audit", side_effect=fail_success
        ):
            self.fail(503)
        self.assertEqual(self.audit(), [("failed", 0, None, None, None)])
        self.assertEqual((self.stored_connection_rows(), self.graph_identity()), before)
        self.assertEqual(len(self.pending()["proposals"]), 1)
