from __future__ import annotations

from contextlib import nullcontext
import threading
import unittest

import anyio
from mcp import Client

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.governed_knowledge_mcp import (
    create_governed_knowledge_mcp_server,
)
from yap_server.knowledge.knowledge_proposals import KnowledgeProposal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolResponse,
    SearchKnowledgeRequest,
)


class _RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def execute(
        self,
        connection: object,
        *,
        principal: PrincipalKey,
        agent_id: str,
        request: object,
        cancellation: threading.Event,
    ) -> KnowledgeToolResponse:
        self.calls.append((connection, principal, agent_id, request, cancellation))
        return KnowledgeToolResponse(
            operation="search",
            generation_sha256="a" * 64,
            permission_hash="b" * 64,
            authorization_hash="c" * 64,
            items=(),
            output_budget_exhausted=False,
        )


class _RecordingProposals:
    def propose(self, connection: object, **kwargs: object) -> KnowledgeProposal:
        return KnowledgeProposal(
            tenant_id="tenant-1",
            proposal_id="d" * 64,
            generation_sha256="a" * 64,
            proposal_type=str(kwargs["proposal_type"]),
            proposed_content=str(kwargs["proposed_content"]),
            source_citations=tuple(kwargs["source_citations"]),  # type: ignore[arg-type]
            inherited_permission_sha256="e" * 64,
            permission_hash="b" * 64,
            authorization_hash="c" * 64,
            status="proposed",
        )


class GovernedKnowledgeMcpTests(unittest.TestCase):
    def test_in_process_tools_bind_identity_outside_model_arguments(self) -> None:
        anyio.run(self._exercise_server)

    async def _exercise_server(self) -> None:
        tools = _RecordingTools()
        connection = object()
        principal = PrincipalKey("tenant-1", "person-1")
        server = create_governed_knowledge_mcp_server(
            tools=tools,  # type: ignore[arg-type]
            proposals=_RecordingProposals(),  # type: ignore[arg-type]
            connection_factory=lambda: nullcontext(connection),  # type: ignore[arg-type]
            principal=principal,
            agent_id="meeting-agent",
        )

        async with Client(server, raise_exceptions=True) as client:
            listed = await client.list_tools()
            for tool in listed.tools:
                properties = tool.input_schema["properties"]
                self.assertNotIn("tenant_id", properties)
                self.assertNotIn("subject_id", properties)
                self.assertNotIn("agent_id", properties)

            result = await client.call_tool(
                "search_knowledge",
                {"purpose": "meeting", "search_text": "cardiac"},
            )
            proposal_result = await client.call_tool(
                "propose_knowledge",
                {
                    "purpose": "meeting",
                    "proposal_type": "summary",
                    "proposed_content": "Cited summary.",
                    "source_citations": [
                        {
                            "concept_id": "meeting-1",
                            "source_revision": "revision-1",
                            "content_sha256": "f" * 64,
                            "char_start": 0,
                            "char_end": 5,
                        }
                    ],
                },
            )

        self.assertFalse(result.is_error, result.content)
        self.assertEqual(result.structured_content["generation_sha256"], "a" * 64)
        self.assertFalse(proposal_result.is_error, proposal_result.content)
        self.assertEqual(proposal_result.structured_content["status"], "proposed")
        self.assertEqual(len(tools.calls), 1)
        used_connection, used_principal, used_agent, request, cancellation = tools.calls[0]
        self.assertIs(used_connection, connection)
        self.assertEqual(used_principal, principal)
        self.assertEqual(used_agent, "meeting-agent")
        self.assertEqual(
            request,
            SearchKnowledgeRequest(purpose="meeting", search_text="cardiac"),
        )
        self.assertIsInstance(cancellation, threading.Event)


if __name__ == "__main__":
    unittest.main()
