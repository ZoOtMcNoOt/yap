from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict
import threading
from typing import Callable

import anyio
from mcp.server import MCPServer
from psycopg import Connection

from yap_server.auth.principal import PrincipalKey

from .governed_knowledge_tools import GovernedKnowledgeTools
from .governed_knowledge_proposals import GovernedKnowledgeProposals
from .knowledge_proposals import ProposalCitation
from .knowledge_tool_contract import (
    BrowseKnowledgeRequest,
    KnowledgeToolRequest,
    SearchKnowledgeRequest,
    TraverseKnowledgeRequest,
)


ConnectionFactory = Callable[[], AbstractContextManager[Connection[object]]]


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
        cancellation = threading.Event()

        def execute() -> dict[str, object]:
            with connection_factory() as connection:
                response = tools.execute(
                    connection,
                    principal=principal,
                    agent_id=agent_id,
                    request=request,
                    cancellation=cancellation,
                )
                return asdict(response)

        try:
            return await anyio.to_thread.run_sync(execute, abandon_on_cancel=True)
        except BaseException:
            cancellation.set()
            raise

    async def propose(
        *,
        purpose: str,
        proposal_type: str,
        proposed_content: str,
        source_citations: list[ProposalCitation],
        expected_generation_sha256: str | None,
    ) -> dict[str, object]:
        cancellation = threading.Event()

        def execute() -> dict[str, object]:
            with connection_factory() as connection:
                response = proposals.propose(
                    connection,
                    principal=principal,
                    agent_id=agent_id,
                    purpose=purpose,
                    proposal_type=proposal_type,
                    proposed_content=proposed_content,
                    source_citations=tuple(source_citations),
                    expected_generation_sha256=expected_generation_sha256,
                    cancellation=cancellation,
                )
                return asdict(response)

        try:
            return await anyio.to_thread.run_sync(execute, abandon_on_cancel=True)
        except BaseException:
            cancellation.set()
            raise

    @server.tool(name="search_knowledge", structured_output=True)
    async def search_knowledge(
        purpose: str,
        search_text: str,
        maximum_results: int = 10,
        expected_generation_sha256: str | None = None,
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
        purpose: str,
        expected_generation_sha256: str | None = None,
    ) -> dict[str, object]:
        return await invoke(
            BrowseKnowledgeRequest(
                purpose=purpose,
                expected_generation_sha256=expected_generation_sha256,
            )
        )

    @server.tool(name="traverse_knowledge", structured_output=True)
    async def traverse_knowledge(
        purpose: str,
        start_concept_id: str,
        maximum_depth: int = 2,
        maximum_results: int = 50,
        expected_generation_sha256: str | None = None,
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
        purpose: str,
        proposal_type: str,
        proposed_content: str,
        source_citations: list[ProposalCitation],
        expected_generation_sha256: str | None = None,
    ) -> dict[str, object]:
        return await propose(
            purpose=purpose,
            proposal_type=proposal_type,
            proposed_content=proposed_content,
            source_citations=source_citations,
            expected_generation_sha256=expected_generation_sha256,
        )

    return server


__all__ = ["ConnectionFactory", "create_governed_knowledge_mcp_server"]
