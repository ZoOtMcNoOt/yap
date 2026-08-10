from __future__ import annotations

import json
import threading
import unittest

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.agent_reasoning_routes import (
    AgentReasoningRoutes,
    AgentWorkloadClass,
    ReasoningRetryableError,
)
from yap_server.knowledge.governed_rag_agent import (
    GovernedRagAgent,
)
from yap_server.knowledge.knowledge_proposals import KnowledgeProposal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCitation,
    KnowledgeToolItem,
    KnowledgeToolResponse,
)
from yap_server.knowledge.terminology_snapshot import (
    TerminologyRecord,
    freeze_terminology_snapshot,
)


def _routes(reason):
    return AgentReasoningRoutes(
        rapid_automation=reason,
        complex_orchestration=reason,
    )


class _Tools:
    def __init__(self, items: tuple[KnowledgeToolItem, ...]) -> None:
        self.items = items

    def execute(self, *args: object, **kwargs: object) -> KnowledgeToolResponse:
        return KnowledgeToolResponse(
            "search", "a" * 64, "b" * 64, "c" * 64, self.items, False
        )


class _Proposals:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def propose(self, *args: object, **kwargs: object) -> KnowledgeProposal:
        self.calls.append(kwargs)
        return KnowledgeProposal(
            "tenant-1",
            "d" * 64,
            "a" * 64,
            "summary",
            str(kwargs["proposed_content"]),
            tuple(kwargs["source_citations"]),  # type: ignore[arg-type]
            "e" * 64,
            "b" * 64,
            "c" * 64,
            "proposed",
        )


