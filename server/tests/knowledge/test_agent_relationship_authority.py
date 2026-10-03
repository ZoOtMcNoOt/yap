from dataclasses import asdict, replace
import os
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.governed_knowledge_tools import (
    GovernedKnowledgeTools,
    _bounded_items,
)
from yap_server.knowledge.knowledge_agent_authority import KnowledgeAgentAuthority
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeAgentProfile,
    KnowledgeToolCitation,
    KnowledgeToolItem,
    TraverseKnowledgeRequest,
)
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture


def item(authority="human_confirmed"):
    return KnowledgeToolItem(
        citation=KnowledgeToolCitation(
            "projects/yap", "reviewed-1", "a" * 64, None, None
        ),
        text=None,
        relationship_type="supports",
        target_concept_id="decisions/interface",
        relationship_authority=authority,
    )


class AgentRelationshipAuthorityTests(unittest.TestCase):
    def test_typed_links_require_source_authority_and_proposals_cannot_be_facts(self):
        for authority in ("asserted", "human_confirmed", "derived"):
            self.assertEqual(
                asdict(item(authority))["relationship_authority"], authority
            )
        for authority in (None, "agent_proposed", "unknown"):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                item(authority)
        for changed in (
            {"target_concept_id": None},
            {"relationship_type": None},
            {"text": "Uncited source assertion"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                replace(item(), **changed)

    def test_text_evidence_cannot_silently_acquire_an_edge_authority(self):
        text = KnowledgeToolItem(
            KnowledgeToolCitation("projects/yap", "reviewed-1", "a" * 64, 0, 4),
            "Yap.",
            None,
            None,
            None,
        )
        self.assertIsNone(asdict(text)["relationship_authority"])
        with self.assertRaises(ValueError):
            replace(text, relationship_authority="derived")

    def test_output_budget_retains_or_excludes_the_complete_edge_proof(self):
        edge = item()
        previous_cost = sum(
            len(value)
            for value in (
                edge.citation.concept_id,
                edge.citation.source_revision,
                edge.citation.content_sha256,
                edge.relationship_type,
                edge.target_concept_id,
            )
        )
        self.assertEqual(_bounded_items((edge,), previous_cost), ((), True))
        self.assertEqual(
            _bounded_items((edge,), previous_cost + len(edge.relationship_authority)),
            ((edge,), False),
        )


DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class AgentRelationshipAuthorityPostgresTests(unittest.TestCase):
    def setUp(self):
        self.tenant = f"agent-authority-{uuid4().hex}"
        self.connection = psycopg.connect(DSN)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.clean)
        install_knowledge_schema(self.connection)
        install_knowledge_tool_audit_schema(self.connection)
        self.generation = activate_connection_fixture(
            self.connection, self.tenant, reviewed_authorities=True
        )
        self.tools = GovernedKnowledgeTools(
            KnowledgeAgentAuthority(
                (
                    KnowledgeAgentProfile(
                        agent_id="curator",
                        capabilities=frozenset({"knowledge.relationship.traverse"}),
                        purposes=frozenset({"knowledge.read"}),
                        maximum_results=16,
                        maximum_output_characters=10000,
                        statement_timeout_milliseconds=5000,
                    ),
                )
            )
        )

    def clean(self):
        self.connection.rollback()
        for table in (
            "yap_knowledge_active_builds",
            "yap_knowledge_builds",
            "yap_knowledge_tool_audit",
        ):
            self.connection.execute(
                f"DELETE FROM {table} WHERE tenant_id = %s", (self.tenant,)
            )
        self.connection.commit()

    def query(self, concept, subject="alice"):
        return self.tools.execute(
            self.connection,
            principal=PrincipalKey(self.tenant, subject),
            agent_id="curator",
            request=TraverseKnowledgeRequest(
                purpose="knowledge.read",
                start_concept_id=concept,
                maximum_depth=1,
                expected_generation_sha256=self.generation.generation_sha256,
            ),
            cancellation=threading.Event(),
        )

    def test_real_compiled_authority_and_citations_survive_the_agent_wire_projection(
        self,
    ):
        responses = [
            self.query(concept) for concept in ("projects/voiceos", "decisions/public")
        ]
        projected = [
            value for response in responses for value in asdict(response)["items"]
        ]
        self.assertEqual(
            {value["relationship_authority"] for value in projected},
            {"asserted", "human_confirmed", "derived"},
        )
        for value in projected:
            citation = value["citation"]
            concept = next(
                concept
                for concept in self.generation.concepts
                if concept.concept_id == citation["concept_id"]
            )
            self.assertEqual(
                citation["source_revision"], self.generation.source_revision
            )
            self.assertEqual(citation["content_sha256"], concept.content_sha256)
        self.assertNotIn("agent_proposed", repr(projected))
        self.assertNotIn("secret/", repr(projected))

    def test_another_principal_cannot_obtain_relation_authority_or_source_proof(self):
        response = self.query("projects/voiceos", subject="bob")
        self.assertEqual(response.items, ())
        self.assertNotIn("voiceos", repr(asdict(response)))
