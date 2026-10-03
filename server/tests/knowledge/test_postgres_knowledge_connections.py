from __future__ import annotations

import os
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.generation_ledger import (
    install_knowledge_schema,
)
from yap_server.knowledge.knowledge_tool_contract import KnowledgeGenerationStale
from yap_server.knowledge.postgres_relationship_retrieval import (
    read_postgres_knowledge_neighborhood,
)
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture

POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")
CAPABILITIES = frozenset({"knowledge.relationship.traverse"})


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PostgresKnowledgeConnectionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tenant = f"connections-{uuid4().hex}"
        self.principal = PrincipalKey(self.tenant, "alice")
        self.connection = psycopg.connect(POSTGRES_DSN)
        self.addCleanup(self.connection.close)
        self.addCleanup(self._clean_tenant)
        install_knowledge_schema(self.connection)
        self.generation = self._activate()

    def _clean_tenant(self) -> None:
        self.connection.rollback()
        self.connection.execute(
            "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.connection.execute(
            "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s", (self.tenant,)
        )
        self.connection.commit()

    def _activate(self, **kwargs):
        return activate_connection_fixture(self.connection, self.tenant, **kwargs)

    def read(self, concept_id="projects/voiceos", **kwargs):
        return read_postgres_knowledge_neighborhood(
            self.connection,
            principal=kwargs.pop("principal", self.principal),
            purpose=kwargs.pop("purpose", "knowledge.read"),
            agent_capabilities=kwargs.pop("agent_capabilities", CAPABILITIES),
            concept_id=concept_id,
            **kwargs,
        )

    def test_incoming_and_outgoing_edges_retain_exact_source_authority(self) -> None:
        result = self.read()
        self.assertEqual(
            {node.concept_id for node in result.nodes},
            {"projects/voiceos", "decisions/public"},
        )
        self.assertEqual(len(result.relationships), 2)
        self.assertEqual(
            {edge.source_concept_id for edge in result.relationships},
            {"projects/voiceos", "decisions/public"},
        )
        self.assertFalse(result.has_more)
        for edge in result.relationships:
            source = next(
                item
                for item in self.generation.concepts
                if item.concept_id == edge.source_concept_id
            )
            self.assertEqual(edge.source_revision, self.generation.source_revision)
            self.assertEqual(edge.content_sha256, source.content_sha256)
            self.assertEqual(edge.source_path, source.source_path)
            self.assertIn(
                edge.target_concept_id,
                source.body[edge.source_char_start : edge.source_char_end],
            )
            self.assertEqual(edge.authority, "asserted")
            self.assertEqual(edge.generation_sha256, result.generation_sha256)
        self.assertNotIn("secret/", repr(result))
        self.assertNotIn("agent_proposed", repr(result))

    def test_restricted_root_and_unknown_root_are_indistinguishable(self) -> None:
        hidden = self.read("secret/launch")
        unknown = self.read("secret/does-not-exist")
        self.assertEqual(hidden, unknown)
        self.assertEqual(hidden.nodes, ())
        self.assertEqual(hidden.relationships, ())
        self.assertFalse(hidden.has_more)

    def test_subject_purpose_and_agent_capability_are_authority(self) -> None:
        for kwargs in [
            {"principal": PrincipalKey(self.tenant, "bob")},
            {"purpose": "knowledge.write"},
        ]:
            result = self.read(**kwargs)
            self.assertEqual(result.nodes, ())
            self.assertEqual(result.relationships, ())
        with self.assertRaises(PermissionError):
            self.read(agent_capabilities=frozenset({"knowledge.tree"}))
        with self.assertRaises(LookupError):
            self.read(principal=PrincipalKey(f"other-{self.tenant}", "alice"))

    def test_limit_is_applied_after_authorization_without_hidden_counts(self) -> None:
        self._activate(hidden_neighbors=24)
        result = self.read(maximum_results=2)
        self.assertEqual(len(result.relationships), 2)
        self.assertFalse(result.has_more)
        self.assertNotIn("Hidden", repr(result))
        self.assertNotIn("secret/", repr(result))

    def test_high_degree_is_bounded_and_deterministic(self) -> None:
        self._activate(neighbors=24)
        result = self.read()
        self.assertEqual(result, self.read())
        self.assertEqual(len(result.relationships), 16)
        self.assertLessEqual(len(result.nodes), 17)
        self.assertTrue(result.has_more)
        self.assertEqual(
            [edge.relationship_id for edge in result.relationships],
            sorted(edge.relationship_id for edge in result.relationships),
        )
        endpoints = {
            endpoint
            for edge in result.relationships
            for endpoint in (edge.source_concept_id, edge.target_concept_id)
        }
        self.assertEqual(endpoints, {node.concept_id for node in result.nodes})

    def test_revocation_cannot_reuse_a_previous_generation(self) -> None:
        before = self.read()
        self._activate(subject="charlie")
        with self.assertRaises(KnowledgeGenerationStale):
            self.read(expected_generation_sha256=before.generation_sha256)
        after = self.read()
        self.assertEqual(after.nodes, ())
        self.assertEqual(after.relationships, ())
        self.assertNotEqual(before.permission_hash, after.permission_hash)

    def test_isolated_visible_node_does_not_require_an_edge(self) -> None:
        with self.connection.transaction():
            self.connection.execute(
                "DELETE FROM yap_knowledge_relationships WHERE tenant_id = %s",
                (self.tenant,),
            )
        result = self.read()
        self.assertEqual(
            tuple(node.concept_id for node in result.nodes), ("projects/voiceos",)
        )
        self.assertEqual(result.relationships, ())
        self.assertFalse(result.has_more)

    def test_invalid_bounds_are_refused(self) -> None:
        for value in [0, -1, 17, True]:
            with self.assertRaises(ValueError):
                self.read(maximum_results=value)
        with self.assertRaises(ValueError):
            self.read(concept_id="x" * 513)
        with self.assertRaises(ValueError):
            self.read(expected_generation_sha256="not-a-generation")


if __name__ == "__main__":
    unittest.main()
