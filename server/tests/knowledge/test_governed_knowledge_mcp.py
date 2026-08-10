from __future__ import annotations

from contextlib import nullcontext
import threading
import unittest

import anyio
from mcp import Client

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.governed_knowledge_mcp import (
    _run_acknowledged_database_call,
    create_governed_knowledge_mcp_server,
)
from yap_server.knowledge.knowledge_proposals import KnowledgeProposal
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeToolCancellationFailed,
    KnowledgeToolCancelled,
    KnowledgeToolResponse,
    SearchKnowledgeRequest,
    governed_agent_tool_definitions,
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
    def test_mcp_schema_uses_the_frozen_product_tool_bounds(self) -> None:
        anyio.run(self._exercise_schema_bounds)

    async def _exercise_schema_bounds(self) -> None:
        server = create_governed_knowledge_mcp_server(
            tools=_RecordingTools(),  # type: ignore[arg-type]
            proposals=_RecordingProposals(),  # type: ignore[arg-type]
            connection_factory=lambda: nullcontext(object()),  # type: ignore[arg-type]
            principal=PrincipalKey("tenant-1", "person-1"),
            agent_id="meeting-agent",
        )
        expected = {
            item["function"]["name"]: item["function"]["parameters"]
            for item in governed_agent_tool_definitions()
        }
        async with Client(server, raise_exceptions=True) as client:
            listed = {item.name: item.input_schema for item in (await client.list_tools()).tools}

        for name in expected:
            self.assertEqual(set(listed[name]["properties"]), set(expected[name]["properties"]))
        self.assertEqual(
            listed["search_knowledge"]["properties"]["search_text"]["maxLength"],
            expected["search_knowledge"]["properties"]["search_text"]["maxLength"],
        )
        self.assertEqual(
            listed["search_knowledge"]["properties"]["maximum_results"]["maximum"],
            expected["search_knowledge"]["properties"]["maximum_results"]["maximum"],
        )
        self.assertEqual(
            listed["traverse_knowledge"]["properties"]["maximum_depth"]["maximum"],
            expected["traverse_knowledge"]["properties"]["maximum_depth"]["maximum"],
        )
        self.assertEqual(
            listed["propose_knowledge"]["properties"]["proposed_content"]["maxLength"],
            expected["propose_knowledge"]["properties"]["proposed_content"]["maxLength"],
        )

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
                {"purpose": "knowledge.read", "search_text": "cardiac"},
            )
            proposal_result = await client.call_tool(
                "propose_knowledge",
                {
                    "purpose": "knowledge.read",
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
            SearchKnowledgeRequest(purpose="knowledge.read", search_text="cardiac"),
        )
        self.assertIsInstance(cancellation, threading.Event)

    def test_async_cancellation_waits_for_database_worker_exit(self) -> None:
        anyio.run(self._exercise_acknowledged_cancellation)

    async def _exercise_acknowledged_cancellation(self) -> None:
        started = threading.Event()
        exited = threading.Event()
        scopes: list[anyio.CancelScope] = []
        outcomes: list[str] = []

        def execute(cancellation: threading.Event) -> None:
            started.set()
            cancellation.wait()
            exited.set()
            raise KnowledgeToolCancelled("cancelled")

        async def call() -> None:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                try:
                    await _run_acknowledged_database_call(execute)
                except anyio.get_cancelled_exc_class():
                    outcomes.append("cancelled")

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(call)
            await anyio.to_thread.run_sync(started.wait)
            scopes[0].cancel()

        self.assertEqual(outcomes, ["cancelled"])
        self.assertTrue(exited.is_set())

    def test_async_cancellation_surfaces_database_cancellation_failure(self) -> None:
        anyio.run(self._exercise_failed_cancellation)

    async def _exercise_failed_cancellation(self) -> None:
        started = threading.Event()
        scopes: list[anyio.CancelScope] = []
        outcomes: list[str] = []

        def execute(cancellation: threading.Event) -> None:
            started.set()
            cancellation.wait()
            raise KnowledgeToolCancellationFailed("cancel failed")

        async def call() -> None:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                try:
                    await _run_acknowledged_database_call(execute)
                except KnowledgeToolCancellationFailed:
                    outcomes.append("failed")

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(call)
            await anyio.to_thread.run_sync(started.wait)
            scopes[0].cancel()

        self.assertEqual(outcomes, ["failed"])


if __name__ == "__main__":
    unittest.main()
