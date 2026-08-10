from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Callable

from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .agent_reasoning_routes import (
    AgentReasoningRoutes,
    AgentWorkloadClass,
    ReasoningRetryableError,
)
from .governed_knowledge_proposals import GovernedKnowledgeProposals
from .governed_knowledge_tools import GovernedKnowledgeTools
from .knowledge_proposals import KnowledgeProposal
from .knowledge_tool_contract import (
    KnowledgeToolCancelled,
    ProposalCitation,
    SearchKnowledgeRequest,
    validate_search_text,
)
from .terminology_ledger import read_job_terminology_snapshot
from .terminology_snapshot import TerminologySnapshot


TerminologySnapshotReader = Callable[
    [Connection[object], PrincipalKey, str], TerminologySnapshot
]


@dataclass(frozen=True, slots=True)
class GovernedRagResult:
    answer: str
    proposal: KnowledgeProposal | None
    generation_sha256: str
    model_invoked: bool
    terminology_snapshot_sha256: str


class GovernedRagAgent:
    """Own retrieval-before-reasoning and citation-bound proposal admission."""

    def __init__(
        self,
        *,
        tools: GovernedKnowledgeTools,
        proposals: GovernedKnowledgeProposals,
        reasoning_routes: AgentReasoningRoutes,
        maximum_prompt_characters: int,
        maximum_output_characters: int,
        maximum_attempts: int = 2,
        read_terminology_snapshot: TerminologySnapshotReader | None = None,
    ) -> None:
        if not 1 <= maximum_prompt_characters <= 1_000_000:
            raise ValueError("RAG prompt bound is invalid")
        if maximum_attempts not in {1, 2}:
            raise ValueError("RAG attempt bound is invalid")
        if not 1 <= maximum_output_characters <= 100_000:
            raise ValueError("RAG output bound is invalid")
        self._tools = tools
        self._proposals = proposals
        self._reasoning_routes = reasoning_routes
        self._maximum_prompt_characters = maximum_prompt_characters
        self._maximum_output_characters = maximum_output_characters
        self._maximum_attempts = maximum_attempts
        self._read_terminology_snapshot = (
            read_terminology_snapshot or _read_job_terminology_snapshot
        )

    def answer(
        self,
        connection: Connection[object],
        *,
        principal: PrincipalKey,
        agent_id: str,
        purpose: str,
        question: str,
        job_id: str,
        workload_class: AgentWorkloadClass,
        cancellation: threading.Event,
        expected_generation_sha256: str | None = None,
    ) -> GovernedRagResult:
        try:
            validate_search_text(question)
        except ValueError as error:
            raise ValueError("RAG question is invalid") from error
        terminology = self._read_terminology_snapshot(connection, principal, job_id)
        if (
            terminology.tenant_id != principal.tenant_id
            or terminology.subject_id != principal.subject_id
        ):
            raise PermissionError("job terminology snapshot is unavailable")
        terminology_exact_forms = tuple(
            sorted({record.canonical_form for record in terminology.entries})
        )
        retrieval = self._tools.execute(
            connection,
            principal=principal,
            agent_id=agent_id,
            request=SearchKnowledgeRequest(
                purpose=purpose,
                search_text=question,
                expected_generation_sha256=expected_generation_sha256,
            ),
            cancellation=cancellation,
        )
        if not retrieval.items:
            return GovernedRagResult(
                "Evidence is unavailable.",
                None,
                retrieval.generation_sha256,
                False,
                terminology.snapshot_sha256,
            )
        prompt = _prompt(question, retrieval.items, terminology_exact_forms)
        if len(prompt) > self._maximum_prompt_characters:
            raise ValueError("RAG prompt exceeds its bound")
        parsed: tuple[str, tuple[str, ...]] | None = None
        for _attempt in range(self._maximum_attempts):
            if cancellation.is_set():
                raise KnowledgeToolCancelled("RAG request was cancelled")
            try:
                parsed = _reasoned_answer(
                    self._reasoning_routes.reason(
                        workload_class, prompt, cancellation
                    ),
                    self._maximum_output_characters,
                )
                _validate_reasoned_answer(parsed, retrieval.items, terminology_exact_forms)
                break
            except (ValueError, ReasoningRetryableError):
                parsed = None
        if parsed is None:
            raise ValueError("reasoning model did not produce an admissible answer")
        answer, citation_ids = parsed
        by_concept = {item.citation.concept_id: item for item in retrieval.items}
        citations = tuple(
            ProposalCitation(
                concept_id=concept_id,
                source_revision=by_concept[concept_id].citation.source_revision,
                content_sha256=by_concept[concept_id].citation.content_sha256,
                char_start=int(by_concept[concept_id].citation.char_start),
                char_end=int(by_concept[concept_id].citation.char_end),
            )
            for concept_id in citation_ids
        )
        proposal = self._proposals.propose(
            connection,
            principal=principal,
            agent_id=agent_id,
            purpose=purpose,
            proposal_type="summary",
            proposed_content=answer,
            source_citations=citations,
            expected_generation_sha256=retrieval.generation_sha256,
            cancellation=cancellation,
        )
        return GovernedRagResult(
            answer,
            proposal,
            retrieval.generation_sha256,
            True,
            terminology.snapshot_sha256,
        )


def _read_job_terminology_snapshot(
    connection: Connection[object], principal: PrincipalKey, job_id: str
) -> TerminologySnapshot:
    return read_job_terminology_snapshot(
        connection,
        principal=principal,
        job_id=job_id,
    )


def _prompt(question: str, items: tuple[object, ...], exact_forms: tuple[str, ...]) -> str:
    context = [
        {
            "conceptId": item.citation.concept_id,
            "text": item.text,
            "sourceRevision": item.citation.source_revision,
            "contentSha256": item.citation.content_sha256,
            "charStart": item.citation.char_start,
            "charEnd": item.citation.char_end,
        }
        for item in items
    ]
    return json.dumps(
        {
            "instruction": (
                "Answer only from context. Preserve listed terminology exactly. "
                "Return JSON with answer and citationConceptIds."
            ),
            "question": question,
            "terminologyExactForms": list(exact_forms),
            "context": context,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reasoned_answer(
    value: str, maximum_output_characters: int
) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or len(value) > maximum_output_characters:
        raise ValueError("reasoning output is invalid")
    try:
        result = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("reasoning output is not valid JSON") from error
    if not isinstance(result, dict) or set(result) != {"answer", "citationConceptIds"}:
        raise ValueError("reasoning output differs from the contract")
    answer = result["answer"]
    citations = result["citationConceptIds"]
    if (
        not isinstance(answer, str)
        or not answer
        or answer.strip() != answer
        or not isinstance(citations, list)
        or not citations
        or len(citations) > 100
        or not all(isinstance(item, str) for item in citations)
        or len(set(citations)) != len(citations)
    ):
        raise ValueError("reasoning output fields are invalid")
    return answer, tuple(citations)


def _validate_reasoned_answer(
    result: tuple[str, tuple[str, ...]],
    items: tuple[object, ...],
    exact_forms: tuple[str, ...],
) -> None:
    answer, citations = result
    visible = {item.citation.concept_id for item in items}
    if not set(citations) <= visible:
        raise ValueError("reasoning output cites unavailable evidence")
    source_text = " ".join(str(item.text or "") for item in items)
    required = tuple(term for term in exact_forms if term in source_text)
    if any(term not in answer for term in required):
        raise ValueError("reasoning output changed governed terminology")


__all__ = [
    "GovernedRagAgent",
    "GovernedRagResult",
    "TerminologySnapshotReader",
]
