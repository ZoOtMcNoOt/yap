from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

import psycopg

from yap_server.auth import AuthenticatedPrincipal, AuthenticationFailure
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_connections_service import (
    build_knowledge_connections_service,
)
from yap_server.knowledge.knowledge_publication_service import (
    build_knowledge_publication_service,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_curated_knowledge_generation,
)
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from tests.knowledge.test_postgres_generation_ledger import _tamper_bundle
from .api_fixtures import HealthServerTestCase
from . import test_terminology_api as terminology_fixtures

DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")
PATH = "/v1/knowledge/publications"


class _Authentication:
    authentication_required = True
    principal_access_enforced = True

    def __init__(self, tenant):
        self.tenant = tenant

    def authenticate(self, authorization):
        if authorization is None:
            raise AuthenticationFailure.missing()
        if authorization not in {
            "Bearer alice",
            "Bearer reader",
            "Bearer bob",
            "Bearer foreign",
        }:
            raise AuthenticationFailure.invalid()
        actor = authorization.split()[1]
        return AuthenticatedPrincipal(
            self.tenant if actor != "foreign" else "other-tenant",
            "bob" if actor == "bob" else "alice",
            "private-client",
            frozenset({"access_as_user"}),
            roles=frozenset()
            if actor == "reader"
            else frozenset({"knowledge.curator"}),
        )


