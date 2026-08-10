from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.knowledge_agent_authority import KnowledgeAgentAuthority
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.governed_knowledge_tools import (
    GovernedKnowledgeTools,
)
from yap_server.knowledge.governed_knowledge_proposals import (
    GovernedKnowledgeProposals,
)
from yap_server.knowledge.governed_rag_agent import GovernedRagAgent
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeAgentProfile,
    KnowledgeToolCancelled,
    SearchKnowledgeRequest,
)
from yap_server.knowledge.knowledge_proposals import (
    ProposalCitation,
    install_knowledge_proposal_schema,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_lexical,
)
from yap_server.knowledge.reviewed_capture_ledger import (
    append_reviewed_meeting_capture,
    install_reviewed_capture_schema,
)
from yap_server.knowledge.reviewed_meeting_knowledge import (
    KnowledgeSourceReview,
    result_revision_sha256,
)

from tests.jobs.service_fixtures import _published_result


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class ReviewedMeetingPostgresRouteTests(unittest.TestCase):
    def test_authoritative_result_reaches_permission_safe_cited_search(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        owner = PrincipalKey(tenant_id, f"alice-{suffix}")
        job_id = f"job-{suffix}"
        job = {
            "sessionId": f"session-{suffix}",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = _published_result(job)
        review = KnowledgeSourceReview(
            reviewer=owner,
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_reviewed_capture_schema(connection)
            capture = append_reviewed_meeting_capture(
                connection,
                result,
                projection=job,
                job_id=job_id,
                owner=owner,
                title="Architecture review",
                review=review,
            )
            with TemporaryDirectory() as directory:
                root = Path(directory)
                _bundle(
                    root, capture.normalized_okf, tenant_id, owner.subject_id, job_id
                )
                generation = compile_okf_bundle(
                    root,
                    tenant_id=tenant_id,
                    source_revision=capture.capture_sha256,
                )
            install_knowledge_schema(connection)
            stage_compiled_generation(connection, generation)
            store_generation_embeddings(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                embedding_model_id="synthetic-test",
                embedding_model_revision="revision-1",
                embeddings={
                    item.chunk_id: (1.0,) + (0.0,) * 767 for item in generation.chunks
                },
            )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
            results = search_postgres_knowledge_lexical(
                connection,
                principal=owner,
                purpose="knowledge.read",
                agent_capabilities=frozenset({"knowledge.search.lexical"}),
                search_text="crash safe transcript",
            )
            install_knowledge_proposal_schema(connection)
            install_knowledge_tool_audit_schema(connection)
            source = results.results[0]
            proposal_service = GovernedKnowledgeProposals(
                KnowledgeAgentAuthority(
                    (
                        KnowledgeAgentProfile(
                            agent_id="proposal-agent",
                            capabilities=frozenset({"knowledge.propose"}),
                            purposes=frozenset({"knowledge.read"}),
                            maximum_results=5,
                            maximum_output_characters=2_000,
                            statement_timeout_milliseconds=5_000,
                        ),
                    )
                )
            )
            proposal = proposal_service.propose(
                connection,
                principal=owner,
                purpose="knowledge.read",
                agent_id="proposal-agent",
                proposal_type="summary",
                proposed_content="The reviewed meeting records crash safety.",
                source_citations=(
                    ProposalCitation(
                        source.concept_id,
                        source.source_revision,
                        source.content_sha256,
                        source.char_start,
                        source.char_end,
                    ),
                ),
                expected_generation_sha256=generation.generation_sha256,
                cancellation=threading.Event(),
            )
            proposal_policy = connection.execute(
                """SELECT inherited_policy FROM yap_knowledge_proposals
                   WHERE tenant_id = %s AND proposal_id = %s""",
                (tenant_id, proposal.proposal_id),
            ).fetchone()[0]
            tools = GovernedKnowledgeTools(
                KnowledgeAgentAuthority(
                    (
                        KnowledgeAgentProfile(
                            agent_id="librarian",
                            capabilities=frozenset({"knowledge.search.lexical"}),
                            purposes=frozenset({"knowledge.read"}),
                            maximum_results=5,
                            maximum_output_characters=2_000,
                            statement_timeout_milliseconds=5_000,
                        ),
                    )
                )
            )
            tool_result = tools.execute(
                connection,
                principal=owner,
                agent_id="librarian",
                request=SearchKnowledgeRequest(
                    purpose="knowledge.read",
                    search_text="crash safe transcript",
                ),
                cancellation=threading.Event(),
            )
            rag_agent = GovernedRagAgent(
                tools=tools,
                proposals=GovernedKnowledgeProposals(
                    KnowledgeAgentAuthority(
                        (
                            KnowledgeAgentProfile(
                                agent_id="librarian",
                                capabilities=frozenset({"knowledge.propose"}),
                                purposes=frozenset({"knowledge.read"}),
                                maximum_results=5,
                                maximum_output_characters=2_000,
                                statement_timeout_milliseconds=5_000,
                            ),
                        )
                    )
                ),
                reason=lambda _prompt, _cancellation: (
                    '{"answer":"The reviewed meeting records crash safety.",'
                    f'"citationConceptIds":["meetings/{job_id}"]}}'
                ),
                maximum_prompt_characters=20_000,
                maximum_output_characters=2_000,
            )
            cited_answer = rag_agent.answer(
                connection,
                principal=owner,
                agent_id="librarian",
                purpose="knowledge.read",
                question="crash safe transcript",
                terminology_exact_forms=("crash safety",),
                expected_generation_sha256=generation.generation_sha256,
                cancellation=threading.Event(),
            )
            tiny_tools = GovernedKnowledgeTools(
                KnowledgeAgentAuthority(
                    (
                        KnowledgeAgentProfile(
                            agent_id="bounded-librarian",
                            capabilities=frozenset({"knowledge.search.lexical"}),
                            purposes=frozenset({"knowledge.read"}),
                            maximum_results=5,
                            maximum_output_characters=1,
                            statement_timeout_milliseconds=5_000,
                        ),
                    )
                )
            )
            bounded_result = tiny_tools.execute(
                connection,
                principal=owner,
                agent_id="bounded-librarian",
                request=SearchKnowledgeRequest(
                    purpose="knowledge.read",
                    search_text="crash safe transcript",
                ),
                cancellation=threading.Event(),
            )
            audit = connection.execute(
                """SELECT operation, outcome, result_count, generation_sha256,
                          permission_hash, authorization_hash
                   FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'librarian'
                     AND operation = 'search'""",
                (tenant_id,),
            ).fetchone()
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(KnowledgeToolCancelled):
                tools.execute(
                    connection,
                    principal=owner,
                    agent_id="librarian",
                    request=SearchKnowledgeRequest(
                        purpose="knowledge.read",
                        search_text="crash safe transcript",
                    ),
                    cancellation=cancelled,
                )
            audit_outcomes = connection.execute(
                """SELECT outcome, generation_sha256 FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s ORDER BY audit_id""",
                (tenant_id,),
            ).fetchall()
            connection.execute(
                "DELETE FROM yap_knowledge_proposals WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_generation_holds WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_tool_audit WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()

        self.assertEqual(len(results.results), 1)
        self.assertEqual(proposal.status, "proposed")
        self.assertFalse(proposal_policy["canonical"])
        self.assertEqual(proposal_policy["classification"], "confidential")
        self.assertEqual(results.results[0].source_revision, capture.capture_sha256)
        self.assertEqual(results.results[0].concept_id, f"meetings/{job_id}")
        self.assertEqual(tool_result.items[0].text, results.results[0].text)
        self.assertTrue(cited_answer.model_invoked)
        self.assertEqual(cited_answer.generation_sha256, generation.generation_sha256)
        self.assertEqual(cited_answer.proposal.status, "proposed")
        self.assertEqual(bounded_result.items, ())
        self.assertTrue(bounded_result.output_budget_exhausted)
        self.assertEqual(
            audit,
            (
                "search",
                "succeeded",
                1,
                tool_result.generation_sha256,
                tool_result.permission_hash,
                tool_result.authorization_hash,
            ),
        )
        self.assertNotIn("crash safe transcript", repr(audit).casefold())
        self.assertEqual(
            audit_outcomes,
            [
                ("succeeded", proposal.generation_sha256),
                ("succeeded", tool_result.generation_sha256),
                ("succeeded", cited_answer.generation_sha256),
                ("succeeded", cited_answer.generation_sha256),
                ("succeeded", bounded_result.generation_sha256),
                ("cancelled", None),
            ],
        )
        self.assertEqual(
            generation.concepts[0].frontmatter["provenance"]["review_sha256"],
            review.review_sha256,
        )


def _bundle(
    root: Path, concept: str, tenant_id: str, subject_id: str, job_id: str
) -> None:
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
    )
    (root / "meetings").mkdir()
    (root / "meetings" / f"{job_id}.md").write_text(concept, encoding="utf-8")
    (root / "permissions").mkdir()
    (root / "permissions" / "meetings.yml").write_text(
        f"""path_prefix: meetings/
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: {subject_id}}}]}}
purposes: [knowledge.read]
classification: confidential
denials: {{users: []}}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
