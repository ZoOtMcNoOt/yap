from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.jobs.ownership import PrincipalRecordingJobs
from yap_server.knowledge.agent_reasoning_routes import (
    AgentReasoningRoutes,
    AgentWorkloadClass,
)
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
from yap_server.knowledge.terminology_snapshot import freeze_terminology_snapshot
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeAgentProfile,
    KnowledgeToolCancelled,
    ProposalCitation,
    SearchKnowledgeRequest,
)
from yap_server.knowledge.knowledge_proposals import (
    install_knowledge_proposal_schema,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_reviewed_capture_generation,
    require_knowledge_source_admission,
)
from yap_server.knowledge.okf_compiler import (
    compiled_generation_sha256,
    compile_okf_bundle,
)
from yap_server.knowledge.okf_projection import (
    compile_chunks,
    compile_relationships,
)
from yap_server.knowledge.permission_policy import effective_permission
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_lexical,
)
from yap_server.knowledge.reviewed_capture_ledger import (
    append_reviewed_meeting_capture,
    install_reviewed_capture_schema,
    read_reviewed_capture,
)
from yap_server.knowledge.reviewed_meeting_knowledge import (
    KnowledgeSourceReview,
    result_revision_sha256,
)

from tests.jobs.service_fixtures import _published_result


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class ReviewedMeetingPostgresRouteTests(unittest.TestCase):
    def test_reviewed_admission_derives_exact_source_and_owner_policy(self) -> None:
        suffix = uuid4().hex
        tenant_id = f"tenant-{suffix}"
        owner = PrincipalKey(tenant_id, f"alice-{suffix}")
        bob = PrincipalKey(tenant_id, f"bob-{suffix}")
        job_id = f"job-{suffix}"
        job = {
            "sessionId": f"session-{suffix}",
            "captureManifest": {"sha256": "a" * 64},
        }
        result = _published_result(job)
        review = KnowledgeSourceReview(
            reviewer=owner,
            job_id=job_id,
            title="Architecture review",
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_reviewed_capture_schema(connection)
            capture = append_reviewed_meeting_capture(
                connection,
                PrincipalRecordingJobs(_ResultService(job, result), owner),
                review=review,
            )
            install_knowledge_schema(connection)
            with TemporaryDirectory() as directory:
                root = Path(directory)
                _bundle(root, capture.normalized_okf, tenant_id, owner.subject_id, job_id)
                generation = compile_okf_bundle(
                    root,
                    tenant_id=tenant_id,
                    source_revision=capture.capture_sha256,
                )
            with TemporaryDirectory() as directory:
                root = Path(directory)
                _bundle(root, capture.normalized_okf, tenant_id, bob.subject_id, job_id)
                cross_owner = compile_okf_bundle(
                    root,
                    tenant_id=tenant_id,
                    source_revision=capture.capture_sha256,
                )
            with TemporaryDirectory() as directory:
                wrong_path = _compile_capture_at_wrong_path(
                    Path(directory),
                    capture.normalized_okf,
                    tenant_id,
                    owner,
                    capture.capture_sha256,
                )

            body_mutation = _rehashed_reviewed_mutation(
                generation,
                replace(
                    generation.concepts[0],
                    body=generation.concepts[0].body + "\nInjected content.\n",
                ),
            )
            frontmatter_mutation = _rehashed_reviewed_mutation(
                generation,
                replace(
                    generation.concepts[0],
                    frontmatter={
                        **generation.concepts[0].frontmatter,
                        "resource": f"yap://tenant/{tenant_id}/meeting/other",
                    },
                ),
            )
            for invalid in (
                cross_owner,
                wrong_path,
                body_mutation,
                frontmatter_mutation,
            ):
                with self.subTest(generation=invalid.generation_sha256):
                    with self.assertRaises((PermissionError, ValueError)):
                        admit_reviewed_capture_generation(
                            connection,
                            principal=_authenticated(owner),
                            capture_sha256=capture.capture_sha256,
                            generation=invalid,
                        )
            self.assertEqual(
                connection.execute(
                    """SELECT count(*) FROM yap_knowledge_source_admissions
                       WHERE tenant_id = %s""",
                    (tenant_id,),
                ).fetchone()[0],
                0,
            )
            admission = admit_reviewed_capture_generation(
                connection,
                principal=_authenticated(owner),
                capture_sha256=capture.capture_sha256,
                generation=generation,
            )
            connection.execute(
                """UPDATE yap_knowledge_source_admissions SET source_path = %s
                   WHERE tenant_id = %s AND admission_sha256 = %s""",
                ("forged/path.md", tenant_id, admission.admission_sha256),
            )
            with self.assertRaisesRegex(ValueError, "differs from its identity"):
                require_knowledge_source_admission(
                    connection,
                    tenant_id=tenant_id,
                    admission_sha256=admission.admission_sha256,
                    generation_sha256=generation.generation_sha256,
                    source_revision=generation.source_revision,
                )
            connection.execute(
                "DELETE FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()

    def test_reviewed_capture_read_rehashes_durable_content(self) -> None:
        for field in ("normalized_okf", "result_payload"):
            with self.subTest(field=field):
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
                    job_id=job_id,
                    title="Architecture review",
                    reviewed_at_utc="2026-08-09T13:00:00Z",
                    result_revision_sha256=result_revision_sha256(result),
                    decision="accepted",
                )
                with psycopg.connect(POSTGRES_DSN) as connection:
                    install_reviewed_capture_schema(connection)
                    capture = append_reviewed_meeting_capture(
                        connection,
                        PrincipalRecordingJobs(_ResultService(job, result), owner),
                        review=review,
                    )
                    if field == "normalized_okf":
                        connection.execute(
                            """UPDATE yap_knowledge_reviewed_captures
                               SET normalized_okf = normalized_okf || %s
                               WHERE tenant_id = %s AND capture_sha256 = %s""",
                            ("\nforged", tenant_id, capture.capture_sha256),
                        )
                    else:
                        connection.execute(
                            """UPDATE yap_knowledge_reviewed_captures
                               SET result_payload = result_payload || %s::jsonb
                               WHERE tenant_id = %s AND capture_sha256 = %s""",
                            ('{"forged":true}', tenant_id, capture.capture_sha256),
                        )
                    connection.commit()
                with psycopg.connect(POSTGRES_DSN) as restarted:
                    with self.assertRaisesRegex(ValueError, "content identity"):
                        read_reviewed_capture(
                            restarted,
                            principal=owner,
                            capture_sha256=capture.capture_sha256,
                        )
                    restarted.execute(
                        """DELETE FROM yap_knowledge_reviewed_captures
                           WHERE tenant_id = %s""",
                        (tenant_id,),
                    )
                    restarted.commit()

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
            job_id=job_id,
            title="Architecture review",
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_reviewed_capture_schema(connection)
            capture = append_reviewed_meeting_capture(
                connection,
                PrincipalRecordingJobs(_ResultService(job, result), owner),
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
            with self.assertRaisesRegex(LookupError, "does not exist"):
                admit_reviewed_capture_generation(
                    connection,
                    principal=_authenticated(
                        PrincipalKey(tenant_id, f"bob-{suffix}")
                    ),
                    capture_sha256=capture.capture_sha256,
                    generation=generation,
                )
            source_admission = admit_reviewed_capture_generation(
                connection,
                principal=_authenticated(owner),
                capture_sha256=capture.capture_sha256,
                generation=generation,
            )
            stage_compiled_generation(
                connection,
                generation,
                source_admission_sha256=source_admission.admission_sha256,
            )
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
                        concept_id=source.concept_id,
                        source_revision=source.source_revision,
                        content_sha256=source.content_sha256,
                        char_start=source.char_start,
                        char_end=source.char_end,
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
                reasoning_routes=AgentReasoningRoutes(
                    rapid_automation=lambda _prompt, _cancellation: (
                        '{"answer":"The reviewed meeting records crash safety.",'
                        f'"citationConceptIds":["meetings/{job_id}"]}}'
                    ),
                    complex_orchestration=lambda _prompt, _cancellation: (
                        '{"answer":"The reviewed meeting records crash safety.",'
                        f'"citationConceptIds":["meetings/{job_id}"]}}'
                    ),
                ),
                maximum_prompt_characters=20_000,
                maximum_output_characters=2_000,
                read_terminology_snapshot=lambda connection, principal, job_id: (
                    freeze_terminology_snapshot(
                        (),
                        principal=principal,
                        team_ids=(),
                        locale="en-US",
                        source_revision="0" * 64,
                    )
                ),
            )
            cited_answer = rag_agent.answer(
                connection,
                principal=owner,
                agent_id="librarian",
                purpose="knowledge.read",
                question="crash safe transcript",
                job_id="reviewed-meeting-job",
                workload_class=AgentWorkloadClass.COMPLEX_ORCHESTRATION,
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

    def test_reviewed_capture_is_exactly_idempotent_and_restart_readable(self) -> None:
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
            job_id=job_id,
            title="Architecture review",
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        jobs = PrincipalRecordingJobs(_ResultService(job, result), owner)
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_reviewed_capture_schema(connection)
            first = append_reviewed_meeting_capture(
                connection, jobs, review=review
            )
            retry = append_reviewed_meeting_capture(
                connection, jobs, review=review
            )
            connection.commit()
        with psycopg.connect(POSTGRES_DSN) as restarted:
            persisted = read_reviewed_capture(
                restarted, principal=owner, capture_sha256=first.capture_sha256
            )
            restarted.execute(
                "DELETE FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s",
                (tenant_id,),
            )
            restarted.commit()

        self.assertEqual(retry, first)
        self.assertEqual(persisted, first)

    def test_reviewed_capture_rejects_conflicting_authority_and_storage(self) -> None:
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
            job_id=job_id,
            title="Architecture review",
            reviewed_at_utc="2026-08-09T13:00:00Z",
            result_revision_sha256=result_revision_sha256(result),
            decision="accepted",
        )
        jobs = PrincipalRecordingJobs(_ResultService(job, result), owner)
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_reviewed_capture_schema(connection)
            stored = append_reviewed_meeting_capture(
                connection, jobs, review=review
            )
            conflicting_title = KnowledgeSourceReview(
                reviewer=owner,
                job_id=job_id,
                title="A different title",
                reviewed_at_utc="2026-08-09T14:00:00Z",
                result_revision_sha256=result_revision_sha256(result),
                decision="accepted",
            )
            with self.assertRaises(psycopg.errors.UniqueViolation):
                append_reviewed_meeting_capture(
                    connection, jobs, review=conflicting_title
                )
            connection.rollback()
            with self.assertRaisesRegex(PermissionError, "owning principal"):
                append_reviewed_meeting_capture(
                    connection,
                    PrincipalRecordingJobs(
                        _ResultService(job, result),
                        PrincipalKey(tenant_id, f"bob-{suffix}"),
                    ),
                    review=review,
                )
            connection.execute(
                """UPDATE yap_knowledge_reviewed_captures
                   SET normalized_okf = normalized_okf || %s
                   WHERE tenant_id = %s AND capture_sha256 = %s""",
                ("\nmutated", tenant_id, stored.capture_sha256),
            )
            connection.commit()
            with self.assertRaisesRegex(ValueError, "differs from stored"):
                append_reviewed_meeting_capture(
                    connection, jobs, review=review
                )
            connection.rollback()
            connection.execute(
                "DELETE FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()


class _ResultService:
    def __init__(self, job: dict[str, object], result: dict[str, object]) -> None:
        self._job = job
        self._result = result

    def get(self, job_id: str, *, owner: PrincipalKey) -> dict[str, object]:
        if not job_id or not owner.subject_id:
            raise AssertionError("owned job lookup was not bound")
        return dict(self._job)

    def get_result(
        self, job_id: str, *, owner: PrincipalKey
    ) -> dict[str, object]:
        if not job_id or not owner.subject_id:
            raise AssertionError("owned result lookup was not bound")
        return dict(self._result)


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


def _compile_capture_at_wrong_path(
    root: Path,
    concept: str,
    tenant_id: str,
    owner: PrincipalKey,
    source_revision: str,
):
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
    )
    (root / "projects").mkdir()
    (root / "projects" / "meeting.md").write_text(concept, encoding="utf-8")
    (root / "permissions").mkdir()
    (root / "permissions" / "projects.yml").write_text(
        f"""path_prefix: projects/
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: {owner.subject_id}}}]}}
purposes: [knowledge.read]
classification: confidential
denials: {{users: []}}
""",
        encoding="utf-8",
    )
    return compile_okf_bundle(
        root,
        tenant_id=tenant_id,
        source_revision=source_revision,
    )


def _rehashed_reviewed_mutation(generation, concept):
    permission = effective_permission(Path(concept.source_path), generation.permissions)
    candidate = replace(
        generation,
        concepts=(concept,),
        chunks=compile_chunks(
            concept_id=concept.concept_id,
            source_path=concept.source_path,
            body=concept.body,
            permission_sha256=permission.permission_sha256,
        ),
        relationships=compile_relationships(
            concept_id=concept.concept_id,
            source_path=concept.source_path,
            body=concept.body,
            frontmatter=concept.frontmatter,
        ),
        generation_sha256="",
    )
    return replace(
        candidate,
        generation_sha256=compiled_generation_sha256(candidate),
    )


def _authenticated(principal: PrincipalKey) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=principal.tenant_id,
        subject_id=principal.subject_id,
        client_id="reviewed-meeting-tests",
        scopes=frozenset(),
    )


if __name__ == "__main__":
    unittest.main()
