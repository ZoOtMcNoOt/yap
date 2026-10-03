from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlencode
from uuid import uuid4

import psycopg

from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.knowledge_connections_service import (
    build_knowledge_connections_service,
)
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from tests.knowledge.knowledge_connections_fixtures import activate_connection_fixture
from tests.api import test_terminology_api as terminology_fixtures
from .api_fixtures import HealthServerTestCase

DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class KnowledgeConnectionsApiTests(HealthServerTestCase):
    server_settings = terminology_fixtures.TerminologyApiTests.server_settings

    def setUp(self) -> None:
        self.tenant = f"connection-api-{uuid4().hex}"
        self.request_authenticator = terminology_fixtures._Authentication(self.tenant)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        credential = Path(temporary.name) / "connections.dsn"
        credential.write_text(DSN, encoding="utf-8")
        credential.chmod(0o600)
        with psycopg.connect(DSN) as connection:
            install_knowledge_schema(connection)
            install_knowledge_tool_audit_schema(connection)
            self.generation = activate_connection_fixture(connection, self.tenant)
        self.addCleanup(self._clean_tenant)
        self.knowledge_connections_service = build_knowledge_connections_service(
            {
                "YAP_KNOWLEDGE_CONNECTIONS_RUNTIME": "postgres",
                "YAP_KNOWLEDGE_CONNECTIONS_DSN_FILE": str(credential),
            },
            authenticated_team_mode=True,
        )
        super().setUp()

    def _clean_tenant(self) -> None:
        with psycopg.connect(DSN) as connection:
            for table in [
                "yap_knowledge_active_builds",
                "yap_knowledge_builds",
                "yap_knowledge_tool_audit",
            ]:
                connection.execute(
                    f"DELETE FROM {table} WHERE tenant_id = %s", (self.tenant,)
                )

    def request(self, path, query, *, principal="alice", method="GET"):
        status, headers, body = self._request(
            path + "?" + urlencode(query, doseq=True),
            method=method,
            headers={}
            if principal is None
            else {"Authorization": f"Bearer {principal}"},
        )
        return status, headers, json.loads(body)

    def graph(self, concept="projects/voiceos", generation=None, principal="alice"):
        return self.request(
            "/v1/knowledge/connections",
            {
                "conceptId": concept,
                "generationSha256": generation or self.generation.generation_sha256,
            },
            principal=principal,
        )

    def test_capability_browse_graph_and_audit_work_without_model_services(
        self,
    ) -> None:
        health = json.loads(self._request("/v1/health")[2])
        self.assertTrue(health["capabilities"]["knowledgeConnections"])
        self.assertFalse(health["capabilities"]["librarianQueries"])
        status, headers, page = self.request("/v1/knowledge/concepts", {"search": ""})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(
            {node["title"] for node in page["nodes"]}, {"VoiceOS", "Public Decision"}
        )
        status, _, graph = self.graph()
        self.assertEqual(status, 200)
        self.assertEqual(len(graph["relationships"]), 2)
        self.assertEqual(graph["generationSha256"], page["generationSha256"])
        self.assertNotIn("secret/", json.dumps(graph))
        self.assertNotIn("agent_proposed", json.dumps(graph))
        from tests.contract import contract_schema_support as schema_support

        document = schema_support.load_json(
            Path(__file__).parents[2] / "openapi" / "openapi.json"
        )
        for result, schema in [
            (page, "KnowledgeConceptPage"),
            (graph, "KnowledgeConnections"),
        ]:
            schema_support.assert_schema_subset(
                result,
                document["components"]["schemas"][schema],
                document_name="openapi.json",
                documents={"openapi.json": document},
            )
        with psycopg.connect(DSN) as connection:
            rows = connection.execute(
                "SELECT agent_id, operation, outcome, result_count, generation_sha256 "
                "FROM yap_knowledge_tool_audit WHERE tenant_id = %s ORDER BY audit_id",
                (self.tenant,),
            ).fetchall()
        self.assertEqual(
            [row[1] for row in rows], ["browse-connections", "read-connections"]
        )
        self.assertTrue(
            all(
                row[0] == "knowledge-explorer" and row[2] == "succeeded" for row in rows
            )
        )
        self.assertTrue(all(row[4] == page["generationSha256"] for row in rows))

    def test_authentication_and_caller_claims_cannot_select_knowledge_authority(
        self,
    ) -> None:
        self.assertEqual(self.graph(principal=None)[0], 401)
        self.assertEqual(self.graph(principal="bob")[0], 404)
        self.assertEqual(self.graph("secret/launch")[0], 404)
        self.assertEqual(
            self.graph("secret/missing")[2]["message"],
            self.graph("secret/launch")[2]["message"],
        )
        status, _, page = self.request(
            "/v1/knowledge/concepts", {"search": ""}, principal="bob"
        )
        self.assertEqual(status, 200)
        self.assertEqual(page["nodes"], [])
        for claim in ["tenantId", "subjectId", "purpose", "agentCapabilities"]:
            self.assertEqual(
                self.request("/v1/knowledge/concepts", {"search": "", claim: "alice"})[
                    0
                ],
                400,
            )

    def test_topic_search_is_literal_bounded_and_private_in_logs(self) -> None:
        status, _, page = self.request("/v1/knowledge/concepts", {"search": "voiceos"})
        self.assertEqual(status, 200)
        self.assertEqual([node["title"] for node in page["nodes"]], ["VoiceOS"])
        for search in ["%", "_", "!", "UnpublishedPrivatePhrase"]:
            self.assertEqual(
                self.request("/v1/knowledge/concepts", {"search": search})[2]["nodes"],
                [],
            )
        for search in ["x" * 129, "\0", " padded "]:
            self.assertEqual(
                self.request("/v1/knowledge/concepts", {"search": search})[0], 400
            )
        self.assertNotIn("UnpublishedPrivatePhrase", " ".join(self.logger.messages))
        self.assertNotIn("Bearer", " ".join(self.logger.messages))

    def test_malformed_query_and_methods_are_refused(self) -> None:
        for query in [
            {},
            {"conceptId": "projects/voiceos"},
            {"conceptId": "projects/voiceos", "generationSha256": "bad"},
            {"conceptId": "x" * 513, "generationSha256": "0" * 64},
        ]:
            self.assertEqual(self.request("/v1/knowledge/connections", query)[0], 400)
        self.assertEqual(
            self.request("/v1/knowledge/concepts", {"search": ["one", "two"]})[0], 400
        )
        self.assertEqual(
            self._request(
                "/v1/knowledge/concepts?search=%FF",
                headers={"Authorization": "Bearer alice"},
            )[0],
            400,
        )
        for method in ["POST", "PUT", "DELETE"]:
            status, headers, _ = self.request(
                "/v1/knowledge/concepts", {"search": ""}, method=method
            )
            self.assertEqual(status, 405)
            self.assertEqual(headers["Allow"], "GET")

    def test_stale_generation_and_revocation_require_new_authorized_topics(
        self,
    ) -> None:
        self.assertEqual(self.graph(generation="0" * 64)[0], 409)
        with psycopg.connect(DSN) as connection:
            generation = activate_connection_fixture(
                connection, self.tenant, subject="bob"
            )
        self.assertEqual(self.graph()[0], 409)
        status, _, page = self.request("/v1/knowledge/concepts", {"search": ""})
        self.assertEqual(status, 200)
        self.assertEqual(page["nodes"], [])
        self.assertEqual(page["generationSha256"], generation.generation_sha256)
        self.assertEqual(self.graph(generation=generation.generation_sha256)[0], 404)

    def test_failed_reads_are_audited_without_query_or_source_content(self):
        self.assertEqual(self.graph("secret/launch")[0], 404)
        with psycopg.connect(DSN) as connection:
            rows = connection.execute(
                "SELECT outcome, result_count, generation_sha256, permission_hash, authorization_hash FROM yap_knowledge_tool_audit WHERE tenant_id = %s",
                (self.tenant,),
            ).fetchall()
        self.assertEqual(rows, [("failed", 0, None, None, None)])
        self.assertNotIn("secret/launch", " ".join(self.logger.messages))

    def test_concurrent_reads_are_bounded_and_busy_requests_can_retry(self):
        from yap_server.knowledge import knowledge_connections_service as runtime

        original = runtime.browse_postgres_knowledge_concepts
        entered = threading.Barrier(3)
        released = threading.Event()

        def blocked(*args, **kwargs):
            entered.wait(timeout=3)
            if not released.wait(timeout=3):
                raise RuntimeError("test request gate expired")
            return original(*args, **kwargs)

        with (
            patch.object(
                runtime, "browse_postgres_knowledge_concepts", side_effect=blocked
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            reads = [
                pool.submit(self.request, "/v1/knowledge/concepts", {"search": ""})
                for _ in range(2)
            ]
            try:
                entered.wait(timeout=3)
                status, _, body = self.request("/v1/knowledge/concepts", {"search": ""})
                self.assertEqual(status, 429)
                self.assertTrue(body["retryable"])
            finally:
                released.set()
            self.assertTrue(all(read.result(timeout=3)[0] == 200 for read in reads))
        self.assertEqual(self.request("/v1/knowledge/concepts", {"search": ""})[0], 200)

    def test_response_budget_rejects_large_unicode_metadata_without_partial_results(
        self,
    ):
        with psycopg.connect(DSN) as connection:
            self.generation = activate_connection_fixture(
                connection, self.tenant, neighbors=14
            )
            titles = connection.execute(
                "SELECT concept_id, frontmatter->>'title' FROM yap_knowledge_concepts WHERE tenant_id = %s AND generation_sha256 = %s",
                (self.tenant, self.generation.generation_sha256),
            ).fetchall()
            connection.execute(
                "UPDATE yap_knowledge_concepts SET frontmatter = jsonb_set(frontmatter, '{title}', to_jsonb(%s::text)) WHERE tenant_id = %s AND generation_sha256 = %s",
                ("🟣" * 1024, self.tenant, self.generation.generation_sha256),
            )
        for status, _, body in [
            self.graph(),
            self.request("/v1/knowledge/concepts", {"search": ""}),
        ]:
            self.assertEqual(status, 503)
            self.assertNotIn("nodes", body)
            self.assertNotIn("🟣", json.dumps(body, ensure_ascii=False))
        with psycopg.connect(DSN) as connection:
            for concept_id, title in titles:
                connection.execute(
                    "UPDATE yap_knowledge_concepts SET frontmatter = jsonb_set(frontmatter, '{title}', to_jsonb(%s::text)) WHERE tenant_id = %s AND generation_sha256 = %s AND concept_id = %s",
                    (title, self.tenant, self.generation.generation_sha256, concept_id),
                )
        self.assertEqual(self.graph()[0], 200)


if __name__ == "__main__":
    unittest.main()