@unittest.skipUnless(DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PublicationApiTestCase(HealthServerTestCase):
    server_settings = terminology_fixtures.TerminologyApiTests.server_settings

    def setUp(self):
        self.tenant = f"publication-api-{uuid4().hex}"
        self.request_authenticator = _Authentication(self.tenant)
        self.principal = self.request_authenticator.authenticate("Bearer alice")
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        credential = self.root / "publication.dsn"
        credential.write_text(DSN, encoding="utf-8")
        credential.chmod(0o600)
        self.environ = {
            "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": "postgres",
            "YAP_KNOWLEDGE_PUBLICATION_DSN_FILE": str(credential),
        }
        with psycopg.connect(DSN) as connection:
            install_knowledge_schema(connection)
            install_knowledge_tool_audit_schema(connection)
        self.addCleanup(self._clean_tenant)
        self.base = self.prepare("reviewed-base", confirmed=False)
        self.target = self.prepare("reviewed-target")
        with psycopg.connect(DSN) as connection:
            activate_complete_generation(
                connection,
                tenant_id=self.tenant,
                generation_sha256=self.base.generation_sha256,
            )
        self.knowledge_publication_service = self._build_publication_service()
        self.knowledge_connections_service = build_knowledge_connections_service(
            {
                "YAP_KNOWLEDGE_CONNECTIONS_RUNTIME": "postgres",
                "YAP_KNOWLEDGE_CONNECTIONS_DSN_FILE": str(credential),
            },
            authenticated_team_mode=True,
        )
        super().setUp()

    def _build_publication_service(self):
        return build_knowledge_publication_service(
            self.environ, authenticated_team_mode=True
        )

    def _clean_tenant(self):
        with psycopg.connect(DSN) as connection:
            for table in (
                "yap_knowledge_active_builds",
                "yap_knowledge_builds",
                "yap_knowledge_activation_history",
                "yap_knowledge_source_admissions",
                "yap_knowledge_tool_audit",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE tenant_id = %s", (self.tenant,)
                )

    def prepare(self, revision, *, confirmed=True, embeddings=True):
        root = self.root / revision
        root.mkdir()
        _tamper_bundle(root, self.tenant)
        source = root / "projects/voiceos.md"
        if confirmed:
            source.write_text(
                source.read_text().replace(
                    "authority: asserted", "authority: human_confirmed"
                )
            )
        generation = compile_okf_bundle(
            root, tenant_id=self.tenant, source_revision=revision
        )
        with psycopg.connect(DSN) as connection:
            admission = admit_curated_knowledge_generation(
                connection,
                principal=self.principal,
                repository_revision=revision,
                source_path="reviewed-knowledge",
                generation=generation,
            )
            stage_compiled_generation(
                connection,
                generation,
                source_admission_sha256=admission.admission_sha256,
            )
            if embeddings:
                store_generation_embeddings(
                    connection,
                    tenant_id=self.tenant,
                    generation_sha256=generation.generation_sha256,
                    embedding_model_id="synthetic-test",
                    embedding_model_revision="fixture-1",
                    embeddings={
                        chunk.chunk_id: (0.25,) * 768 for chunk in generation.chunks
                    },
                )
        return generation

    def request(
        self,
        method="GET",
        *,
        generation=None,
        expected=None,
        actor="alice",
        payload=None,
    ):
        generation = generation or self.target.generation_sha256
        if method == "GET":
            target = PATH + "?" + urlencode({"generationSha256": generation})
            data = None
        else:
            target = PATH
            data = json.dumps(
                payload
                if payload is not None
                else {
                    "schemaVersion": 1,
                    "generationSha256": generation,
                    "expectedActiveGenerationSha256": self.base.generation_sha256
                    if expected is None
                    else expected,
                }
            ).encode()
        headers = {"Content-Type": "application/json"}
        if actor is not None:
            headers["Authorization"] = f"Bearer {actor}"
        status, headers, body = self._request(
            target, method=method, data=data, headers=headers, timeout=5
        )
        return status, headers, json.loads(body)

    def snapshot(self):
        with psycopg.connect(DSN) as connection:
            return tuple(
                connection.execute(query, (self.tenant,)).fetchall()
                for query in (
                    "SELECT generation_sha256 FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                    "SELECT generation_sha256, previous_generation_sha256, reason FROM yap_knowledge_activation_history WHERE tenant_id = %s ORDER BY activation_id",
                    "SELECT generation_sha256, chunk_id, body, embedding::text, embedding_model_id, embedding_model_revision FROM yap_knowledge_chunks WHERE tenant_id = %s ORDER BY generation_sha256, chunk_id",
                    "SELECT admission_sha256, review_authority_sha256 FROM yap_knowledge_source_admissions WHERE tenant_id = %s ORDER BY admission_sha256",
                    "SELECT agent_id, operation, outcome FROM yap_knowledge_tool_audit WHERE tenant_id = %s ORDER BY audit_id",
                )
            )


class KnowledgePublicationApiTests(PublicationApiTestCase):
    def test_inspection_explicit_publication_replay_and_restart_preserve_reviewed_sources(
        self,
    ):
        source = self.root / "reviewed-target/projects/voiceos.md"
        original = source.read_bytes()
        status, headers, view = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(view["status"], "staged")
        self.assertEqual(view["activeGenerationSha256"], self.base.generation_sha256)
        status, _, published = self.request("POST")
        self.assertEqual(status, 200)
        self.assertTrue(published["changed"])
        self.assertEqual(published["status"], "active")
        from tests.contract import contract_schema_support as schema_support

        document = schema_support.load_json(
            Path(__file__).parents[2] / "openapi/openapi.json"
        )
        for result, schema in (
            (view, "KnowledgePublicationView"),
            (published, "KnowledgePublicationReceipt"),
        ):
            schema_support.assert_schema_subset(
                result,
                document["components"]["schemas"][schema],
                document_name="openapi.json",
                documents={"openapi.json": document},
            )
        before = self.snapshot()
        status, _, replay = self.request("POST")
        self.assertEqual(status, 200)
        self.assertFalse(replay["changed"])
        self.assertEqual(self.snapshot()[:4], before[:4])
        self.assertEqual(source.read_bytes(), original)
        restarted = build_knowledge_publication_service(
            self.environ, authenticated_team_mode=True
        )
        recovered = restarted.inspect(
            principal=self.principal, generation_sha256=self.target.generation_sha256
        )
        self.assertEqual(recovered["status"], "active")
        status, _, body = self._request(
            "/v1/knowledge/connections?"
            + urlencode(
                {
                    "conceptId": "projects/voiceos",
                    "generationSha256": self.target.generation_sha256,
                }
            ),
            headers={"Authorization": "Bearer alice"},
        )
        self.assertEqual(status, 200)
        graph = json.loads(body)
        self.assertTrue(
            any(
                edge["authority"] == "human_confirmed"
                for edge in graph["relationships"]
            )
        )
        self.assertEqual(graph["generationSha256"], self.target.generation_sha256)

    def test_first_publication_requires_an_explicit_empty_active_generation(self):
        self._clean_tenant()
        generation = self.prepare("reviewed-first")
        before = self.snapshot()
        self.assertEqual(
            self.request("POST", generation=generation.generation_sha256)[0], 409
        )
        self.assertEqual(self.snapshot(), before)
        status, _, receipt = self.request(
            "POST",
            payload={
                "schemaVersion": 1,
                "generationSha256": generation.generation_sha256,
                "expectedActiveGenerationSha256": None,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(receipt["changed"])
        self.assertIsNone(receipt["previousActiveGenerationSha256"])

    def test_roles_review_owner_and_tenant_do_not_acquire_publication_authority(self):
        before = self.snapshot()
        for method in ("GET", "POST"):
            self.assertEqual(self.request(method, actor=None)[0], 401)
            self.assertEqual(self.request(method, actor="reader")[0], 403)
            for actor in ("bob", "foreign"):
                status, _, denied = self.request(method, actor=actor)
                self.assertEqual(status, 404)
                unknown = self.request(method, generation="f" * 64)[2]
                self.assertEqual(
                    (denied["code"], denied["message"]),
                    (unknown["code"], unknown["message"]),
                )
                self.assertNotIn("sourceRevision", denied)
        self.assertEqual(self.snapshot(), before)

    def test_stale_intent_and_retained_generation_cannot_replace_newer_publication(
        self,
    ):
        successor = self.prepare("reviewed-successor")
        self.assertEqual(self.request("POST")[0], 200)
        before = self.snapshot()
        status, _, conflict = self.request(
            "POST", generation=successor.generation_sha256
        )
        self.assertEqual(
            (status, conflict["code"]), (409, "KNOWLEDGE_PUBLICATION_CHANGED")
        )
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            self.request(
                "POST",
                generation=successor.generation_sha256,
                expected=self.target.generation_sha256,
            )[0],
            200,
        )
        before = self.snapshot()
        status, _, retained = self.request("POST", expected=successor.generation_sha256)
        self.assertEqual(
            (status, retained["code"]), (409, "KNOWLEDGE_PUBLICATION_RETAINED")
        )
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.request()[2]["status"], "retained")

    def test_incomplete_vectors_source_tampering_and_invalid_admission_keep_prior_build(
        self,
    ):
        for scenario in ("incomplete", "source", "admission"):
            generation = self.prepare(
                "reviewed-" + scenario, embeddings=scenario != "incomplete"
            )
            with psycopg.connect(DSN) as connection:
                if scenario == "source":
                    connection.execute(
                        "UPDATE yap_knowledge_concepts SET body = 'private corrupted content' WHERE tenant_id = %s AND generation_sha256 = %s",
                        (self.tenant, generation.generation_sha256),
                    )
                elif scenario == "admission":
                    connection.execute(
                        "UPDATE yap_knowledge_source_admissions SET review_authority_sha256 = %s WHERE tenant_id = %s AND generation_sha256 = %s",
                        ("0" * 64, self.tenant, generation.generation_sha256),
                    )
            before = self.snapshot()
            status, _, error = self.request(
                "POST", generation=generation.generation_sha256
            )
            self.assertEqual(
                (status, error["code"]), (409, "KNOWLEDGE_PUBLICATION_INVALID")
            )
            self.assertNotIn("private corrupted", json.dumps(error))
            self.assertEqual(self.snapshot(), before)

    def test_failed_success_audit_rolls_back_actual_activation_and_history(self):
        before = self.snapshot()
        with patch(
            "yap_server.knowledge.knowledge_publication_service.record_knowledge_tool_audit",
            side_effect=psycopg.OperationalError("private failure details"),
        ):
            status, _, error = self.request("POST")
        self.assertEqual(status, 503)
        self.assertNotIn("private failure", json.dumps(error))
        self.assertIn("Inspect", error["message"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.request("POST")[0], 200)

    def test_lock_timeout_releases_request_without_a_late_publication(self):
        before = self.snapshot()
        with psycopg.connect(DSN) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (self.tenant,),
                )
                self.assertEqual(self.request("POST")[0], 503)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.request("POST")[0], 200)

    def test_concurrent_publications_with_one_expected_build_have_one_winner(self):
        successor = self.prepare("reviewed-concurrent")
        before = self.snapshot()
        barrier = threading.Barrier(2)

        def publish(generation):
            barrier.wait(2)
            return self.request("POST", generation=generation)[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(publish, generation.generation_sha256)
                for generation in (self.target, successor)
            ]
            self.assertEqual(sorted(f.result(5) for f in futures), [200, 409])
        after = self.snapshot()
        self.assertEqual(len(after[1]), len(before[1]) + 1)
        self.assertEqual(after[2:4], before[2:4])

    def test_current_generation_replay_revalidates_complete_truth_without_repair(self):
        self.assertEqual(self.request("POST")[0], 200)
        with psycopg.connect(DSN) as connection:
            connection.execute(
                "UPDATE yap_knowledge_concepts SET body = 'invalid active content' WHERE tenant_id = %s AND generation_sha256 = %s",
                (self.tenant, self.target.generation_sha256),
            )
        before = self.snapshot()
        self.assertEqual(self.request("POST")[0], 409)
        self.assertEqual(self.snapshot(), before)

    def test_request_bounds_identity_claims_and_private_logging(self):
        for extra in (
            "tenantId",
            "subjectId",
            "sourceRevision",
            "sourcePath",
            "approval",
            "embeddings",
        ):
            request = {
                "schemaVersion": 1,
                "generationSha256": self.target.generation_sha256,
                "expectedActiveGenerationSha256": self.base.generation_sha256,
                extra: "PrivateCallerClaim",
            }
            self.assertEqual(self.request("POST", payload=request)[0], 400)
        for schema in (True, 2):
            self.assertEqual(
                self.request(
                    "POST",
                    payload={
                        "schemaVersion": schema,
                        "generationSha256": self.target.generation_sha256,
                        "expectedActiveGenerationSha256": None,
                    },
                )[0],
                400,
            )
        for path, method, data, content_type, expected in (
            (
                PATH + "?tenantId=PrivateCallerClaim",
                "GET",
                None,
                "application/json",
                400,
            ),
            (
                PATH + "?generationSha256=" + self.target.generation_sha256,
                "GET",
                b"{}",
                "application/json",
                400,
            ),
            (
                PATH + "?sourcePath=PrivateCallerClaim",
                "POST",
                b"{}",
                "application/json",
                400,
            ),
            (PATH, "POST", b"{", "application/json", 400),
            (PATH, "POST", b"{}", "text/plain", 415),
            (PATH, "DELETE", None, "application/json", 405),
        ):
            status, _, _ = self._request(
                path,
                method=method,
                data=data,
                headers={"Authorization": "Bearer alice", "Content-Type": content_type},
            )
            self.assertEqual(status, expected)
        self.assertNotIn("PrivateCallerClaim", "\n".join(self.logger.messages))


