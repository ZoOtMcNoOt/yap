from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict
import threading
from typing import Callable, TypeVar

import anyio
from mcp.server import MCPServer
from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .governed_knowledge_tools import GovernedKnowledgeTools
from .governed_knowledge_proposals import GovernedKnowledgeProposals
from .knowledge_proposals import ProposalCitation
from .knowledge_tool_contract import (
    BrowseKnowledgeRequest,
    ConceptId,
    GenerationSha256,
    KnowledgeToolRequest,
    KnowledgeToolCancellationFailed,
    KnowledgePurpose,
    ProposalContent,
    ProposalCitations,
    ProposalCitationInput,
    ProposalType,
    SearchResultLimit,
    SearchText,
    SearchKnowledgeRequest,
    TraversalDepth,
    TraversalResultLimit,
    TraverseKnowledgeRequest,
)


ConnectionFactory = Callable[[], AbstractContextManager[Connection[object]]]
ResultT = TypeVar("ResultT")


def create_governed_knowledge_mcp_server(
    *,
    tools: GovernedKnowledgeTools,
    proposals: GovernedKnowledgeProposals,
    connection_factory: ConnectionFactory,
    principal: PrincipalKey,
    agent_id: str,
) -> MCPServer:
    """Create an in-process MCP surface bound to server-authenticated authority."""

    server = MCPServer(
        name="yap-governed-knowledge",
        instructions=(
            "Read governed knowledge through permission-filtered, citation-bound "
            "operations. Identity and agent authority are supplied by Yap."
        ),
    )

    async def invoke(request: KnowledgeToolRequest) -> dict[str, object]:
        def execute(cancellation: threading.Event) -> dict[str, object]:
            with connection_factory() as connection:
                response = tools.execute(
                    connection,
                    principal=principal,
                    agent_id=agent_id,
                    request=request,
                    cancellation=cancellation,
                )
                return asdict(response)

        return await _run_acknowledged_database_call(execute)

    async def propose(
        *,
        purpose: KnowledgePurpose,
        proposal_type: ProposalType,
        proposed_content: ProposalContent,
        source_citations: ProposalCitations,
        expected_generation_sha256: GenerationSha256 | None,
    ) -> dict[str, object]:
        def execute(cancellation: threading.Event) -> dict[str, object]:
            with connection_factory() as connection:
                response = proposals.propose(
                    connection,
                    principal=principal,
                    agent_id=agent_id,
                    purpose=purpose,
                    proposal_type=proposal_type,
                    proposed_content=proposed_content,
                    source_citations=tuple(
                        _persisted_citation(item) for item in source_citations
                    ),
                    expected_generation_sha256=expected_generation_sha256,
                    cancellation=cancellation,
                )
                return asdict(response)

        return await _run_acknowledged_database_call(execute)

    @server.tool(name="search_knowledge", structured_output=True)
    async def search_knowledge(
        purpose: KnowledgePurpose,
        search_text: SearchText,
        maximum_results: SearchResultLimit = 10,
        expected_generation_sha256: GenerationSha256 | None = None,
    ) -> dict[str, object]:
        return await invoke(
            SearchKnowledgeRequest(
                purpose=purpose,
                search_text=search_text,
                maximum_results=maximum_results,
                expected_generation_sha256=expected_generation_sha256,
            )
        )

    @server.tool(name="browse_knowledge", structured_output=True)
    async def browse_knowledge(
        purpose: KnowledgePurpose,
        expected_generation_sha256: GenerationSha256 | None = None,
    ) -> dict[str, object]:
        return await invoke(
            BrowseKnowledgeRequest(
                purpose=purpose,
                expected_generation_sha256=expected_generation_sha256,
            )
        )

    @server.tool(name="traverse_knowledge", structured_output=True)
    async def traverse_knowledge(
        purpose: KnowledgePurpose,
        start_concept_id: ConceptId,
        maximum_depth: TraversalDepth = 2,
        maximum_results: TraversalResultLimit = 50,
        expected_generation_sha256: GenerationSha256 | None = None,
    ) -> dict[str, object]:
        return await invoke(
            TraverseKnowledgeRequest(
                purpose=purpose,
                start_concept_id=start_concept_id,
                maximum_depth=maximum_depth,
                maximum_results=maximum_results,
                expected_generation_sha256=expected_generation_sha256,
            )
        )

    @server.tool(name="propose_knowledge", structured_output=True)
    async def propose_knowledge(
        purpose: KnowledgePurpose,
        proposal_type: ProposalType,
        proposed_content: ProposalContent,
        source_citations: ProposalCitations,
        expected_generation_sha256: GenerationSha256 | None = None,
    ) -> dict[str, object]:
        return await propose(
            purpose=purpose,
            proposal_type=proposal_type,
            proposed_content=proposed_content,
            source_citations=source_citations,
            expected_generation_sha256=expected_generation_sha256,
        )

    return server


async def _run_acknowledged_database_call(
    execute: Callable[[threading.Event], ResultT],
) -> ResultT:
    cancellation = threading.Event()
    finished = threading.Event()
    outcome: list[ResultT | BaseException] = []

    def run() -> None:
        try:
            outcome.append(execute(cancellation))
        except BaseException as error:
            outcome.append(error)
        finally:
            finished.set()

    try:
        await anyio.to_thread.run_sync(run, abandon_on_cancel=True)
    except BaseException as cancellation_error:
        cancellation.set()
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(
                finished.wait,
                abandon_on_cancel=False,
            )
        if len(outcome) == 1 and isinstance(
            outcome[0], KnowledgeToolCancellationFailed
        ):
            raise outcome[0] from cancellation_error
        raise
    if len(outcome) != 1:
        raise RuntimeError("knowledge database worker did not produce one outcome")
    if isinstance(outcome[0], BaseException):
        raise outcome[0]
    return outcome[0]


def _persisted_citation(value: ProposalCitationInput) -> ProposalCitation:
    return ProposalCitation(
        concept_id=value.concept_id,
        source_revision=value.source_revision,
        content_sha256=value.content_sha256,
        char_start=value.char_start,
        char_end=value.char_end,
    )


__all__ = ["ConnectionFactory", "create_governed_knowledge_mcp_server"]
