from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
import yap_server.knowledge.postgres_knowledge_retrieval as retrieval_module

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    prune_inactive_generations,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_curated_knowledge_generation,
    review_curated_knowledge_generation,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.postgres_knowledge_retrieval import (
    list_postgres_knowledge_tree,
    search_postgres_knowledge_hybrid,
    search_postgres_knowledge_lexical,
    search_postgres_knowledge_vector,
)
from yap_server.knowledge.postgres_relationship_retrieval import (
    traverse_postgres_knowledge_relationships,
)


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PostgresPermissionSafeRetrievalTests(unittest.TestCase):
    def test_filters_before_search_and_hides_chunks_linking_restricted_concepts(
        self,
    ) -> None:
        tenant_id = f"tenant-{uuid4().hex}"
        with TemporaryDirectory() as directory, TemporaryDirectory() as revoked_dir:
            generation = _generation(Path(directory), tenant_id, subject="alice")
            revoked_generation = _generation(
                Path(revoked_dir), tenant_id, subject="charlie"
            )
        alice = PrincipalKey(tenant_id, "alice")
        capabilities = frozenset({"knowledge.tree", "knowledge.search.lexical"})
        with psycopg.connect(POSTGRES_DSN) as connection:
            install_knowledge_schema(connection)
            _stage_reviewed_generation(connection, generation)
            embeddings = {
                item.chunk_id: ((1.0,) + (0.0,) * 767)
                if item.concept_id == "projects/voiceos"
                else ((0.0, 1.0) + (0.0,) * 766)
                for item in generation.chunks
            }
            store_generation_embeddings(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                embedding_model_id="synthetic-test",
                embedding_model_revision="revision-1",
                embeddings=embeddings,
            )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
            hybrid = search_postgres_knowledge_hybrid(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities
                | frozenset({"knowledge.search.hybrid"}),
                search_text="approved roadmap",
                query_embedding=(1.0,) + (0.0,) * 767,
                maximum_results=1,
            )
            relationships = traverse_postgres_knowledge_relationships(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=frozenset({"knowledge.relationship.traverse"}),
                start_concept_id="projects/voiceos",
            )
            tree = list_postgres_knowledge_tree(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities,
            )
            visible = search_postgres_knowledge_lexical(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities,
                search_text="approved roadmap",
            )
            self.assertEqual(
                search_postgres_knowledge_lexical(
                    connection,
                    principal=alice,
                    purpose="knowledge.read",
                    agent_capabilities=capabilities,
                    search_text="a" * 1_024,
                ).results,
                (),
            )
            with self.assertRaisesRegex(ValueError, "search text"):
                search_postgres_knowledge_lexical(
                    connection,
                    principal=alice,
                    purpose="knowledge.read",
                    agent_capabilities=capabilities,
                    search_text="a" * 1_025,
                )
            hidden = search_postgres_knowledge_lexical(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities,
                search_text="zircon hidden",
            )
            wrong_owner = search_postgres_knowledge_lexical(
                connection,
                principal=PrincipalKey(tenant_id, "bob"),
                purpose="knowledge.read",
                agent_capabilities=capabilities,
                search_text="approved roadmap",
            )
            wrong_purpose = search_postgres_knowledge_lexical(
                connection,
                principal=alice,
                purpose="knowledge.write",
                agent_capabilities=capabilities,
                search_text="approved roadmap",
            )
            with self.assertRaisesRegex(LookupError, "no active knowledge generation"):
                search_postgres_knowledge_lexical(
                    connection,
                    principal=PrincipalKey(f"other-{tenant_id}", "alice"),
                    purpose="knowledge.read",
                    agent_capabilities=capabilities,
                    search_text="approved roadmap",
                )
            vector = search_postgres_knowledge_vector(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities
                | frozenset({"knowledge.search.vector"}),
                query_embedding=(1.0,) + (0.0,) * 767,
                maximum_results=1,
            )
            with self.assertRaisesRegex(ValueError, "stale"):
                search_postgres_knowledge_lexical(
                    connection,
                    principal=alice,
                    purpose="knowledge.read",
                    agent_capabilities=capabilities,
                    search_text="roadmap",
                    expected_generation_sha256="0" * 64,
                )
            _stage_reviewed_generation(connection, revoked_generation)
            store_generation_embeddings(
                connection,
                tenant_id=tenant_id,
                generation_sha256=revoked_generation.generation_sha256,
                embedding_model_id="synthetic-test",
                embedding_model_revision="revision-1",
                embeddings={
                    item.chunk_id: (1.0,) + (0.0,) * 767
                    for item in revoked_generation.chunks
                },
            )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=revoked_generation.generation_sha256,
            )
            after_revocation = search_postgres_knowledge_lexical(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities,
                search_text="approved roadmap",
            )
            connection.execute(
                "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.commit()

        self.assertEqual(
            tuple(item.concept_id for item in tree.concepts),
            ("decisions/public", "projects/voiceos"),
        )
        self.assertEqual(len(visible.results), 1)
        self.assertEqual(visible.results[0].text, "Approved roadmap work is ready.")
        self.assertEqual(hidden.results, ())
        self.assertEqual(wrong_owner.results, ())
        self.assertEqual(wrong_purpose.results, ())
        self.assertEqual(
            tuple(item.concept_id for item in vector.results), ("projects/voiceos",)
        )
        self.assertEqual(vector.permission_hash, visible.permission_hash)
        self.assertEqual(hybrid.results[0].concept_id, "projects/voiceos")
        self.assertEqual(after_revocation.results, ())
        self.assertEqual(len(relationships.relationships), 1)
        self.assertEqual(
            relationships.relationships[0].target_concept_id, "decisions/public"
        )
        self.assertNotIn(
            "secret",
            repr(tree)
            + repr(visible)
            + repr(hidden)
            + repr(vector)
            + repr(hybrid)
            + repr(relationships),
        )

    def test_query_pins_generation_until_retrieval_transaction_finishes(self) -> None:
        tenant_id = f"tenant-{uuid4().hex}"
        with TemporaryDirectory() as first_directory, TemporaryDirectory() as second_directory:
            first = _generation(
                Path(first_directory),
                tenant_id,
                subject="alice",
                source_revision="commit-a",
            )
            second = _generation(
                Path(second_directory),
                tenant_id,
                subject="alice",
                source_revision="commit-b",
            )
        principal = PrincipalKey(tenant_id, "alice")
        capabilities = frozenset({"knowledge.search.lexical"})
        writer_started = threading.Event()
        writer_finished = threading.Event()
        writer_errors: list[BaseException] = []
        writer_pid: list[int] = []

        with psycopg.connect(POSTGRES_DSN) as setup:
            install_knowledge_schema(setup)
            for generation in (first, second):
                _stage_reviewed_generation(setup, generation)
                store_generation_embeddings(
                    setup,
                    tenant_id=tenant_id,
                    generation_sha256=generation.generation_sha256,
                    embedding_model_id="synthetic-test",
                    embedding_model_revision="revision-1",
                    embeddings={
                        item.chunk_id: (1.0,) + (0.0,) * 767
                        for item in generation.chunks
                    },
                )
            activate_complete_generation(
                setup,
                tenant_id=tenant_id,
                generation_sha256=first.generation_sha256,
            )

        def activate_and_prune() -> None:
            try:
                with psycopg.connect(POSTGRES_DSN) as writer:
                    writer_pid.append(
                        int(writer.execute("SELECT pg_backend_pid()").fetchone()[0])
                    )
                    writer_started.set()
                    activate_complete_generation(
                        writer,
                        tenant_id=tenant_id,
                        generation_sha256=second.generation_sha256,
                    )
                    prune_inactive_generations(
                        writer, tenant_id=tenant_id, retain=0
                    )
            except BaseException as error:
                writer_errors.append(error)
            finally:
                writer_finished.set()

        authorization_finished = threading.Event()
        release_reader = threading.Event()
        reader_errors: list[BaseException] = []
        reader_results = []
        original_lexical = retrieval_module._lexical_results

        def pause_after_authorization(*args, **kwargs):
            authorization_finished.set()
            release_reader.wait()
            return original_lexical(*args, **kwargs)

        def read_with_autocommit() -> None:
            try:
                with psycopg.connect(POSTGRES_DSN, autocommit=True) as reader:
                    reader_results.append(
                        search_postgres_knowledge_lexical(
                            reader,
                            principal=principal,
                            purpose="knowledge.read",
                            agent_capabilities=capabilities,
                            search_text="approved roadmap",
                        )
                    )
            except BaseException as error:
                reader_errors.append(error)

        with patch.object(
            retrieval_module, "_lexical_results", side_effect=pause_after_authorization
        ):
            reader = threading.Thread(target=read_with_autocommit)
            reader.start()
            self.assertTrue(authorization_finished.wait(2))
            writer = threading.Thread(target=activate_and_prune)
            writer.start()
            self.assertTrue(writer_started.wait(2))
            _wait_for_advisory_lock_wait(writer_pid[0])
            self.assertFalse(writer_finished.is_set())
            release_reader.set()
            reader.join(5)
            writer.join(5)

        self.assertFalse(reader.is_alive())
        self.assertFalse(writer.is_alive())
        self.assertFalse(reader_errors)
        self.assertFalse(writer_errors)
        self.assertEqual(len(reader_results), 1)
        self.assertEqual(
            reader_results[0].generation_sha256, first.generation_sha256
        )
        with psycopg.connect(POSTGRES_DSN) as verification:
            current = search_postgres_knowledge_lexical(
                verification,
                principal=principal,
                purpose="knowledge.read",
                agent_capabilities=capabilities,
                search_text="approved roadmap",
            )
            self.assertEqual(current.generation_sha256, second.generation_sha256)
            verification.rollback()
            verification.execute(
                "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            verification.execute(
                "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            verification.commit()


def _generation(
    root: Path,
    tenant_id: str,
    *,
    subject: str,
    source_revision: str = "commit-a",
):
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
    )
    for folder in ("projects", "decisions", "secret", "permissions"):
        (root / folder).mkdir()
    (root / "projects" / "voiceos.md").write_text(
        _concept(
            tenant_id,
            "Project",
            "VoiceOS",
            "project/voiceos",
            "# VoiceOS\n\nApproved roadmap work is ready.\n\n"
            "See [Decision](/decisions/public.md).\n\n"
            "See [Hidden](/secret/launch.md) for zircon details.\n",
        ),
        encoding="utf-8",
    )
    (root / "decisions" / "public.md").write_text(
        _concept(
            tenant_id,
            "Decision",
            "Public Decision",
            "decision/public",
            "# Public Decision\n\nApproved release decision.\n",
        ),
        encoding="utf-8",
    )
    (root / "secret" / "launch.md").write_text(
        _concept(
            tenant_id,
            "Decision",
            "Hidden",
            "decision/hidden",
            "# Hidden\n\nZircon hidden launch.\n",
        ),
        encoding="utf-8",
    )
    _permission(root, tenant_id, "projects", "projects/", subject)
    _permission(root, tenant_id, "decisions", "decisions/", subject)
    _permission(root, tenant_id, "secret", "secret/", "charlie")
    return compile_okf_bundle(
        root, tenant_id=tenant_id, source_revision=source_revision
    )


def _wait_for_advisory_lock_wait(process_id: int) -> None:
    deadline = time.monotonic() + 2
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as observer:
        while time.monotonic() < deadline:
            waiting = observer.execute(
                """SELECT EXISTS (
                       SELECT 1 FROM pg_locks
                       WHERE pid = %s AND locktype = 'advisory' AND NOT granted
                   )""",
                (process_id,),
            ).fetchone()[0]
            if waiting:
                return
            time.sleep(0.01)
    raise AssertionError("generation writer did not wait for the query lock")


def _stage_reviewed_generation(connection, generation) -> None:
    review = review_curated_knowledge_generation(
        AuthenticatedPrincipal(
            tenant_id=generation.tenant_id,
            subject_id="synthetic-curator",
            client_id="knowledge-tests",
            scopes=frozenset(),
            roles=frozenset({"knowledge.curator"}),
        ),
        repository_revision=generation.source_revision,
        source_path="tests/fixtures/permission-safe-okf",
        generation=generation,
    )
    admission = admit_curated_knowledge_generation(
        connection,
        review=review,
        generation=generation,
    )
    stage_compiled_generation(
        connection,
        generation,
        source_admission_sha256=admission.admission_sha256,
    )


def _concept(tenant_id: str, kind: str, title: str, resource: str, body: str) -> str:
    return f"""---
type: {kind}
title: {title}
resource: yap://tenant/{tenant_id}/{resource}
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {{source: synthetic-test, source_revision: revision-1}}
---
{body}"""


def _permission(
    root: Path, tenant_id: str, name: str, prefix: str, subject: str
) -> None:
    (root / "permissions" / f"{name}.yml").write_text(
        f"""path_prefix: {prefix}
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: {subject}}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
