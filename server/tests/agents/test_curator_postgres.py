from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time
import unittest
from uuid import uuid4

import psycopg

from yap_server.agents.archivist import (
    ArchivistRequest,
    PostgresArchivistProcessor,
    compile_reviewed_capture_generation,
)
from yap_server.agents.curator import CuratorRequest, PostgresCuratorEvidenceReader
from yap_server.agents.curator_publisher import PostgresCuratorPublisher
from yap_server.agents.curator_result_audit import (
    CuratorRuntimeAuditIdentity,
    PostgresCuratorResultAuditor,
    install_curator_result_audit_schema,
)
from yap_server.auth import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_proposals import (
    KnowledgeProposalCapacityExceeded,
    MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT,
    discard_knowledge_proposal,
    store_knowledge_proposal,
)
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation

from tests.agents.test_student_postgres import _capture


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class CuratorPostgresTests(unittest.TestCase):
    def test_exact_evidence_atomic_publication_restart_and_owner_isolation(self) -> None:
        owner, principal, compiled = _active_generation()
        citation = _citation(compiled, "Crash-safe private transcript")
        request = CuratorRequest(
            submission_id=f"curator-{uuid4().hex}",
            trigger="explicit-proposal",
            expected_generation_sha256=compiled.generation_sha256,
            reviewed_content="The reviewed meeting records crash-safe evidence.",
            source_citations=(citation,),
        )
        evidence = PostgresCuratorEvidenceReader(_connect).read(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        self.assertEqual(evidence.items[0].citation, citation)
        self.assertEqual(evidence.items[0].text, "Crash-safe private transcript")

        auditor = PostgresCuratorResultAuditor(_connect, _runtime_identity())
        publisher = PostgresCuratorPublisher(_connect, auditor)
        proposal = publisher.publish(
            principal=principal,
            request_id=f"request-{uuid4().hex}",
            request=request,
            evidence=evidence,
            provider_generation=11,
            started=time.monotonic(),
            deadline=time.monotonic() + 10,
            cancellation=threading.Event(),
        )
        restarted = auditor.read(
            principal=principal,
            submission_id=request.submission_id,
        )
        hidden = auditor.read(
            principal=_authenticated(
                PrincipalKey(owner.tenant_id, f"bob-{uuid4().hex}")
            ),
            submission_id=request.submission_id,
        )

        with psycopg.connect(POSTGRES_DSN) as verification:
            stored = verification.execute(
                """SELECT proposed_content, source_citations, status
                   FROM yap_knowledge_proposals
                   WHERE tenant_id = %s AND proposal_id = %s""",
                (owner.tenant_id, proposal.proposal_id),
            ).fetchone()
            success_audits = verification.execute(
                """SELECT operation, outcome, result_count
                   FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'curator'
                     AND outcome = 'succeeded'
                   ORDER BY audit_id""",
                (owner.tenant_id,),
            ).fetchall()
            active = verification.execute(
                """SELECT generation_sha256 FROM yap_knowledge_active_builds
                   WHERE tenant_id = %s""",
                (owner.tenant_id,),
            ).fetchone()
            _cleanup(verification, owner.tenant_id)

        self.assertEqual(
            stored,
            (
                request.reviewed_content,
                [citation.model_dump(mode="json")],
                "proposed",
            ),
        )
        self.assertEqual(
            success_audits,
            [
                ("reviewed-source-evidence", "succeeded", 1),
                ("propose", "succeeded", 1),
            ],
        )
        self.assertIsNotNone(restarted)
        assert restarted is not None
        self.assertEqual(restarted.proposal_id, proposal.proposal_id)
        self.assertIsNone(hidden)
        self.assertEqual(active, (compiled.generation_sha256,))

    def test_atomic_audit_failure_rolls_back_proposal_and_success_audit(self) -> None:
        owner, principal, compiled = _active_generation()
        citation = _citation(compiled, "Crash-safe private transcript")
        request = CuratorRequest(
            submission_id=f"curator-{uuid4().hex}",
            trigger="explicit-proposal",
            expected_generation_sha256=compiled.generation_sha256,
            reviewed_content="The reviewed meeting records crash-safe evidence.",
            source_citations=(citation,),
        )
        evidence = PostgresCuratorEvidenceReader(_connect).read(
            request,
            principal=principal,
            cancellation=threading.Event(),
        )
        failing = _FailingAuditor(_connect, _runtime_identity())
        with self.assertRaisesRegex(RuntimeError, "injected audit failure"):
            PostgresCuratorPublisher(_connect, failing).publish(
                principal=principal,
                request_id=f"request-{uuid4().hex}",
                request=request,
                evidence=evidence,
                provider_generation=11,
                started=time.monotonic(),
                deadline=time.monotonic() + 10,
                cancellation=threading.Event(),
            )

        with psycopg.connect(POSTGRES_DSN) as verification:
            proposal_count = verification.execute(
                """SELECT count(*) FROM yap_knowledge_proposals
                   WHERE tenant_id = %s""",
                (owner.tenant_id,),
            ).fetchone()[0]
            success_count = verification.execute(
                """SELECT count(*) FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND agent_id = 'curator'
                     AND operation = 'propose' AND outcome = 'succeeded'""",
                (owner.tenant_id,),
            ).fetchone()[0]
            result_count = verification.execute(
                """SELECT count(*) FROM yap_curator_result_audit
                   WHERE tenant_id = %s""",
                (owner.tenant_id,),
            ).fetchone()[0]
            _cleanup(verification, owner.tenant_id)
        self.assertEqual((proposal_count, success_count, result_count), (0, 0, 0))

    def test_unresolved_capacity_is_exact_retry_safe_and_released_by_discard(self) -> None:
        owner, principal, compiled = _active_generation()
        citation = _citation(compiled, "Crash-safe private transcript")
        proposals = [
            _store(
                principal,
                compiled.generation_sha256,
                citation,
                f"Bounded proposal {index}",
            )
            for index in range(MAX_UNRESOLVED_PROPOSALS_PER_SUBJECT - 1)
        ]
        self.assertEqual(len({item.proposal_id for item in proposals}), 63)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _store,
                    principal,
                    compiled.generation_sha256,
                    citation,
                    f"Concurrent bounded proposal {index}",
                )
                for index in range(2)
            ]
        concurrent_results: list[object] = []
        for future in futures:
            try:
                concurrent_results.append(future.result())
            except BaseException as error:
                concurrent_results.append(error)
        winners = [
            item for item in concurrent_results if not isinstance(item, BaseException)
        ]
        failures = [
            item for item in concurrent_results if isinstance(item, BaseException)
        ]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], KnowledgeProposalCapacityExceeded)
        winner = winners[0]
        retry = _store(
            principal,
            compiled.generation_sha256,
            citation,
            winner.proposed_content,
        )
        self.assertEqual(retry.proposal_id, winner.proposal_id)
        with self.assertRaises(KnowledgeProposalCapacityExceeded):
            _store(
                principal,
                compiled.generation_sha256,
                citation,
                "Capacity must fail",
            )
        with psycopg.connect(POSTGRES_DSN) as connection:
            discarded = discard_knowledge_proposal(
                connection,
                principal=owner,
                proposal_id=proposals[0].proposal_id,
            )
        self.assertEqual(discarded.status, "discarded")
        replacement = _store(
            principal,
            compiled.generation_sha256,
            citation,
            "Capacity released",
        )
        self.assertEqual(replacement.status, "proposed")

        other_subject = _authenticated(
            PrincipalKey(owner.tenant_id, f"bob-{uuid4().hex}")
        )
        with psycopg.connect(POSTGRES_DSN) as verification:
            path_prefix = verification.execute(
                """SELECT permission_path_prefix FROM yap_knowledge_concepts
                   WHERE tenant_id = %s AND generation_sha256 = %s
                   LIMIT 1""",
                (owner.tenant_id, compiled.generation_sha256),
            ).fetchone()[0]
            verification.execute(
                """INSERT INTO yap_knowledge_permission_audience (
                       tenant_id, generation_sha256, path_prefix, subject_id
                   ) VALUES (%s, %s, %s, %s)""",
                (
                    owner.tenant_id,
                    compiled.generation_sha256,
                    path_prefix,
                    other_subject.subject_id,
                ),
            )
        other_proposal = _store(
            other_subject,
            compiled.generation_sha256,
            citation,
            "Independent authorized owner proposal",
        )
        with psycopg.connect(POSTGRES_DSN) as verification:
            counts = verification.execute(
                """SELECT count(*) FROM yap_knowledge_proposals
                   WHERE tenant_id = %s AND status = 'proposed'
                   GROUP BY proposer_subject_id ORDER BY proposer_subject_id""",
                (owner.tenant_id,),
            ).fetchall()
            with self.assertRaises(PermissionError):
                discard_knowledge_proposal(
                    verification,
                    principal=other_subject.key,
                    proposal_id=replacement.proposal_id,
                )
            _cleanup(verification, owner.tenant_id)
        self.assertEqual(sorted(row[0] for row in counts), [1, 64])
        self.assertEqual(other_proposal.status, "proposed")