class GovernedRagAgentTests(unittest.TestCase):
    def test_question_uses_the_executing_search_boundary(self) -> None:
        agent = GovernedRagAgent(
            tools=_Tools(()),  # type: ignore[arg-type]
            proposals=_Proposals(),  # type: ignore[arg-type]
            reasoning_routes=_routes(lambda prompt, cancellation: "{}"),
            maximum_prompt_characters=10_000,
            maximum_output_characters=2_000,
            read_terminology_snapshot=_snapshot_reader,
        )
        with self.assertRaisesRegex(ValueError, "RAG question"):
            agent.answer(
                object(),  # type: ignore[arg-type]
                principal=PrincipalKey("tenant-1", "person-1"),
                agent_id="librarian",
                purpose="knowledge.read",
                question="a" * 1_025,
                job_id="job-1",
                workload_class=AgentWorkloadClass.RAPID_AUTOMATION,
                cancellation=threading.Event(),
            )

    def test_retries_invalid_output_then_stores_cited_terminology_safe_proposal(
        self,
    ) -> None:
        proposals = _Proposals()
        outputs = iter(
            (
                "not json",
                json.dumps(
                    {
                        "answer": "TAVI publication is atomic.",
                        "citationConceptIds": ["meeting-1"],
                    }
                ),
            )
        )
        agent = GovernedRagAgent(
            tools=_Tools((_item(),)),  # type: ignore[arg-type]
            proposals=proposals,  # type: ignore[arg-type]
            reasoning_routes=_routes(lambda prompt, cancellation: next(outputs)),
            maximum_prompt_characters=10_000,
            maximum_output_characters=2_000,
            read_terminology_snapshot=_snapshot_reader,
        )

        result = agent.answer(
            object(),  # type: ignore[arg-type]
            principal=PrincipalKey("tenant-1", "person-1"),
            agent_id="librarian",
            purpose="knowledge.read",
            question="TAVI publication",
            job_id="job-1",
            workload_class=AgentWorkloadClass.COMPLEX_ORCHESTRATION,
            cancellation=threading.Event(),
        )

        self.assertTrue(result.model_invoked)
        self.assertEqual(result.proposal.status, "proposed")
        self.assertEqual(len(proposals.calls), 1)

    def test_no_visible_evidence_never_invokes_model(self) -> None:
        invoked = False

        def reason(prompt: str, cancellation: threading.Event) -> str:
            nonlocal invoked
            invoked = True
            return "{}"

        agent = GovernedRagAgent(
            tools=_Tools(()),  # type: ignore[arg-type]
            proposals=_Proposals(),  # type: ignore[arg-type]
            reasoning_routes=_routes(reason),
            maximum_prompt_characters=10_000,
            maximum_output_characters=2_000,
            read_terminology_snapshot=_snapshot_reader,
        )
        result = agent.answer(
            object(),  # type: ignore[arg-type]
            principal=PrincipalKey("tenant-1", "person-1"),
            agent_id="librarian",
            purpose="knowledge.read",
            question="unknown evidence",
            job_id="job-1",
            workload_class=AgentWorkloadClass.COMPLEX_ORCHESTRATION,
            cancellation=threading.Event(),
        )

        self.assertFalse(invoked)
        self.assertFalse(result.model_invoked)
        self.assertIsNone(result.proposal)

    def test_rejects_unavailable_citation_after_bounded_retry(self) -> None:
        output = json.dumps(
            {"answer": "Invented", "citationConceptIds": ["hidden-concept"]}
        )
        agent = GovernedRagAgent(
            tools=_Tools((_item(),)),  # type: ignore[arg-type]
            proposals=_Proposals(),  # type: ignore[arg-type]
            reasoning_routes=_routes(lambda prompt, cancellation: output),
            maximum_prompt_characters=10_000,
            maximum_output_characters=2_000,
            read_terminology_snapshot=_snapshot_reader,
        )
        with self.assertRaisesRegex(ValueError, "admissible"):
            agent.answer(
                object(),  # type: ignore[arg-type]
                principal=PrincipalKey("tenant-1", "person-1"),
                agent_id="librarian",
                purpose="knowledge.read",
                question="TAVI publication",
                job_id="job-1",
                workload_class=AgentWorkloadClass.COMPLEX_ORCHESTRATION,
                cancellation=threading.Event(),
            )

    def test_bounds_unavailable_reasoning_server_retries(self) -> None:
        attempts = 0
        proposals = _Proposals()

        def unavailable(prompt: str, cancellation: threading.Event) -> str:
            nonlocal attempts
            attempts += 1
            raise ReasoningRetryableError("server unavailable")

        agent = GovernedRagAgent(
            tools=_Tools((_item(),)),  # type: ignore[arg-type]
            proposals=proposals,  # type: ignore[arg-type]
            reasoning_routes=_routes(unavailable),
            maximum_prompt_characters=10_000,
            maximum_output_characters=2_000,
            read_terminology_snapshot=_snapshot_reader,
        )

        with self.assertRaisesRegex(ValueError, "admissible"):
            agent.answer(
                object(),  # type: ignore[arg-type]
                principal=PrincipalKey("tenant-1", "person-1"),
                agent_id="librarian",
                purpose="knowledge.read",
                question="TAVI publication",
                job_id="job-1",
                workload_class=AgentWorkloadClass.COMPLEX_ORCHESTRATION,
                cancellation=threading.Event(),
            )

        self.assertEqual(attempts, 2)
        self.assertEqual(proposals.calls, [])

    def test_rejects_snapshot_owned_by_another_subject(self) -> None:
        agent = GovernedRagAgent(
            tools=_Tools((_item(),)),  # type: ignore[arg-type]
            proposals=_Proposals(),  # type: ignore[arg-type]
            reasoning_routes=_routes(lambda prompt, cancellation: "{}"),
            maximum_prompt_characters=10_000,
            maximum_output_characters=2_000,
            read_terminology_snapshot=lambda connection, principal, job_id: _snapshot(
                PrincipalKey(principal.tenant_id, "other-person")
            ),
        )
        with self.assertRaisesRegex(PermissionError, "unavailable"):
            agent.answer(
                object(),  # type: ignore[arg-type]
                principal=PrincipalKey("tenant-1", "person-1"),
                agent_id="librarian",
                purpose="knowledge.read",
                question="TAVI publication",
                job_id="job-1",
                workload_class=AgentWorkloadClass.COMPLEX_ORCHESTRATION,
                cancellation=threading.Event(),
            )


def _item() -> KnowledgeToolItem:
    return KnowledgeToolItem(
        KnowledgeToolCitation("meeting-1", "revision-1", "f" * 64, 0, 27),
        "TAVI publication is atomic.",
        None,
        None,
    )


def _snapshot_reader(connection: object, principal: PrincipalKey, job_id: str):
    del connection, job_id
    return _snapshot(principal)


def _snapshot(principal: PrincipalKey):
    return freeze_terminology_snapshot(
        (
            TerminologyRecord(
                record_id="tavi",
                tenant_id=principal.tenant_id,
                scope="personal",
                owner_id=principal.subject_id,
                locale="en-US",
                canonical_form="TAVI",
                variants=("tavi",),
                sensitivity="internal",
                version=1,
                deleted=False,
                audit_revision="audit-1",
                changed_at="2026-08-09T12:00:00Z",
            ),
        ),
        principal=principal,
        team_ids=(),
        locale="en-US",
        source_revision="a" * 64,
    )


if __name__ == "__main__":
    unittest.main()
