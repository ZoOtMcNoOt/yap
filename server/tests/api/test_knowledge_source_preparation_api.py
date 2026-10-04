from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
from unittest.mock import patch

import psycopg

from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    prune_inactive_generations,
    rollback_to_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_publication_service import (
    build_knowledge_publication_service,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.reviewed_source_snapshot import ReviewedSourceSnapshot
from . import test_knowledge_publication_api as publication_fixtures


PATH = "/v1/knowledge/source-preparations"
DSN = publication_fixtures.DSN


class KnowledgeSourcePreparationApiTestCase(
    publication_fixtures.PublicationApiTestCase
):
    def snapshot(self):
        with psycopg.connect(DSN) as connection:
            stored = tuple(
                connection.execute(
                    f"SELECT to_jsonb(record) FROM {table} AS record WHERE tenant_id = %s ORDER BY to_jsonb(record)::text",
                    (self.tenant,),
                ).fetchall()
                for table in (
                    "yap_knowledge_builds",
                    "yap_knowledge_source_admissions",
                    "yap_knowledge_concepts",
                    "yap_knowledge_permissions",
                    "yap_knowledge_permission_audience",
                    "yap_knowledge_permission_denials",
                    "yap_knowledge_permission_purposes",
                    "yap_knowledge_chunks",
                    "yap_knowledge_relationships",
                    "yap_knowledge_active_builds",
                    "yap_knowledge_activation_history",
                    "yap_knowledge_proposals",
                )
            )
        return super().snapshot() + (stored,)

    def _build_publication_service(self):
        self.source_root = self.root / "reviewed-source"
        self.source_root.mkdir()
        publication_fixtures._tamper_bundle(self.source_root, self.tenant)
        self.source_generation = compile_okf_bundle(
            self.source_root,
            tenant_id=self.tenant,
            source_revision="deployment-reviewed-source",
        )
        self.manifest_path = self.root / "source.json"
        manifest = {
            "schemaVersion": 1,
            "tenantId": self.tenant,
            "bundleRoot": str(self.source_root),
            "repositoryRevision": self.source_generation.source_revision,
            "sourcePath": "knowledge/reviewed-source",
            "generationSha256": self.source_generation.generation_sha256,
        }
        body = json.dumps(manifest).encode()
        self.manifest_path.write_bytes(body)
        self.environ.update(
            YAP_KNOWLEDGE_REVIEWED_SOURCE_FILE=str(self.manifest_path),
            YAP_KNOWLEDGE_REVIEWED_SOURCE_SHA256=hashlib.sha256(body).hexdigest(),
        )
        return super()._build_publication_service()

    def source_request(
        self,
        method="GET",
        *,
        actor="alice",
        payload=None,
        path=PATH,
        data=None,
        headers=None,
    ):
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        if actor is not None:
            request_headers["Authorization"] = "Bearer " + actor
        if method == "POST" and data is None:
            data = json.dumps(
                payload
                if payload is not None
                else {
                    "schemaVersion": 1,
                    "expectedGenerationSha256": self.source_generation.generation_sha256,
                }
            ).encode()
        status, response_headers, body = self._request(
            path, method=method, headers=request_headers, data=data, timeout=5
        )
        return status, response_headers, json.loads(body)

    def embed_and_activate_source(self):
        generation = self.source_generation
        with psycopg.connect(DSN) as connection:
            store_generation_embeddings(
                connection,
                tenant_id=self.tenant,
                generation_sha256=generation.generation_sha256,
                embedding_model_id="synthetic-test",
                embedding_model_revision="fixture-1",
                embeddings={
                    chunk.chunk_id: (0.5,) * 768 for chunk in generation.chunks
                },
            )
            activate_complete_generation(
                connection,
                tenant_id=self.tenant,
                generation_sha256=generation.generation_sha256,
            )


class KnowledgeSourcePreparationApiTests(KnowledgeSourcePreparationApiTestCase):
    def test_explicit_inspection_preparation_replay_and_restart_without_embeddings(
        self,
    ):
        before = self.snapshot()
        sources = {
            path.relative_to(self.source_root): path.read_bytes()
            for path in self.source_root.rglob("*")
            if path.is_file()
        }
        status, headers, view = self.source_request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(view["status"], "unadmitted")
        self.assertEqual(view["activeGenerationSha256"], self.base.generation_sha256)
        self.assertNotIn("bundleRoot", view)
        self.assertEqual(self.snapshot()[:4], before[:4])
        status, _, receipt = self.source_request("POST")
        self.assertEqual(status, 200)
        self.assertEqual(receipt["status"], "staged")
        self.assertTrue(receipt["changed"])
        from tests.contract import contract_schema_support as schema_support

        document = schema_support.load_json(
            Path(__file__).parents[2] / "openapi/openapi.json"
        )
        for result, schema in (
            (view, "KnowledgeSourcePreparationView"),
            (receipt, "KnowledgeSourcePreparationReceipt"),
        ):
            schema_support.assert_schema_subset(
                result,
                document["components"]["schemas"][schema],
                document_name="openapi.json",
                documents={"openapi.json": document},
            )
        after = self.snapshot()
        self.assertEqual(after[:2], before[:2])
        self.assertTrue(
            any(
                row[0] == self.source_generation.generation_sha256 and row[3] is None
                for row in after[2]
            )
        )
        self.assertEqual(self.source_request("POST")[2]["changed"], False)
        self.assertEqual(self.snapshot()[:4], after[:4])
        self.assertEqual(self.snapshot()[5], after[5])
        restarted = build_knowledge_publication_service(
            self.environ, authenticated_team_mode=True
        )
        self.assertEqual(
            restarted.inspect_source(principal=self.principal)["status"], "staged"
        )
        self.assertEqual(
            self.request("POST", generation=self.source_generation.generation_sha256)[
                0
            ],
            409,
        )
        self.assertEqual(self.snapshot()[:4], after[:4])
        self.assertEqual(
            {
                path.relative_to(self.source_root): path.read_bytes()
                for path in self.source_root.rglob("*")
                if path.is_file()
            },
            sources,
        )
        self.assertEqual(
            after[4][-1][:2], ("knowledge-publication", "prepare-reviewed-source")
        )

    def test_auth_role_and_configured_tenant_refuse_before_source_reads(self):
        before = self.snapshot()
        with patch(
            "yap_server.knowledge.reviewed_source_snapshot.ReviewedSourceSnapshot.compile",
            side_effect=AssertionError("unexpected source read"),
        ):
            for method in ("GET", "POST"):
                self.assertEqual(self.source_request(method, actor=None)[0], 401)
                self.assertEqual(self.source_request(method, actor="reader")[0], 403)
                self.assertEqual(self.source_request(method, actor="foreign")[0], 404)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.source_request("POST")[0], 200)
        before = self.snapshot()
        for method in ("GET", "POST"):
            status, _, response = self.source_request(method, actor="bob")
            self.assertEqual(status, 404)
            self.assertNotIn("sourcePath", response)
        self.assertEqual(self.snapshot(), before)

    def test_source_drift_and_stale_intent_never_create_admission_or_staging(self):
        before = self.snapshot()
        stale = {"schemaVersion": 1, "expectedGenerationSha256": "a" * 64}
        self.assertEqual(self.source_request("POST", payload=stale)[0], 409)
        source = self.source_root / "projects/voiceos.md"
        source.write_bytes(source.read_bytes() + b"\nPrivate changed source body.\n")
        for method in ("GET", "POST"):
            status, _, response = self.source_request(method)
            self.assertEqual(status, 409)
            self.assertNotIn("Private", json.dumps(response))
            self.assertNotIn(str(self.source_root), json.dumps(response))
        self.assertEqual(self.snapshot(), before)

    def test_failed_success_audit_rolls_back_admission_and_all_staging(self):
        before = self.snapshot()
        with patch(
            "yap_server.knowledge.knowledge_publication_service.record_knowledge_tool_audit",
            side_effect=psycopg.OperationalError("private audit details"),
        ):
            status, _, response = self.source_request("POST")
        self.assertEqual(status, 503)
        self.assertNotIn("private audit", json.dumps(response))
        self.assertIn("Inspect", response["message"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.source_request("POST")[0], 200)

    def test_replay_refuses_damaged_staging_without_repair(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        for table, assignment in (
            ("yap_knowledge_builds", "concept_count = concept_count + 1"),
            (
                "yap_knowledge_source_admissions",
                "review_authority_sha256 = repeat('f', 64)",
            ),
        ):
            with psycopg.connect(DSN) as connection:
                connection.execute(
                    f"UPDATE {table} SET {assignment} WHERE tenant_id = %s AND generation_sha256 = %s",
                    (self.tenant, self.source_generation.generation_sha256),
                )
            before = self.snapshot()
            self.assertEqual(self.source_request("POST")[0], 409)
            self.assertEqual(self.snapshot(), before)

    def test_active_and_retained_replay_preserve_vectors_and_history(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        self.embed_and_activate_source()
        before = self.snapshot()
        status, _, response = self.source_request("POST")
        self.assertEqual(
            (status, response["status"], response["changed"]), (200, "active", False)
        )
        self.assertEqual(self.snapshot()[:4], before[:4])
        with psycopg.connect(DSN) as connection:
            rollback_to_generation(
                connection,
                tenant_id=self.tenant,
                generation_sha256=self.base.generation_sha256,
            )
        before = self.snapshot()
        status, _, response = self.source_request("POST")
        self.assertEqual(
            (status, response["status"], response["changed"]), (200, "retained", False)
        )
        self.assertEqual(self.snapshot()[:4], before[:4])

    def test_pruned_published_identity_requires_explicit_restore(self):
        self.assertEqual(self.source_request("POST")[0], 200)
        self.embed_and_activate_source()
        with psycopg.connect(DSN) as connection:
            rollback_to_generation(
                connection,
                tenant_id=self.tenant,
                generation_sha256=self.base.generation_sha256,
            )
            removed = prune_inactive_generations(
                connection, tenant_id=self.tenant, retain=0
            )
        self.assertIn(self.source_generation.generation_sha256, removed)
        self.assertEqual(self.source_request()[2]["status"], "retained")
        before = self.snapshot()
        status, _, response = self.source_request("POST")
        self.assertEqual(status, 409)
        self.assertEqual(response["code"], "KNOWLEDGE_SOURCE_PREPARATION_RETAINED")
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_preparation_has_one_changed_receipt_and_no_activation(self):
        before = self.snapshot()
        barrier = threading.Barrier(2)

        def prepare():
            barrier.wait(2)
            return self.source_request("POST")

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(prepare) for _ in range(2)]
            responses = [request.result(5) for request in requests]
        self.assertEqual([response[0] for response in responses], [200, 200])
        self.assertEqual(
            sorted(response[2]["changed"] for response in responses), [False, True]
        )
        self.assertEqual(self.snapshot()[:2], before[:2])
        with psycopg.connect(DSN) as connection:
            for table in ("yap_knowledge_source_admissions", "yap_knowledge_builds"):
                self.assertEqual(
                    connection.execute(
                        f"SELECT count(*) FROM {table} WHERE tenant_id = %s AND generation_sha256 = %s",
                        (self.tenant, self.source_generation.generation_sha256),
                    ).fetchone(),
                    (1,),
                )

    def test_lock_timeout_cannot_leave_a_late_preparation(self):
        before = self.snapshot()
        with psycopg.connect(DSN) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (self.tenant,),
                )
                self.assertEqual(self.source_request("POST")[0], 503)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.source_request("POST")[0], 200)

    def test_source_slots_bound_work_without_blocking_health_or_later_retry(self):
        release = threading.Event()
        saturated = threading.Event()
        counter_lock = threading.Lock()
        calls = 0
        original_compile = ReviewedSourceSnapshot.compile

        def held_compile(snapshot):
            nonlocal calls
            generation = original_compile(snapshot)
            with counter_lock:
                calls += 1
                if calls == 2:
                    saturated.set()
            if not release.wait(5):
                raise TimeoutError("fixture did not release source compilation")
            return generation

        with patch.object(ReviewedSourceSnapshot, "compile", held_compile):
            with ThreadPoolExecutor(max_workers=2) as pool:
                requests = [pool.submit(self.source_request, "POST") for _ in range(2)]
                try:
                    self.assertTrue(saturated.wait(2))
                    self.assertEqual(self.source_request()[0], 429)
                    self.assertEqual(self.request("POST")[0], 429)
                    self.assertEqual(self._request("/v1/health")[0], 200)
                finally:
                    release.set()
                self.assertEqual(
                    [request.result(5)[0] for request in requests], [200, 200]
                )
        self.assertEqual(self.source_request("POST")[0], 200)

    def test_request_contract_rejects_uploaded_authority_and_redacts_logs(self):
        before = self.snapshot()
        request = {
            "schemaVersion": 1,
            "expectedGenerationSha256": self.source_generation.generation_sha256,
        }
        for key in (
            "tenantId",
            "subjectId",
            "sourcePath",
            "approved",
            "source",
            "policy",
            "credentials",
            "vectors",
        ):
            self.assertEqual(
                self.source_request(
                    "POST", payload={**request, key: "private uploaded field"}
                )[0],
                400,
            )
        self.assertEqual(
            self.source_request("POST", payload={**request, "schemaVersion": True})[0],
            400,
        )
        self.assertEqual(
            self.source_request("GET", path=PATH + "?private=source")[0], 400
        )
        self.assertEqual(
            self.source_request("GET", data=b"private uploaded body")[0], 400
        )
        self.assertEqual(
            self.source_request("POST", path=PATH + "?private=source")[0], 400
        )
        self.assertEqual(self.source_request("POST", data=b"{private")[0], 400)
        self.assertEqual(
            self.source_request("POST", headers={"Content-Type": "text/plain"})[0], 415
        )
        self.assertEqual(self.source_request("DELETE")[0], 405)
        self.assertEqual(self.snapshot(), before)
        logs = "\n".join(self.logger.messages)
        self.assertNotIn("private", logs)
        self.assertNotIn("Bearer", logs)

    def test_publication_runtime_without_snapshot_keeps_source_preparation_disabled(
        self,
    ):
        disabled = {
            key: value
            for key, value in self.environ.items()
            if not key.startswith("YAP_KNOWLEDGE_REVIEWED_SOURCE")
        }
        service = build_knowledge_publication_service(
            disabled, authenticated_team_mode=True
        )
        self.server.RequestHandlerClass.keywords["knowledge_publication_service"] = (
            service
        )
        before = self.snapshot()
        self.assertEqual(self.source_request()[0], 501)
        self.assertEqual(self.source_request("POST")[0], 501)
        self.assertEqual(self.source_request(actor=None)[0], 401)
        self.assertEqual(self.snapshot(), before)