class _FailingAuditor(PostgresCuratorResultAuditor):
    def record_in_transaction(self, connection, **value) -> None:
        del connection, value
        raise RuntimeError("injected audit failure")


def _active_generation():
    suffix = uuid4().hex
    owner = PrincipalKey(f"tenant-{suffix}", f"alice-{suffix}")
    principal = _authenticated(owner)
    capture = _capture(owner, f"job-{suffix}")
    compiled = compile_reviewed_capture_generation(capture, principal=principal)
    PostgresArchivistProcessor(_connect).ingest(
        ArchivistRequest(capture.capture_sha256),
        principal=principal,
        cancellation=threading.Event(),
    )
    with psycopg.connect(POSTGRES_DSN) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_curator_result_audit_schema(connection)
        store_generation_embeddings(
            connection,
            tenant_id=owner.tenant_id,
            generation_sha256=compiled.generation_sha256,
            embedding_model_id="curator-test",
            embedding_model_revision="revision-1",
            embeddings={
                chunk.chunk_id: (1.0,) + (0.0,) * 767
                for chunk in compiled.chunks
            },
        )
        activate_complete_generation(
            connection,
            tenant_id=owner.tenant_id,
            generation_sha256=compiled.generation_sha256,
        )
    return owner, principal, compiled


def _citation(compiled, phrase: str) -> ProposalCitation:
    concept = compiled.concepts[0]
    start = concept.body.index(phrase)
    return ProposalCitation(
        concept_id=concept.concept_id,
        source_revision=compiled.source_revision,
        content_sha256=concept.content_sha256,
        char_start=start,
        char_end=start + len(phrase),
    )


