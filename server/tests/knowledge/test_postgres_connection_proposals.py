import json
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import anyio
from mcp import Client
import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.governed_knowledge_mcp import (
    create_governed_knowledge_mcp_server,
)
from yap_server.knowledge.governed_knowledge_proposals import GovernedKnowledgeProposals
from yap_server.knowledge.governed_knowledge_tools import GovernedKnowledgeTools
from yap_server.knowledge.knowledge_agent_authority import KnowledgeAgentAuthority
from yap_server.knowledge.knowledge_proposals import discard_knowledge_proposal
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
    record_knowledge_tool_audit,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeAgentProfile,
    KnowledgeGenerationStale,
    KnowledgeToolCancelled,
    ProposalCitation,
)
from yap_server.knowledge.postgres_relationship_retrieval import (
    read_postgres_knowledge_neighborhood,
)
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture


DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PostgresConnectionProposalTests(unittest.TestCase):
    def setUp(self):
        self.tenant = f"connection-proposal-{uuid4().hex}"
        self.principal = PrincipalKey(self.tenant, "alice")
        self.connection = psycopg.connect(DSN)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.clean)
        install_knowledge_schema(self.connection)
        install_knowledge_tool_audit_schema(self.connection)
        self.generation = activate_connection_fixture(self.connection, self.tenant)
        self.authority = KnowledgeAgentAuthority(
            (
                KnowledgeAgentProfile(
                    agent_id="curator",
                    capabilities=frozenset({"knowledge.propose"}),
                    purposes=frozenset({"knowledge.read"}),
                    maximum_results=16,
                    maximum_output_characters=10000,
                    statement_timeout_milliseconds=5000,
                ),
                KnowledgeAgentProfile(
                    agent_id="librarian",
                    capabilities=frozenset({"knowledge.relationship.traverse"}),
                    purposes=frozenset({"knowledge.read"}),
                    maximum_results=16,
                    maximum_output_characters=10000,
                    statement_timeout_milliseconds=5000,
                ),
            )
        )
        self.proposals = GovernedKnowledgeProposals(self.authority)
        self.candidate = {
            "schema_version": 1,
            "source_concept_id": "projects/voiceos",
            "target_concept_id": "decisions/public",
            "relationship_type": "supports",
            "rationale": "The reviewed project and decision describe related work.",
        }
        self.citations = tuple(
            self.citation(value) for value in ("projects/voiceos", "decisions/public")
        )

    def clean(self):
        self.connection.rollback()
        for table in (
            "yap_knowledge_active_builds",
            "yap_knowledge_builds",
            "yap_knowledge_activation_history",
            "yap_knowledge_source_admissions",
            "yap_knowledge_tool_audit",
        ):
            self.connection.execute(
                f"DELETE FROM {table} WHERE tenant_id = %s", (self.tenant,)
            )
        self.connection.commit()

    def citation(self, concept_id):
        concept = next(
            value
            for value in self.generation.concepts
            if value.concept_id == concept_id
        )
        return ProposalCitation(
            concept_id=concept_id,
            source_revision=self.generation.source_revision,
            content_sha256=concept.content_sha256,
            char_start=0,
            char_end=min(12, len(concept.body)),
        )

    def propose(self, **changes):
        arguments = {
            "principal": self.principal,
            "agent_id": "curator",
            "purpose": "knowledge.read",
            "proposal_type": "relationship",
            "proposed_content": json.dumps(self.candidate),
            "source_citations": self.citations,
            "expected_generation_sha256": self.generation.generation_sha256,
            "cancellation": threading.Event(),
            **changes,
        }
        return self.proposals.propose(self.connection, **arguments)

    def stored(self):
        with psycopg.connect(DSN) as connection:
            return connection.execute(
                "SELECT proposal_id, proposed_content, source_citations, inherited_policy, status "
                "FROM yap_knowledge_proposals WHERE tenant_id = %s ORDER BY proposal_id",
                (self.tenant,),
            ).fetchall()

    def graph(self):
        result = read_postgres_knowledge_neighborhood(
            self.connection,
            principal=self.principal,
            purpose="knowledge.read",
            agent_capabilities=frozenset({"knowledge.relationship.traverse"}),
            concept_id="projects/voiceos",
            expected_generation_sha256=self.generation.generation_sha256,
        )
        self.connection.commit()
        return result

    def test_persist_restart_and_equivalent_replay_never_create_canonical_edges(self):
        graph = self.graph()
        proposal = self.propose()
        replay = self.propose(
            proposed_content=json.dumps(
                dict(reversed(list(self.candidate.items()))), indent=2
            ),
            source_citations=tuple(reversed(self.citations)),
        )
        self.assertEqual(proposal.proposal_id, replay.proposal_id)
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][1]), self.candidate)
        self.assertEqual(
            {value["concept_id"] for value in rows[0][2]},
            {"projects/voiceos", "decisions/public"},
        )
        self.assertFalse(rows[0][3]["canonical"])
        self.assertEqual(rows[0][4], "proposed")
        self.assertEqual(self.graph(), graph)

    def test_hidden_and_unknown_endpoint_citations_cannot_be_persisted(self):
        hidden = next(
            value.concept_id
            for value in self.generation.concepts
            if value.concept_id.startswith("secret/")
        )
        for target, proof in (
            (hidden, self.citation(hidden)),
            (
                "secret/absent",
                self.citations[1].model_copy(update={"concept_id": "secret/absent"}),
            ),
        ):
            with (
                self.subTest(target=target),
                self.assertRaisesRegex(PermissionError, "not visible"),
            ):
                self.propose(
                    proposed_content=json.dumps(
                        {**self.candidate, "target_concept_id": target}
                    ),
                    source_citations=(self.citations[0], proof),
                )
        self.assertEqual(self.stored(), [])

    def test_changed_generation_revision_hash_or_span_refuse_new_proposals(self):
        with self.assertRaises(KnowledgeGenerationStale):
            self.propose(expected_generation_sha256="0" * 64)
        for change in (
            {"source_revision": "other-revision"},
            {"content_sha256": "0" * 64},
            {"char_end": 100000},
        ):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "stale or invalid"),
            ):
                self.propose(
                    source_citations=(
                        self.citations[0].model_copy(update=change),
                        self.citations[1],
                    )
                )
        self.assertEqual(self.stored(), [])

    def test_owner_scoped_discard_is_idempotent_and_replay_does_not_resurrect(self):
        proposal = self.propose()
        with self.assertRaises(LookupError):
            discard_knowledge_proposal(
                self.connection,
                principal=PrincipalKey(self.tenant, "bob"),
                proposal_id=proposal.proposal_id,
            )
        first = discard_knowledge_proposal(
            self.connection, principal=self.principal, proposal_id=proposal.proposal_id
        )
        self.assertEqual(
            discard_knowledge_proposal(
                self.connection,
                principal=self.principal,
                proposal_id=proposal.proposal_id,
            ),
            first,
        )
        with self.assertRaisesRegex(ValueError, "conflicts with stored truth"):
            self.propose()
        self.assertEqual(self.stored()[0][4], "discarded")
        self.assertEqual(len(self.graph().relationships), 2)

    def test_revocation_retains_existing_proposal_but_blocks_new_submission(self):
        proposal = self.propose()
        previous = self.generation
        self.generation = activate_connection_fixture(
            self.connection, self.tenant, subject="charlie"
        )
        with self.assertRaises(KnowledgeGenerationStale):
            self.propose(expected_generation_sha256=previous.generation_sha256)
        self.citations = tuple(
            self.citation(value) for value in ("projects/voiceos", "decisions/public")
        )
        with self.assertRaises(PermissionError):
            self.propose()
        self.assertEqual(self.stored()[0][0], proposal.proposal_id)

    def test_cancellation_and_audit_failure_cannot_leave_a_partial_proposal(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(KnowledgeToolCancelled):
            self.propose(cancellation=cancelled)

        def audit(connection, **arguments):
            if arguments["outcome"] == "succeeded":
                raise RuntimeError("injected audit failure")
            return record_knowledge_tool_audit(connection, **arguments)

        with patch(
            "yap_server.knowledge.governed_knowledge_proposals.record_knowledge_tool_audit",
            side_effect=audit,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected audit failure"):
                self.propose()
        self.assertEqual(self.stored(), [])

    def test_read_agent_and_other_principal_cannot_submit_cited_connections(self):
        with self.assertRaises(PermissionError):
            self.propose(agent_id="librarian")
        with self.assertRaises(PermissionError):
            self.propose(principal=PrincipalKey(self.tenant, "bob"))
        self.assertEqual(self.stored(), [])

    def test_mcp_persists_typed_candidate_and_rejects_canonical_claims(self):
        anyio.run(self.exercise_mcp)

    async def exercise_mcp(self):
        connections = []

        def connect():
            connections.append(True)
            return psycopg.connect(DSN)

        server = create_governed_knowledge_mcp_server(
            tools=GovernedKnowledgeTools(self.authority),
            proposals=self.proposals,
            connection_factory=connect,
            principal=self.principal,
            agent_id="curator",
        )
        arguments = {
            "purpose": "knowledge.read",
            "proposal_type": "relationship",
            "proposed_content": json.dumps(self.candidate),
            "source_citations": [
                value.model_dump(mode="json") for value in self.citations
            ],
            "expected_generation_sha256": self.generation.generation_sha256,
        }
        async with Client(server, raise_exceptions=False) as client:
            rejected = await client.call_tool(
                "propose_knowledge",
                {
                    **arguments,
                    "proposed_content": json.dumps(
                        {**self.candidate, "authority": "human_confirmed"}
                    ),
                },
            )
            self.assertTrue(rejected.is_error)
            self.assertEqual(connections, [])
            result = await client.call_tool("propose_knowledge", arguments)
            self.assertFalse(result.is_error, result.content)
            self.assertEqual(result.structured_content["status"], "proposed")
            self.assertEqual(
                json.loads(result.structured_content["proposed_content"]),
                self.candidate,
            )
            self.assertEqual(len(result.structured_content["source_citations"]), 2)
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(len(self.graph().relationships), 2)
