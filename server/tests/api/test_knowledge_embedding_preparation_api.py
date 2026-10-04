from __future__ import annotations

import json
from pathlib import Path
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

import psycopg

from yap_server.knowledge.generation_ledger import store_generation_embeddings
from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_vector,
)
from yap_server.knowledge.knowledge_publication_service import (
    build_knowledge_publication_service,
)

from tests.knowledge.embedding_provider_fixtures import embedding_server

from .test_knowledge_source_preparation_api import (
    KnowledgeSourcePreparationApiTestCase,
    DSN,
)


PATH = "/v1/knowledge/embedding-preparations"


class KnowledgeEmbeddingPreparationApiTests(KnowledgeSourcePreparationApiTestCase):
    def _build_publication_service(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        endpoint, self.provider_requests, self.provider_settings = stack.enter_context(
            embedding_server()
        )
        self.environ.update(
            YAP_KNOWLEDGE_EMBEDDING_ENDPOINT=endpoint,
            YAP_KNOWLEDGE_EMBEDDING_MODEL_ID="fixture-embedding",
            YAP_KNOWLEDGE_EMBEDDING_MODEL_REVISION="a" * 64,
        )
        return super()._build_publication_service()

    def embeddings(self, *, actor="alice", generation=None, payload=None):
        headers = {"Content-Type": "application/json"}
        if actor is not None:
            headers["Authorization"] = "Bearer " + actor
        status, _, body = self._request(
            PATH,
            method="POST",
            data=json.dumps(
                payload
                if payload is not None
                else {
                    "schemaVersion": 1,
                    "generationSha256": generation
                    or self.source_generation.generation_sha256,
                }
            ).encode(),
            headers=headers,
            timeout=15,
        )
        return status, json.loads(body)

    def test_reviewed_source_can_generate_vectors_before_explicit_publication(self):
        source_bytes = {
            p.relative_to(self.source_root): p.read_bytes()
            for p in self.source_root.rglob("*")
            if p.is_file()
        }
        self.assertEqual(self.source_request("POST")[0], 200)
        self.assertEqual(
            self.request("POST", generation=self.source_generation.generation_sha256)[
                0
            ],
            409,
        )
        before = self.snapshot()
        status, receipt = self.embeddings()
        self.assertEqual(status, 200, receipt)
        self.assertTrue(receipt["changed"])
        self.assertEqual(receipt["status"], "prepared")
        self.assertEqual(receipt["embeddingModelRevision"], "a" * 64)
        self.assertEqual(
            self.provider_requests[0],
            (
                "/v1/embeddings",
                {
                    "model": "fixture-embedding",
                    "input": [c.text for c in self.source_generation.chunks],
                    "encoding_format": "float",
                },
            ),
        )
        after = self.snapshot()
        self.assertEqual(after[:2], before[:2])
        self.assertEqual(after[3], before[3])
        self.assertEqual(after[5][1:7], before[5][1:7])
        self.assertEqual(after[5][8:], before[5][8:])
        self.assertEqual(
            after[4][-1],
            ("knowledge-publication", "prepare-generation-embeddings", "succeeded"),
        )
        self.assertEqual(
            self.request("GET", generation=self.source_generation.generation_sha256)[2][
                "status"
            ],
            "staged",
        )
        self.server.RequestHandlerClass.keywords["knowledge_publication_service"] = (
            build_knowledge_publication_service(
                self.environ, authenticated_team_mode=True
            )
        )
        replay_before = self.snapshot()
        self.assertFalse(self.embeddings()[1]["changed"])
        self.assertEqual(self.snapshot()[:4], replay_before[:4])
        self.assertEqual(len(self.provider_requests), 1)
        self.assertEqual(
            self.request("POST", generation=self.source_generation.generation_sha256)[
                0
            ],
            200,
        )
        with psycopg.connect(DSN) as connection:
            for subject, expected_count in (("alice", 1), ("bob", 0)):
                retrieved = search_postgres_knowledge_vector(
                    connection,
                    principal=PrincipalKey(self.tenant, subject),
                    purpose="knowledge.read",
                    agent_capabilities=frozenset({"knowledge.search.vector"}),
                    query_embedding=(0.25,) * 768,
                )
                self.assertEqual(len(retrieved.results), expected_count)
                if retrieved.results:
                    self.assertEqual(
                        retrieved.results[0].text, self.source_generation.chunks[0].text
                    )
                    self.assertEqual(
                        retrieved.results[0].generation_sha256,
                        self.source_generation.generation_sha256,
                    )
        status, _, body = self._request(
            "/v1/knowledge/concepts?search=", headers={"Authorization": "Bearer alice"}
        )
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(
            json.loads(body)["generationSha256"],
            self.source_generation.generation_sha256,
        )
        self.assertEqual(len(json.loads(body)["nodes"]), 2)
        status, _, body = self._request(
            "/v1/knowledge/concepts?search=", headers={"Authorization": "Bearer bob"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["nodes"], [])
        self.assertEqual(self.embeddings()[0], 409)
        self.assertEqual(len(self.provider_requests), 1)
        self.assertEqual(
            self.source_request(
                "POST",
                path="/v1/knowledge/rollbacks",
                payload={
                    "schemaVersion": 1,
                    "generationSha256": self.base.generation_sha256,
                    "expectedActiveGenerationSha256": self.source_generation.generation_sha256,
                },
            )[0],
            200,
        )
        self.assertEqual(
            self.request("GET", generation=self.base.generation_sha256)[2]["status"],
            "active",
        )
        self.assertEqual(
            source_bytes,
            {
                p.relative_to(self.source_root): p.read_bytes()
                for p in self.source_root.rglob("*")
                if p.is_file()
            },
        )
        from tests.contract import contract_schema_support as support

        document = support.load_json(Path(__file__).parents[2] / "openapi/openapi.json")
        support.assert_schema_subset(
            receipt,
            document["components"]["schemas"]["KnowledgeEmbeddingPreparationReceipt"],
            document_name="openapi.json",
            documents={"openapi.json": document},
        )

    def test_authority_and_unknown_source_refuse_without_provider_dispatch(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        before = self.snapshot()
        for actor, expected in (
            (None, 401),
            ("reader", 403),
            ("bob", 404),
            ("foreign", 404),
        ):
            self.assertEqual(self.embeddings(actor=actor)[0], expected)
            if expected == 404:
                self.assertEqual(
                    self.embeddings(actor=actor)[1]["code"],
                    self.embeddings(actor=actor, generation="0" * 64)[1]["code"],
                )
        self.assertEqual(self.embeddings(generation="0" * 64)[0], 404)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.provider_requests, [])

    def test_damaged_source_admission_counts_and_partial_vectors_refuse_before_dispatch(
        self,
    ):
        self.assertEqual(self.source_request("POST")[0], 200)
        mutations = (
            ("yap_knowledge_concepts", "body", "Private corrupt source"),
            ("yap_knowledge_source_admissions", "review_authority_sha256", "0" * 64),
            ("yap_knowledge_builds", "chunk_count", 900),
            ("yap_knowledge_chunks", "embedding_model_id", "Private partial model"),
        )
        for table, field, value in mutations:
            with self.subTest(field=field):
                with psycopg.connect(DSN) as connection:
                    # The source fixture has one nonempty body/chunk; constrain the concept explicitly.
                    extra = (
                        " AND concept_id = 'projects/voiceos'"
                        if table == "yap_knowledge_concepts"
                        else ""
                    )
                    original = connection.execute(
                        f"SELECT {field} FROM {table} WHERE tenant_id = %s AND generation_sha256 = %s{extra}",
                        (self.tenant, self.source_generation.generation_sha256),
                    ).fetchone()[0]
                    connection.execute(
                        f"UPDATE {table} SET {field} = %s WHERE tenant_id = %s AND generation_sha256 = %s{extra}",
                        (value, self.tenant, self.source_generation.generation_sha256),
                    )
                before = self.snapshot()
                status, error = self.embeddings()
                self.assertEqual(status, 409)
                self.assertNotIn("Private", json.dumps(error))
                self.assertEqual(self.snapshot(), before)
                with psycopg.connect(DSN) as connection:
                    connection.execute(
                        f"UPDATE {table} SET {field} = %s WHERE tenant_id = %s AND generation_sha256 = %s{extra}",
                        (
                            original,
                            self.tenant,
                            self.source_generation.generation_sha256,
                        ),
                    )
        self.assertEqual(self.provider_requests, [])

    def test_bad_provider_output_and_unavailability_leave_no_partial_projection(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        before = self.snapshot()
        self.provider_settings["transform"] = lambda value: {**value, "data": []}
        self.assertEqual(self.embeddings()[0], 409)
        self.assertEqual(self.snapshot(), before)
        self.provider_settings["transform"] = lambda value: {
            **value,
            "data": [{**item, "embedding": [10**400] * 768} for item in value["data"]],
        }
        self.assertEqual(self.embeddings()[0], 409)
        self.assertEqual(self.snapshot(), before)
        self.provider_settings["transform"] = lambda value: value
        self.provider_settings["status"] = 503
        self.assertEqual(self.embeddings()[0], 503)
        self.assertEqual(self.snapshot(), before)
        self.provider_settings["status"] = 200
        self.assertEqual(self.embeddings()[0], 200)

    def test_failed_success_audit_rolls_back_vectors_and_all_metadata(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        before = self.snapshot()
        with patch(
            "yap_server.knowledge.knowledge_publication_service.record_knowledge_tool_audit",
            side_effect=psycopg.OperationalError("Private audit failure"),
        ):
            status, error = self.embeddings()
        self.assertEqual(status, 503)
        self.assertNotIn("Private audit", json.dumps(error))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.embeddings()[0], 200)
        self.assertEqual(len(self.provider_requests), 2)

    def test_concurrent_preparation_calls_provider_once_and_never_activates(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        before = self.snapshot()
        barrier = threading.Barrier(2)

        def prepare():
            barrier.wait(2)
            return self.embeddings()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [
                f.result(5) for f in (pool.submit(prepare), pool.submit(prepare))
            ]
        self.assertEqual([r[0] for r in results], [200, 200])
        self.assertEqual(sorted(r[1]["changed"] for r in results), [False, True])
        self.assertEqual(len(self.provider_requests), 1)
        self.assertEqual(self.snapshot()[:2], before[:2])

    def test_lock_timeout_has_no_late_provider_or_vector_mutation(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        before = self.snapshot()
        with psycopg.connect(DSN) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (self.tenant,),
                )
                self.assertEqual(self.embeddings()[0], 503)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.provider_requests, [])
        self.assertEqual(self.embeddings()[0], 200)

    def test_conflicting_and_previously_published_models_are_never_rewritten(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        with psycopg.connect(DSN) as connection:
            store_generation_embeddings(
                connection,
                tenant_id=self.tenant,
                generation_sha256=self.source_generation.generation_sha256,
                embedding_model_id="different-model",
                embedding_model_revision="other-revision",
                embeddings={
                    c.chunk_id: (0.5,) * 768 for c in self.source_generation.chunks
                },
            )
        before = self.snapshot()
        self.assertEqual(self.embeddings()[0], 409)
        self.assertEqual(
            self.embeddings(generation=self.base.generation_sha256)[0], 409
        )
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.provider_requests, [])

    def test_strict_request_methods_disabled_runtime_and_content_free_logs(self):
        before = self.snapshot()
        for extra in (
            "tenantId",
            "source",
            "embeddings",
            "endpoint",
            "modelId",
            "modelRevision",
            "approval",
        ):
            self.assertEqual(
                self.embeddings(
                    payload={
                        "schemaVersion": 1,
                        "generationSha256": self.source_generation.generation_sha256,
                        extra: "PrivateCallerClaim",
                    }
                )[0],
                400,
            )
        for method in ("GET", "DELETE"):
            self.assertEqual(self._request(PATH, method=method)[0], 405)
        self.assertEqual(
            self.source_request("POST", path=PATH + "?source=PrivateCallerClaim")[0],
            400,
        )
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("PrivateCallerClaim", "\n".join(self.logger.messages))
        environ = {
            k: v
            for k, v in self.environ.items()
            if not k.startswith("YAP_KNOWLEDGE_EMBEDDING_")
        }
        self.server.RequestHandlerClass.keywords["knowledge_publication_service"] = (
            build_knowledge_publication_service(environ, authenticated_team_mode=True)
        )
        self.assertEqual(self.embeddings()[0], 501)
        self.assertEqual(self.provider_requests, [])
