from __future__ import annotations

import dataclasses
import json
import time
from unittest.mock import patch

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_vector,
)
from yap_server.knowledge.vllm_reasoning_client import BoundedVllmJsonClient
from .test_knowledge_embedding_preparation_api import (
    KnowledgeEmbeddingPreparationApiTestCase,
    DSN,
)


class KnowledgeEmbeddingBatchApiTests(KnowledgeEmbeddingPreparationApiTestCase):
    def _write_reviewed_source(self):
        super()._write_reviewed_source()
        source = self.source_root / "projects/voiceos.md"
        source.write_text(
            source.read_text()
            + "\n\n"
            + "\n\n".join(
                f"Synthetic reviewed paragraph {index} café 🌱." for index in range(64)
            )
            + "\n",
            encoding="utf-8",
        )

    def stage_large_source(self):
        self.assertEqual(len(self.source_generation.chunks), 65)
        status, _, receipt = self.source_request("POST")
        self.assertEqual(status, 200)
        self.assertEqual(receipt["chunkCount"], 65)

    def test_complete_batched_source_can_publish_read_and_restore_without_regeneration(
        self,
    ):
        source_bytes = {
            p.relative_to(self.source_root): p.read_bytes()
            for p in self.source_root.rglob("*")
            if p.is_file()
        }
        self.stage_large_source()
        status, prepared = self.embeddings()
        self.assertEqual(status, 200)
        self.assertTrue(prepared["changed"])
        self.assertEqual(prepared["chunkCount"], 65)
        self.assertEqual(
            [len(body["input"]) for _, body in self.provider_requests], [64, 1]
        )
        self.assertEqual(
            [text for _, body in self.provider_requests for text in body["input"]],
            [c.text for c in self.source_generation.chunks],
        )
        self.assertFalse(self.embeddings()[1]["changed"])
        self.assertEqual(len(self.provider_requests), 2)
        self.assertEqual(
            self.request("POST", generation=self.source_generation.generation_sha256)[
                0
            ],
            200,
        )
        with psycopg.connect(DSN) as connection:
            count = connection.execute(
                "SELECT count(*) FROM yap_knowledge_chunks WHERE tenant_id = %s AND generation_sha256 = %s AND embedding IS NOT NULL",
                (self.tenant, self.source_generation.generation_sha256),
            ).fetchone()
            self.assertEqual(count, (65,))
            for subject in ("alice", "bob"):
                results = search_postgres_knowledge_vector(
                    connection,
                    principal=PrincipalKey(self.tenant, subject),
                    purpose="knowledge.read",
                    agent_capabilities=frozenset({"knowledge.search.vector"}),
                    query_embedding=(0.25,) * 768,
                ).results
                self.assertEqual(bool(results), subject == "alice")
                for result in results:
                    self.assertEqual(
                        result.generation_sha256,
                        self.source_generation.generation_sha256,
                    )
                    self.assertIn(
                        result.text, {c.text for c in self.source_generation.chunks}
                    )
        for actor in ("alice", "bob"):
            status, _, body = self._request(
                "/v1/knowledge/concepts?search=",
                headers={"Authorization": "Bearer " + actor},
            )
            self.assertEqual(status, 200)
            self.assertEqual(bool(json.loads(body)["nodes"]), actor == "alice")
        self.assertEqual(self.embeddings()[0], 409)
        self.assertEqual(len(self.provider_requests), 2)
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

    def test_later_invalid_batch_commits_nothing_and_explicit_retry_recovers(self):
        self.stage_large_source()
        before = self.snapshot()
        self.provider_settings["transform"] = lambda value: (
            {**value, "model": "private-wrong-model"}
            if len(self.provider_requests) == 2
            else value
        )
        status, error = self.embeddings()
        self.assertEqual(status, 409)
        self.assertNotIn("private-wrong-model", json.dumps(error))
        self.assertEqual(len(self.provider_requests), 2)
        self.assertEqual(self.snapshot(), before)
        self.provider_settings["transform"] = lambda value: value
        self.assertTrue(self.embeddings()[1]["changed"])
        self.assertEqual(len(self.provider_requests), 4)

    def test_one_total_deadline_discards_every_batch_and_all_metadata(self):
        self.stage_large_source()
        service = self.server.RequestHandlerClass.keywords[
            "knowledge_publication_service"
        ]
        service._embedding_provider = dataclasses.replace(
            service._embedding_provider,
            transport=BoundedVllmJsonClient(
                endpoint=self.environ["YAP_KNOWLEDGE_EMBEDDING_ENDPOINT"],
                timeout_seconds=1,
                maximum_response_bytes=2_000_000,
            ),
        )

        def delayed(value):
            time.sleep(0.65)
            return value

        self.provider_settings["transform"] = delayed
        before = self.snapshot()
        status, _error = self.embeddings()
        self.assertEqual(status, 503)
        self.assertEqual(len(self.provider_requests), 2)
        self.assertEqual(self.snapshot(), before)
        self.provider_settings["transform"] = lambda value: value
        self.assertEqual(self.embeddings()[0], 200)

    def test_failed_audit_rolls_back_complete_batched_vectors(self):
        self.stage_large_source()
        before = self.snapshot()
        with patch(
            "yap_server.knowledge.knowledge_publication_service.record_knowledge_tool_audit",
            side_effect=psycopg.OperationalError("Private audit failure"),
        ):
            status, error = self.embeddings()
        self.assertEqual(status, 503)
        self.assertNotIn("Private audit", json.dumps(error))
        self.assertEqual(len(self.provider_requests), 2)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.embeddings()[0], 200)
        self.assertEqual(len(self.provider_requests), 4)
