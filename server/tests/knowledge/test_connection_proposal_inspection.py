import json
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from yap_server.knowledge.knowledge_connections_service import (
    KnowledgeConnectionsError,
    KnowledgeConnectionsService,
)
from yap_server.knowledge.knowledge_proposals import discard_knowledge_proposal
from tests.agents.curator_connections_fixtures import (
    CuratorConnectionFixture,
    DSN,
    connect,
)
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class ConnectionProposalInspectionTests(CuratorConnectionFixture, unittest.TestCase):
    def setUp(self):
        self.prepare_connection_review()
        self.result = self.core.propose(
            self.request, principal=self.principal, cancellation=threading.Event()
        )
        self.reference = self.result.proposal_id
        self.service = KnowledgeConnectionsService(connect)

    def read(self, principal=None, reference=None):
        return self.service.proposal(
            principal=principal or self.principal,
            proposal_id=reference or self.reference,
        )

    def status(self, **kwargs):
        with self.assertRaises(KnowledgeConnectionsError) as error:
            self.read(**kwargs)
        return error.exception.status

    def test_persisted_candidate_and_exact_source_pair_reopen_without_model_or_graph_writes(
        self,
    ):
        before = self.graph_identity(), self.stored_connection_rows()
        wire = self.read()
        self.assertEqual(wire["proposalId"], self.reference)
        self.assertEqual(
            wire["candidate"],
            {
                "schemaVersion": self.candidate["schema_version"],
                "sourceConceptId": self.candidate["source_concept_id"],
                "targetConceptId": self.candidate["target_concept_id"],
                "relationshipType": self.candidate["relationship_type"],
                "rationale": self.candidate["rationale"],
            },
        )
        self.assertEqual(wire["status"], "proposed")
        self.assertEqual(wire["generationSha256"], self.generation.generation_sha256)
        by_source = {item["node"]["conceptId"]: item for item in wire["sources"]}
        self.assertEqual(
            set(by_source),
            {self.candidate["source_concept_id"], self.candidate["target_concept_id"]},
        )
        for citation in self.request.source_citations:
            item = by_source[citation.concept_id]
            concept = next(
                value
                for value in self.generation.concepts
                if value.concept_id == citation.concept_id
            )
            self.assertEqual(
                item["text"], concept.body[citation.char_start : citation.char_end]
            )
            self.assertEqual(item["citation"]["contentSha256"], citation.content_sha256)
            self.assertEqual(item["node"]["sourceRevision"], citation.source_revision)
        self.assertEqual(self.read(), wire)
        self.assertEqual((self.graph_identity(), self.stored_connection_rows()), before)

    def test_foreign_unknown_discarded_and_wrong_type_references_are_indistinguishable(
        self,
    ):
        self.assertEqual(
            self.status(principal=replace(self.principal, subject_id="bob")), 404
        )
        self.assertEqual(self.status(reference="f" * 64), 404)
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposal_type = 'summary' WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(self.status(), 404)
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposal_type = 'relationship' WHERE tenant_id = %s",
                (self.tenant,),
            )
            discard_knowledge_proposal(
                connection, principal=self.principal.key, proposal_id=self.reference
            )
        self.assertEqual(self.status(), 404)

    def test_both_endpoints_are_reauthorized_before_excerpts_are_returned(self):
        with connect() as connection:
            connection.execute(
                "DELETE FROM yap_knowledge_permission_audience WHERE tenant_id = %s AND subject_id = 'alice' AND path_prefix = (SELECT permission_path_prefix FROM yap_knowledge_concepts WHERE tenant_id = %s AND generation_sha256 = %s AND concept_id = 'decisions/public')",
                (self.tenant, self.tenant, self.generation.generation_sha256),
            )
        self.assertEqual(self.status(), 404)
        self.assertEqual(len(self.stored_connection_rows()), 1)

    def test_new_generation_refuses_a_stale_owned_proposal(self):
        with connect() as connection:
            activate_connection_fixture(connection, self.tenant, subject="charlie")
        self.assertEqual(self.status(), 409)
        self.assertEqual(
            self.status(principal=replace(self.principal, subject_id="bob")), 404
        )

    def test_stored_candidate_or_inherited_policy_tampering_refuses_read_and_preserves_rows(
        self,
    ):
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposed_content = %s WHERE tenant_id = %s",
                (
                    json.dumps(
                        {**self.candidate, "rationale": "Changed without acceptance"},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    self.tenant,
                ),
            )
        before = self.stored_connection_rows()
        self.assertEqual(self.status(), 503)
        self.assertEqual(self.stored_connection_rows(), before)
        with connect() as connection:
            connection.execute(
                "UPDATE yap_knowledge_proposals SET proposed_content = %s, inherited_permission_sha256 = %s WHERE tenant_id = %s",
                (
                    json.dumps(self.candidate, sort_keys=True, separators=(",", ":")),
                    "f" * 64,
                    self.tenant,
                ),
            )
        self.assertEqual(self.status(), 503)

    def test_busy_invalid_reference_and_success_audit_failure_never_return_partial_content(
        self,
    ):
        for reference in ["", "../source", "a" * 63, "A" * 64]:
            with self.assertRaises(KnowledgeConnectionsError) as error:
                self.service.proposal(principal=self.principal, proposal_id=reference)
            self.assertEqual(error.exception.status, 400)
        self.service._requests.acquire()
        self.service._requests.acquire()
        try:
            self.assertEqual(self.status(), 429)
        finally:
            self.service._requests.release()
            self.service._requests.release()
        from yap_server.knowledge import knowledge_connections_service as runtime

        real = runtime.record_knowledge_tool_audit

        def fail_success(*args, **kwargs):
            if kwargs["outcome"] == "succeeded":
                raise RuntimeError("private audit failure")
            return real(*args, **kwargs)

        with patch.object(
            runtime, "record_knowledge_tool_audit", side_effect=fail_success
        ):
            self.assertEqual(self.status(), 503)
        self.assertEqual(self.read()["proposalId"], self.reference)

    def test_response_budget_rolls_back_success_audit_and_keeps_saved_proposal(self):
        from yap_server.knowledge import knowledge_connections_service as runtime

        before = self.stored_connection_rows()
        with patch.object(runtime, "MAXIMUM_CONNECTION_RESPONSE_BYTES", 128):
            self.assertEqual(self.status(), 503)
        with connect() as connection:
            outcomes = connection.execute(
                "SELECT outcome FROM yap_knowledge_tool_audit WHERE tenant_id = %s AND operation = 'read-connection-proposal'",
                (self.tenant,),
            ).fetchall()
        self.assertEqual(outcomes, [("failed",)])
        self.assertEqual(self.stored_connection_rows(), before)
        self.assertEqual(self.read()["proposalId"], self.reference)