def _store(
    principal: AuthenticatedPrincipal,
    generation_sha256: str,
    citation: ProposalCitation,
    content: str,
):
    with psycopg.connect(POSTGRES_DSN) as connection:
        return store_knowledge_proposal(
            connection,
            principal=principal.key,
            purpose="knowledge.read",
            agent_id="curator",
            agent_capabilities=frozenset({"knowledge.propose"}),
            proposal_type="summary",
            proposed_content=content,
            source_citations=(citation,),
            expected_generation_sha256=generation_sha256,
        )


def _authenticated(owner: PrincipalKey) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=owner.tenant_id,
        subject_id=owner.subject_id,
        client_id="curator-tests",
        scopes=frozenset(),
    )


def _connect():
    return psycopg.connect(POSTGRES_DSN)


def _runtime_identity() -> CuratorRuntimeAuditIdentity:
    return CuratorRuntimeAuditIdentity(
        candidate_id="gemma4-31b-it-nvfp4",
        model="nvidia/Gemma-4-31B-IT-NVFP4",
        model_revision="f" * 40,
        runtime_id="gemma-vllm-26.07-xgrammar-0.2.1",
        profile_sha256="1" * 64,
        candidate_lock_sha256="2" * 64,
    )


def _cleanup(connection, tenant_id: str) -> None:
    connection.execute(
        "DELETE FROM yap_curator_result_audit WHERE tenant_id = %s",
        (tenant_id,),
    )
    connection.execute(
        "DELETE FROM yap_knowledge_tool_audit WHERE tenant_id = %s",
        (tenant_id,),
    )
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
        "DELETE FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
        (tenant_id,),
    )
    connection.execute(
        "DELETE FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s",
        (tenant_id,),
    )


if __name__ == "__main__":
    unittest.main()