class KnowledgeRollbackApiTests(PublicationApiTestCase):
    def snapshot(self):
        with psycopg.connect(DSN) as connection:
            stored = tuple(
                connection.execute(
                    f"SELECT to_jsonb(record) FROM {table} AS record WHERE tenant_id = %s ORDER BY to_jsonb(record)::text",
                    (self.tenant,),
                ).fetchall()
                for table in (
                    "yap_knowledge_builds",
                    "yap_knowledge_concepts",
                    "yap_knowledge_permissions",
                    "yap_knowledge_relationships",
                    "yap_knowledge_source_admissions",
                    "yap_knowledge_proposals",
                )
            )
        return super().snapshot() + (stored,)

    def rollback(self, *, generation=None, expected=None, actor="alice", payload=None):
        headers = {"Content-Type": "application/json"}
        if actor is not None:
            headers["Authorization"] = f"Bearer {actor}"
        data = (
            payload
            if payload is not None
            else {
                "schemaVersion": 1,
                "generationSha256": generation or self.base.generation_sha256,
                "expectedActiveGenerationSha256": expected
                or self.target.generation_sha256,
            }
        )
        status, headers, body = self._request(
            "/v1/knowledge/rollbacks",
            method="POST",
            data=json.dumps(data).encode(),
            headers=headers,
            timeout=5,
        )
        return status, headers, json.loads(body)

    def test_explicit_rollback_restores_retained_vectors_and_persists_across_restart(
        self,
    ):
        self.assertEqual(self.request("POST")[0], 200)
        before = self.snapshot()
        status, headers, result = self.rollback()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(result["changed"])
        self.assertEqual(result["activeGenerationSha256"], self.base.generation_sha256)
        self.assertEqual(
            result["previousActiveGenerationSha256"], self.target.generation_sha256
        )
        after = self.snapshot()
        self.assertEqual(after[2:4], before[2:4])
        self.assertEqual(
            after[1][-1],
            (self.base.generation_sha256, self.target.generation_sha256, "rollback"),
        )
        self.assertEqual(
            after[4][-1], ("knowledge-publication", "rollback-generation", "succeeded")
        )
        restarted = build_knowledge_publication_service(
            self.environ, authenticated_team_mode=True
        )
        self.assertEqual(
            restarted.inspect(
                principal=self.principal, generation_sha256=self.base.generation_sha256
            )["status"],
            "active",
        )
        replay_before = self.snapshot()
        self.assertFalse(self.rollback()[2]["changed"])
        self.assertEqual(self.snapshot()[:4], replay_before[:4])

    def test_authority_and_unknown_targets_refuse_without_mutation(self):
        self.assertEqual(self.request("POST")[0], 200)
        before = self.snapshot()
        for actor, expected_status in (
            (None, 401),
            ("reader", 403),
            ("bob", 404),
            ("foreign", 404),
        ):
            self.assertEqual(self.rollback(actor=actor)[0], expected_status)
            if actor in {"bob", "foreign"}:
                known = self.rollback(actor=actor)[2]
                unknown = self.rollback(actor=actor, generation="0" * 64)[2]
                self.assertEqual(
                    (known["code"], known["message"]),
                    (unknown["code"], unknown["message"]),
                )
        self.assertEqual(self.rollback(generation="0" * 64)[0], 404)
        self.assertEqual(self.snapshot(), before)

    def test_unpublished_and_pruned_targets_cannot_be_rolled_back(self):
        before = self.snapshot()
        status, _, error = self.rollback(
            generation=self.target.generation_sha256,
            expected=self.base.generation_sha256,
        )
        self.assertEqual(
            (status, error["code"]), (409, "KNOWLEDGE_ROLLBACK_UNPUBLISHED")
        )
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.request("POST")[0], 200)
        with psycopg.connect(DSN) as connection:
            connection.execute(
                "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s AND generation_sha256 = %s",
                (self.tenant, self.base.generation_sha256),
            )
        before = self.snapshot()
        self.assertEqual(self.rollback()[0], 404)
        self.assertEqual(self.snapshot(), before)

    def test_changed_active_generation_refuses_stale_rollback(self):
        successor = self.prepare("reviewed-newer")
        self.assertEqual(self.request("POST")[0], 200)
        self.assertEqual(
            self.request(
                "POST",
                generation=successor.generation_sha256,
                expected=self.target.generation_sha256,
            )[0],
            200,
        )
        before = self.snapshot()
        self.assertEqual(self.rollback()[0], 409)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.rollback(expected=successor.generation_sha256)[0], 200)

    def test_failed_audit_and_lock_timeout_have_no_late_rollback(self):
        self.assertEqual(self.request("POST")[0], 200)
        before = self.snapshot()
        with patch(
            "yap_server.knowledge.knowledge_publication_service.record_knowledge_tool_audit",
            side_effect=psycopg.OperationalError("Private rollback audit failure"),
        ):
            status, _, error = self.rollback()
        self.assertEqual(status, 503)
        self.assertNotIn("Private rollback", json.dumps(error))
        self.assertEqual(self.snapshot(), before)
        with psycopg.connect(DSN) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (self.tenant,),
                )
                self.assertEqual(self.rollback()[0], 503)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.rollback()[0], 200)

    def test_source_admission_and_vectors_are_revalidated_without_repairs(self):
        for scenario in ("source", "admission", "vector", "count"):
            with self.subTest(scenario=scenario):
                retained = self.prepare("reviewed-retained-" + scenario)
                self.assertEqual(
                    self.request(
                        "POST",
                        generation=retained.generation_sha256,
                        expected=self.snapshot()[0][0][0],
                    )[0],
                    200,
                )
                replacement = self.prepare("reviewed-replacement-" + scenario)
                self.assertEqual(
                    self.request(
                        "POST",
                        generation=replacement.generation_sha256,
                        expected=retained.generation_sha256,
                    )[0],
                    200,
                )
                queries = {
                    "source": "UPDATE yap_knowledge_concepts SET body = 'Private corrupted source' WHERE tenant_id = %s AND generation_sha256 = %s",
                    "admission": "UPDATE yap_knowledge_source_admissions SET review_authority_sha256 = repeat('0', 64) WHERE tenant_id = %s AND generation_sha256 = %s",
                    "vector": "UPDATE yap_knowledge_chunks SET embedding = NULL WHERE tenant_id = %s AND generation_sha256 = %s",
                    "count": "UPDATE yap_knowledge_builds SET chunk_count = chunk_count + 1 WHERE tenant_id = %s AND generation_sha256 = %s",
                }
                with psycopg.connect(DSN) as connection:
                    connection.execute(
                        queries[scenario], (self.tenant, retained.generation_sha256)
                    )
                before = self.snapshot()
                status, _, error = self.rollback(
                    generation=retained.generation_sha256,
                    expected=replacement.generation_sha256,
                )
                self.assertEqual(status, 409)
                self.assertNotIn("Private corrupted source", json.dumps(error))
                self.assertEqual(self.snapshot(), before)

    def test_rollback_and_publication_race_has_one_expected_active_winner(self):
        successor = self.prepare("reviewed-racing-publication")
        self.assertEqual(self.request("POST")[0], 200)
        before = self.snapshot()
        barrier = threading.Barrier(2)

        def rollback():
            barrier.wait(2)
            return self.rollback()[0]

        def publish():
            barrier.wait(2)
            return self.request(
                "POST",
                generation=successor.generation_sha256,
                expected=self.target.generation_sha256,
            )[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(rollback), pool.submit(publish)]
            self.assertEqual(sorted(f.result(5) for f in futures), [200, 409])
        after = self.snapshot()
        self.assertEqual(len(after[1]), len(before[1]) + 1)
        self.assertEqual(after[2:4], before[2:4])

    def test_rollback_contract_bounds_disabled_runtime_and_content_free_logs(self):
        before = self.snapshot()
        for extra in ("tenantId", "subjectId", "approval", "sourcePath", "embeddings"):
            self.assertEqual(
                self.rollback(
                    payload={
                        "schemaVersion": 1,
                        "generationSha256": self.base.generation_sha256,
                        "expectedActiveGenerationSha256": self.target.generation_sha256,
                        extra: "PrivateCallerClaim",
                    }
                )[0],
                400,
            )
        for method in ("GET", "DELETE"):
            self.assertEqual(
                self._request("/v1/knowledge/rollbacks", method=method)[0], 405
            )
        status, _, _ = self._request(
            "/v1/knowledge/rollbacks?tenantId=PrivateCallerClaim",
            method="POST",
            data=b"{}",
            headers={
                "Authorization": "Bearer alice",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("PrivateCallerClaim", "\n".join(self.logger.messages))
        self.server.RequestHandlerClass.keywords["knowledge_publication_service"] = None
        self.assertEqual(self.rollback()[0], 501)
