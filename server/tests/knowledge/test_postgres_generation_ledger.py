from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    prune_inactive_generations,
    read_active_generation,
    rollback_to_generation,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_curated_knowledge_generation,
)
from yap_server.knowledge.knowledge_proposals import (
    discard_knowledge_proposal,
    store_knowledge_proposal,
)
from yap_server.knowledge.knowledge_tool_contract import ProposalCitation
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_lexical,
)


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PostgresGenerationLedgerTests(unittest.TestCase):
    def test_embedding_preparation_refuses_changed_reviewed_projection_without_repair(
        self,
    ):
        mutations = {
            "chunk-body": "UPDATE yap_knowledge_chunks SET body = body || ' changed'",
            "chunk-span": "UPDATE yap_knowledge_chunks SET char_end = char_end + 1",
            "concept-body": "UPDATE yap_knowledge_concepts SET body = body || ' changed'",
            "concept-metadata": "UPDATE yap_knowledge_concepts SET frontmatter = jsonb_set(frontmatter, '{title}', '\"Changed\"')",
            "relationship": "UPDATE yap_knowledge_relationships SET relationship_type = 'changed'",
            "permission": "UPDATE yap_knowledge_permissions SET policy = jsonb_set(policy, '{classification}', '\"restricted\"')",
            "permission-audience": "UPDATE yap_knowledge_permission_audience SET subject_id = 'another-reviewer'",
            "reviewer": "UPDATE yap_knowledge_source_admissions SET reviewer_id = 'another-reviewer'",
            "revision": "UPDATE yap_knowledge_builds SET source_revision = 'changed-revision'",
            **{
                field: f"UPDATE yap_knowledge_builds SET {field} = {field} + 1"
                for field in (
                    "concept_count",
                    "permission_count",
                    "chunk_count",
                    "relationship_count",
                )
            },
        }
        for name, statement in mutations.items():
            with self.subTest(mutation=name):
                tenant = f"test-{uuid4()}"
                self.addCleanup(_remove_generation_test_tenant, tenant)
                with TemporaryDirectory() as directory:
                    root = _tamper_bundle(Path(directory), tenant)
                    source_bytes = {
                        path.relative_to(root): path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    }
                    generation = compile_okf_bundle(
                        root, tenant_id=tenant, source_revision="reviewed-source"
                    )
                    with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
                        install_knowledge_schema(connection)
                        _stage_reviewed_generation(connection, generation)
                        arguments = dict(
                            tenant_id=tenant,
                            generation_sha256=generation.generation_sha256,
                            embedding_model_id="synthetic-test",
                            embedding_model_revision="revision-1",
                            embeddings={
                                item.chunk_id: (0.25,) * 768
                                for item in generation.chunks
                            },
                        )
                        # Valid first preparation and retry need no prior vectors.
                        store_generation_embeddings(connection, **arguments)
                        store_generation_embeddings(connection, **arguments)
                        connection.execute(
                            statement
                            + " WHERE tenant_id = %s AND generation_sha256 = %s",
                            (tenant, generation.generation_sha256),
                        )
                        before = _embedding_integrity_snapshot(connection, tenant)
                        with self.assertRaises(ValueError):
                            store_generation_embeddings(
                                connection,
                                **{
                                    **arguments,
                                    "embeddings": {
                                        item.chunk_id: (0.75,) * 768
                                        for item in generation.chunks
                                    },
                                },
                            )
                        self.assertEqual(
                            _embedding_integrity_snapshot(connection, tenant), before
                        )
                    self.assertEqual(
                        source_bytes,
                        {
                            path.relative_to(root): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        },
                    )

    def test_embedding_preparation_rechecks_source_after_actual_lock_wait(self):
        tenant = f"test-{uuid4()}"
        self.addCleanup(_remove_generation_test_tenant, tenant)
        with TemporaryDirectory() as directory:
            generation = compile_okf_bundle(
                _tamper_bundle(Path(directory), tenant),
                tenant_id=tenant,
                source_revision="reviewed-source",
            )
        ready = threading.Event()
        pids, outcomes = [], []

        def write():
            try:
                with psycopg.connect(
                    POSTGRES_DSN,
                    autocommit=True,
                    options="-c lock_timeout=10000 -c statement_timeout=15000",
                ) as connection:
                    pids.append(connection.info.backend_pid)
                    ready.set()
                    store_generation_embeddings(
                        connection,
                        tenant_id=tenant,
                        generation_sha256=generation.generation_sha256,
                        embedding_model_id="synthetic-test",
                        embedding_model_revision="revision-1",
                        embeddings={
                            item.chunk_id: (0.25,) * 768 for item in generation.chunks
                        },
                    )
                outcomes.append(None)
            except Exception as error:
                outcomes.append(error)
                ready.set()

        worker = threading.Thread(target=write)
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
            install_knowledge_schema(connection)
            _stage_reviewed_generation(connection, generation)
            try:
                with connection.transaction():
                    connection.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (tenant,),
                    )
                    worker.start()
                    self.assertTrue(ready.wait(5), "writer did not connect")
                    self.assertTrue(pids)
                    deadline = time.monotonic() + 5
                    while True:
                        connection.execute("SELECT pg_stat_clear_snapshot()")
                        if connection.execute(
                            "SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE pid = %s",
                            (pids[0],),
                        ).fetchone() == ("Lock", "advisory"):
                            break
                        self.assertLess(
                            time.monotonic(), deadline, "writer did not wait"
                        )
                        time.sleep(0.01)
                    connection.execute(
                        "UPDATE yap_knowledge_chunks SET body = body || ' changed' WHERE tenant_id = %s",
                        (tenant,),
                    )
                    before = _embedding_integrity_snapshot(connection, tenant)
            finally:
                if worker.ident is not None:
                    worker.join(16)
            self.assertFalse(worker.is_alive(), "writer did not finish")
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], ValueError)
            self.assertEqual(_embedding_integrity_snapshot(connection, tenant), before)

    def test_published_vectors_survive_replacement_and_rollback(self) -> None:
        tenant_id = f"test-{uuid4()}"
        self.addCleanup(_remove_generation_test_tenant, tenant_id)
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            first, second = (
                compile_okf_bundle(root, tenant_id=tenant_id, source_revision=revision)
                for revision in ("first", "second")
            )
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
            install_knowledge_schema(connection)
            _stage_reviewed_generation(connection, first)
            arguments = {
                "tenant_id": tenant_id,
                "generation_sha256": first.generation_sha256,
                "embedding_model_id": "synthetic-test",
                "embedding_model_revision": "revision-1",
            }
            # Preparation may retry before publication; the latest complete
            # staged projection becomes the immutable rollback target.
            for value in (0.0, 0.25):
                store_generation_embeddings(
                    connection,
                    **arguments,
                    embeddings={item.chunk_id: (value,) * 768 for item in first.chunks},
                )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=first.generation_sha256,
            )
            _stage_reviewed_generation(connection, second)
            _embed_and_activate(connection, second)

            def snapshot():
                return (
                    connection.execute(
                        """SELECT chunk_id, embedding::text, embedding_model_id,
                                  embedding_model_revision FROM yap_knowledge_chunks
                           WHERE tenant_id = %s ORDER BY generation_sha256, chunk_id""",
                        (tenant_id,),
                    ).fetchall(),
                    connection.execute(
                        """SELECT generation_sha256, previous_generation_sha256, reason
                           FROM yap_knowledge_activation_history
                           WHERE tenant_id = %s ORDER BY activation_id""",
                        (tenant_id,),
                    ).fetchall(),
                    read_active_generation(connection, tenant_id=tenant_id),
                    connection.execute(
                        """SELECT generation_sha256, embedding_model_id,
                                  embedding_model_revision FROM yap_knowledge_builds
                           WHERE tenant_id = %s ORDER BY generation_sha256""",
                        (tenant_id,),
                    ).fetchall(),
                )

            before = snapshot()
            for target in (first, second):
                with self.subTest(revision=target.source_revision):
                    with self.assertRaisesRegex(ValueError, "immutable"):
                        store_generation_embeddings(
                            connection,
                            **{
                                **arguments,
                                "generation_sha256": target.generation_sha256,
                            },
                            embeddings={
                                item.chunk_id: (0.75,) * 768 for item in target.chunks
                            },
                        )
                    self.assertEqual(snapshot(), before)
            restored = rollback_to_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=first.generation_sha256,
            )
            self.assertEqual(restored.generation_sha256, first.generation_sha256)
            self.assertEqual(snapshot()[0], before[0])
            self.assertEqual(
                snapshot()[1][-1],
                (
                    first.generation_sha256,
                    second.generation_sha256,
                    "rollback",
                ),
            )

    def test_embedding_writer_rechecks_publication_and_replacement_after_waiting(
        self,
    ) -> None:
        tenant_id = f"test-{uuid4()}"
        self.addCleanup(_remove_generation_test_tenant, tenant_id)
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            generation, successor = (
                compile_okf_bundle(root, tenant_id=tenant_id, source_revision=revision)
                for revision in ("concurrent-publication", "concurrent-successor")
            )
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
            install_knowledge_schema(connection)
            _stage_reviewed_generation(connection, generation)
            arguments = {
                "tenant_id": tenant_id,
                "generation_sha256": generation.generation_sha256,
                "embedding_model_id": "synthetic-test",
                "embedding_model_revision": "revision-1",
            }
            store_generation_embeddings(
                connection,
                **arguments,
                embeddings={item.chunk_id: (0.25,) * 768 for item in generation.chunks},
            )
            _stage_reviewed_generation(connection, successor)
            store_generation_embeddings(
                connection,
                **{**arguments, "generation_sha256": successor.generation_sha256},
                embeddings={item.chunk_id: (0.0,) * 768 for item in successor.chunks},
            )
            projection_query = """SELECT chunk_id, embedding::text, embedding_model_id,
                                        embedding_model_revision
                                  FROM yap_knowledge_chunks
                                  WHERE tenant_id = %s AND generation_sha256 = %s
                                  ORDER BY chunk_id"""
            projection_args = (tenant_id, generation.generation_sha256)
            before = connection.execute(projection_query, projection_args).fetchall()
            ready = threading.Event()
            worker_pid = []
            outcomes = []

            def write():
                try:
                    with psycopg.connect(
                        POSTGRES_DSN,
                        autocommit=True,
                        options="-c lock_timeout=10000 -c statement_timeout=15000",
                    ) as worker_connection:
                        worker_pid.append(worker_connection.info.backend_pid)
                        ready.set()
                        store_generation_embeddings(
                            worker_connection,
                            **arguments,
                            embeddings={
                                item.chunk_id: (0.75,) * 768
                                for item in generation.chunks
                            },
                        )
                    outcomes.append(None)
                except Exception as error:
                    outcomes.append(error)
                    ready.set()

            worker = threading.Thread(target=write)
            try:
                with connection.transaction():
                    connection.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (tenant_id,),
                    )
                    worker.start()
                    self.assertTrue(ready.wait(5), "writer did not connect")
                    self.assertTrue(worker_pid, "writer connection failed")
                    deadline = time.monotonic() + 5
                    while True:
                        waiting = connection.execute(
                            """SELECT wait_event_type, wait_event FROM pg_stat_activity
                               WHERE pid = %s""",
                            (worker_pid[0],),
                        ).fetchone()
                        if waiting == ("Lock", "advisory"):
                            break
                        self.assertLess(
                            time.monotonic(), deadline, "writer did not wait"
                        )
                        # Refresh the statistics snapshot within this transaction.
                        connection.execute("SELECT pg_stat_clear_snapshot()")
                        time.sleep(0.01)
                    activate_complete_generation(
                        connection,
                        tenant_id=tenant_id,
                        generation_sha256=generation.generation_sha256,
                    )
                    activate_complete_generation(
                        connection,
                        tenant_id=tenant_id,
                        generation_sha256=successor.generation_sha256,
                    )
            finally:
                if worker.ident is not None:
                    worker.join(16)
            self.assertFalse(worker.is_alive(), "writer failed to finish")
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], ValueError)
            self.assertIn("immutable", str(outcomes[0]))
            self.assertEqual(len(before), len(generation.chunks))
            self.assertEqual(
                connection.execute(projection_query, projection_args).fetchall(),
                before,
            )
            self.assertEqual(
                read_active_generation(
                    connection, tenant_id=tenant_id
                ).generation_sha256,
                successor.generation_sha256,
            )

    def test_activation_rehashes_every_persisted_projection(self) -> None:
        mutations = {
            "source-admission": """UPDATE yap_knowledge_source_admissions
                SET reviewer_id = 'mallory'
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "audience": """UPDATE yap_knowledge_permission_audience
                SET subject_id = 'mallory'
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "permission-policy": """UPDATE yap_knowledge_permissions
                SET policy = jsonb_set(policy, '{classification}', '"restricted"')
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "permission-hash": """UPDATE yap_knowledge_permissions
                SET permission_sha256 = repeat('0', 64)
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "concept-frontmatter": """UPDATE yap_knowledge_concepts
                SET frontmatter = jsonb_set(frontmatter, '{title}', '"Forged"')
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "concept-body": """UPDATE yap_knowledge_concepts
                SET body = body || E'\\nforged'
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "concept-links": """UPDATE yap_knowledge_concepts
                SET links = '[]'::jsonb
                WHERE tenant_id = %s AND generation_sha256 = %s
                  AND jsonb_array_length(links) > 0""",
            "chunk-body": """UPDATE yap_knowledge_chunks
                SET body = body || ' forged'
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "chunk-span": """UPDATE yap_knowledge_chunks
                SET char_end = char_end + 1
                WHERE tenant_id = %s AND generation_sha256 = %s""",
            "chunk-links": """UPDATE yap_knowledge_chunks
                SET linked_concept_ids = '[]'::jsonb
                WHERE tenant_id = %s AND generation_sha256 = %s
                  AND jsonb_array_length(linked_concept_ids) > 0""",
            "relationship": """UPDATE yap_knowledge_relationships
                SET relationship_type = 'forged'
                WHERE tenant_id = %s AND generation_sha256 = %s""",
        }
        for name, statement in mutations.items():
            with self.subTest(mutation=name):
                tenant_id = f"test-{uuid4()}"
                with TemporaryDirectory() as directory:
                    root = _tamper_bundle(Path(directory), tenant_id)
                    baseline = compile_okf_bundle(
                        root,
                        tenant_id=tenant_id,
                        source_revision="baseline",
                    )
                    candidate = compile_okf_bundle(
                        root,
                        tenant_id=tenant_id,
                        source_revision="candidate",
                    )
                with psycopg.connect(POSTGRES_DSN) as connection:
                    install_knowledge_schema(connection)
                    _stage_reviewed_generation(connection, baseline)
                    _embed_and_activate(connection, baseline)
                    _stage_reviewed_generation(connection, candidate)
                    store_generation_embeddings(
                        connection,
                        tenant_id=tenant_id,
                        generation_sha256=candidate.generation_sha256,
                        embedding_model_id="synthetic-test",
                        embedding_model_revision="revision-1",
                        embeddings={
                            item.chunk_id: (0.0,) * 768 for item in candidate.chunks
                        },
                    )
                    connection.execute(
                        statement, (tenant_id, candidate.generation_sha256)
                    )
                    connection.commit()
                    with self.assertRaises(ValueError):
                        activate_complete_generation(
                            connection,
                            tenant_id=tenant_id,
                            generation_sha256=candidate.generation_sha256,
                        )
                    self.assertEqual(
                        read_active_generation(
                            connection, tenant_id=tenant_id
                        ).generation_sha256,
                        baseline.generation_sha256,
                    )
                    connection.execute(
                        "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    connection.execute(
                        """DELETE FROM yap_knowledge_activation_history
                           WHERE tenant_id = %s""",
                        (tenant_id,),
                    )
                    connection.execute(
                        "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    connection.execute(
                        """DELETE FROM yap_knowledge_source_admissions
                           WHERE tenant_id = %s""",
                        (tenant_id,),
                    )
                    connection.commit()

    def test_proposal_disposition_and_pruning_are_atomic(self) -> None:
        tenant_id = f"test-{uuid4()}"
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            retained = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="proposal-generation",
            )
            successor = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="successor-generation",
            )
        with psycopg.connect(POSTGRES_DSN) as setup:
            install_knowledge_schema(setup)
            _stage_reviewed_generation(setup, retained)
            _embed_and_activate(setup, retained)
            concept = retained.concepts[0]
            citation = ProposalCitation(
                concept_id=concept.concept_id,
                source_revision=retained.source_revision,
                content_sha256=concept.content_sha256,
                char_start=0,
                char_end=1,
            )

            for char_start, char_end in (
                (False, True),
                (0.0, 1.0),
                ("0", "1"),
            ):
                invalid = ProposalCitation.model_construct(
                    concept_id=concept.concept_id,
                    source_revision=retained.source_revision,
                    content_sha256=concept.content_sha256,
                    char_start=char_start,
                    char_end=char_end,
                )
                with self.subTest(char_start=char_start, char_end=char_end):
                    with self.assertRaisesRegex(ValueError, "citation"):
                        store_knowledge_proposal(
                            setup,
                            principal=PrincipalKey(tenant_id, "alice"),
                            purpose="knowledge.read",
                            agent_id="retention-test",
                            agent_capabilities=frozenset({"knowledge.propose"}),
                            proposal_type="summary",
                            proposed_content="Reject invalid citation offsets.",
                            source_citations=(invalid,),
                            expected_generation_sha256=retained.generation_sha256,
                        )

            def store(content: str):
                return store_knowledge_proposal(
                    setup,
                    principal=PrincipalKey(tenant_id, "alice"),
                    purpose="knowledge.read",
                    agent_id="retention-test",
                    agent_capabilities=frozenset({"knowledge.propose"}),
                    proposal_type="summary",
                    proposed_content=content,
                    source_citations=(citation,),
                    expected_generation_sha256=retained.generation_sha256,
                )

            terminal = store("Discard this reviewed proposal.")
            self.assertEqual(store("Discard this reviewed proposal."), terminal)
            discard_knowledge_proposal(
                setup,
                principal=PrincipalKey(tenant_id, "alice"),
                proposal_id=terminal.proposal_id,
            )
            with self.assertRaisesRegex(ValueError, "stored truth"):
                store("Discard this reviewed proposal.")
            proposal = store("Retain this reviewed proposal.")
            _stage_reviewed_generation(setup, successor)
            _embed_and_activate(setup, successor)

        barrier = threading.Barrier(3)
        errors: list[BaseException] = []

        def discard() -> None:
            try:
                with psycopg.connect(POSTGRES_DSN) as connection:
                    barrier.wait()
                    discard_knowledge_proposal(
                        connection,
                        principal=PrincipalKey(tenant_id, "alice"),
                        proposal_id=proposal.proposal_id,
                    )
            except BaseException as error:
                errors.append(error)

        def prune() -> None:
            try:
                with psycopg.connect(POSTGRES_DSN) as connection:
                    barrier.wait()
                    prune_inactive_generations(
                        connection,
                        tenant_id=tenant_id,
                        retain=0,
                    )
            except BaseException as error:
                errors.append(error)

        workers = (threading.Thread(target=discard), threading.Thread(target=prune))
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(5)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertFalse(errors)
        with psycopg.connect(POSTGRES_DSN) as verification:
            build = verification.execute(
                """SELECT 1 FROM yap_knowledge_builds
                   WHERE tenant_id = %s AND generation_sha256 = %s""",
                (tenant_id, retained.generation_sha256),
            ).fetchone()
            proposal_row = verification.execute(
                """SELECT status FROM yap_knowledge_proposals
                   WHERE tenant_id = %s AND proposal_id = %s""",
                (tenant_id, proposal.proposal_id),
            ).fetchone()
            if build is None:
                self.assertIsNone(proposal_row)
            else:
                self.assertEqual(proposal_row, ("discarded",))
            prune_inactive_generations(verification, tenant_id=tenant_id, retain=0)
            self.assertIsNone(
                verification.execute(
                    """SELECT 1 FROM yap_knowledge_builds
                       WHERE tenant_id = %s AND generation_sha256 = %s""",
                    (tenant_id, retained.generation_sha256),
                ).fetchone()
            )
            self.assertIsNone(
                verification.execute(
                    """SELECT 1 FROM yap_knowledge_proposals
                       WHERE tenant_id = %s AND proposal_id = %s""",
                    (tenant_id, proposal.proposal_id),
                ).fetchone()
            )
            verification.execute(
                "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            verification.execute(
                "DELETE FROM yap_knowledge_activation_history WHERE tenant_id = %s",
                (tenant_id,),
            )
            verification.execute(
                "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            verification.execute(
                "DELETE FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
                (tenant_id,),
            )
            verification.commit()

    def test_staging_retry_refuses_damaged_counts_without_repair(self) -> None:
        tenant_id = f"test-{uuid4()}"
        self.addCleanup(_remove_generation_test_tenant, tenant_id)
        with TemporaryDirectory() as directory:
            root = _tamper_bundle(Path(directory), tenant_id)
            sources = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            generations = tuple(
                compile_okf_bundle(root, tenant_id=tenant_id, source_revision=revision)
                for revision in ("reviewed-active", "reviewed-staged")
            )
            with psycopg.connect(POSTGRES_DSN) as connection:
                install_knowledge_schema(connection)
                for generation in generations:
                    _stage_reviewed_generation(connection, generation)
                _embed_and_activate(connection, generations[0])
                connection.commit()

                def snapshot():
                    return tuple(
                        connection.execute(
                            f"SELECT to_jsonb(record) FROM {table} AS record WHERE tenant_id = %s ORDER BY to_jsonb(record)::text",
                            (tenant_id,),
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

                for generation in generations:
                    admission = connection.execute(
                        "SELECT source_admission_sha256 FROM yap_knowledge_builds WHERE tenant_id = %s AND generation_sha256 = %s",
                        (tenant_id, generation.generation_sha256),
                    ).fetchone()[0]
                    before = snapshot()
                    descriptor = stage_compiled_generation(
                        connection, generation, source_admission_sha256=admission
                    )
                    self.assertEqual(descriptor.concept_count, len(generation.concepts))
                    self.assertEqual(snapshot(), before)
                    for column in (
                        "concept_count",
                        "permission_count",
                        "chunk_count",
                        "relationship_count",
                    ):
                        with self.subTest(
                            revision=generation.source_revision, column=column
                        ):
                            connection.execute(
                                f"UPDATE yap_knowledge_builds SET {column} = {column} + 1 WHERE tenant_id = %s AND generation_sha256 = %s",
                                (tenant_id, generation.generation_sha256),
                            )
                            connection.commit()
                            damaged = snapshot()
                            with self.assertRaisesRegex(ValueError, "descriptor"):
                                stage_compiled_generation(
                                    connection,
                                    generation,
                                    source_admission_sha256=admission,
                                )
                            self.assertEqual(snapshot(), damaged)
                            # Restore only this synthetic fixture for the next case.
                            connection.execute(
                                f"UPDATE yap_knowledge_builds SET {column} = {column} - 1 WHERE tenant_id = %s AND generation_sha256 = %s",
                                (tenant_id, generation.generation_sha256),
                            )
                            connection.commit()
                    self.assertEqual(snapshot(), before)
                self.assertEqual(
                    {
                        path.relative_to(root): path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    },
                    sources,
                )

    def test_staging_requires_exact_durable_source_admission(self) -> None:
        tenant_id = f"test-{uuid4()}"
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            reviewed = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="reviewed-revision",
            )
            concept_path = root / "projects" / "voiceos.md"
            concept_path.write_text(
                concept_path.read_text(encoding="utf-8") + "\nUnreviewed mutation.\n",
                encoding="utf-8",
            )
            mutated = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="reviewed-revision",
            )

        with psycopg.connect(POSTGRES_DSN) as connection:
            install_knowledge_schema(connection)
            with self.assertRaisesRegex(PermissionError, "was not reviewed"):
                stage_compiled_generation(
                    connection,
                    reviewed,
                    source_admission_sha256="0" * 64,
                )
            admission = admit_curated_knowledge_generation(
                connection,
                principal=_curator(tenant_id, "curator"),
                repository_revision=reviewed.source_revision,
                source_path="knowledge/voiceos",
                generation=reviewed,
            )
            forged = replace(
                reviewed,
                permissions=(
                    replace(
                        reviewed.permissions[0],
                        audience=(PrincipalKey(tenant_id, "mallory"),),
                    ),
                ),
            )
            with self.assertRaisesRegex(ValueError, "permission"):
                stage_compiled_generation(
                    connection,
                    forged,
                    source_admission_sha256=admission.admission_sha256,
                )
            self.assertIsNone(
                connection.execute(
                    """SELECT 1 FROM yap_knowledge_builds
                       WHERE tenant_id = %s AND generation_sha256 = %s""",
                    (tenant_id, reviewed.generation_sha256),
                ).fetchone()
            )
            with self.assertRaisesRegex(ValueError, "differs from the generation"):
                stage_compiled_generation(
                    connection,
                    mutated,
                    source_admission_sha256=admission.admission_sha256,
                )
            stage_compiled_generation(
                connection,
                reviewed,
                source_admission_sha256=admission.admission_sha256,
            )
            connection.commit()

        with psycopg.connect(POSTGRES_DSN) as restarted:
            stored = restarted.execute(
                """SELECT source_admission_sha256 FROM yap_knowledge_builds
                   WHERE tenant_id = %s AND generation_sha256 = %s""",
                (tenant_id, reviewed.generation_sha256),
            ).fetchone()
            self.assertEqual(stored, (admission.admission_sha256,))
            restarted.execute(
                "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                (tenant_id,),
            )
            restarted.execute(
                "DELETE FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
                (tenant_id,),
            )
            restarted.commit()

    def test_failed_staging_transaction_leaves_previous_generation_active(self) -> None:
        tenant_id = f"test-{uuid4()}"
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            first = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="revision-1",
            )
            second = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="revision-2",
            )

            with psycopg.connect(POSTGRES_DSN) as connection:
                install_knowledge_schema(connection)
                _stage_reviewed_generation(connection, first)
                _embed_and_activate(connection, first)
                connection.execute(
                    f"""CREATE OR REPLACE FUNCTION yap_test_reject_generation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                      IF NEW.generation_sha256 = '{second.generation_sha256}' THEN
                        RAISE EXCEPTION 'injected staging failure';
                      END IF;
                      RETURN NEW;
                    END $$"""
                )
                connection.execute(
                    """CREATE TRIGGER yap_test_reject_generation
                    BEFORE INSERT ON yap_knowledge_concepts
                    FOR EACH ROW EXECUTE FUNCTION yap_test_reject_generation()"""
                )
                connection.commit()
                with self.assertRaises(psycopg.Error):
                    _stage_reviewed_generation(connection, second)
                active = read_active_generation(connection, tenant_id=tenant_id)
                self.assertEqual(active.generation_sha256, first.generation_sha256)
                connection.execute(
                    "DROP TRIGGER yap_test_reject_generation ON yap_knowledge_concepts"
                )
                connection.execute("DROP FUNCTION yap_test_reject_generation()")
                connection.execute(
                    "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.commit()

    def test_rollback_and_retention_preserve_active_generation(self) -> None:
        tenant_id = f"test-{uuid4()}"
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            generations = tuple(
                compile_okf_bundle(
                    root,
                    tenant_id=tenant_id,
                    source_revision=f"revision-{index}",
                )
                for index in range(1, 4)
            )
            with psycopg.connect(POSTGRES_DSN) as connection:
                install_knowledge_schema(connection)
                retained_proposal = None
                for index, generation in enumerate(generations):
                    _stage_reviewed_generation(connection, generation)
                    _embed_and_activate(connection, generation)
                    if index == 1:
                        concept = generation.concepts[0]
                        retained_proposal = store_knowledge_proposal(
                            connection,
                            principal=PrincipalKey(tenant_id, "alice"),
                            purpose="knowledge.read",
                            agent_id="retention-test",
                            agent_capabilities=frozenset({"knowledge.propose"}),
                            proposal_type="summary",
                            proposed_content="Retain this reviewed proposal.",
                            source_citations=(
                                ProposalCitation(
                                    concept_id=concept.concept_id,
                                    source_revision=generation.source_revision,
                                    content_sha256=concept.content_sha256,
                                    char_start=0,
                                    char_end=1,
                                ),
                            ),
                            expected_generation_sha256=generation.generation_sha256,
                        )
                        self.assertEqual(
                            store_knowledge_proposal(
                                connection,
                                principal=PrincipalKey(tenant_id, "alice"),
                                purpose="knowledge.read",
                                agent_id="retention-test",
                                agent_capabilities=frozenset({"knowledge.propose"}),
                                proposal_type="summary",
                                proposed_content="Retain this reviewed proposal.",
                                source_citations=(
                                    ProposalCitation(
                                        concept_id=concept.concept_id,
                                        source_revision=generation.source_revision,
                                        content_sha256=concept.content_sha256,
                                        char_start=0,
                                        char_end=1,
                                    ),
                                ),
                                expected_generation_sha256=(
                                    generation.generation_sha256
                                ),
                            ),
                            retained_proposal,
                        )

                self.assertIsNotNone(retained_proposal)

                restored = rollback_to_generation(
                    connection,
                    tenant_id=tenant_id,
                    generation_sha256=generations[0].generation_sha256,
                )
                self.assertEqual(
                    restored.generation_sha256, generations[0].generation_sha256
                )
                removed = prune_inactive_generations(
                    connection, tenant_id=tenant_id, retain=0
                )
                self.assertEqual(len(removed), 1)
                self.assertNotIn(generations[0].generation_sha256, removed)
                self.assertNotIn(generations[1].generation_sha256, removed)
                with self.assertRaisesRegex(LookupError, "does not exist"):
                    discard_knowledge_proposal(
                        connection,
                        principal=PrincipalKey(tenant_id, "bob"),
                        proposal_id=retained_proposal.proposal_id,
                    )
                disposition = discard_knowledge_proposal(
                    connection,
                    principal=PrincipalKey(tenant_id, "alice"),
                    proposal_id=retained_proposal.proposal_id,
                )
                self.assertEqual(disposition.status, "discarded")
                self.assertEqual(
                    discard_knowledge_proposal(
                        connection,
                        principal=PrincipalKey(tenant_id, "alice"),
                        proposal_id=retained_proposal.proposal_id,
                    ),
                    disposition,
                )
                self.assertEqual(
                    prune_inactive_generations(
                        connection, tenant_id=tenant_id, retain=0
                    ),
                    (generations[1].generation_sha256,),
                )
                active = read_active_generation(connection, tenant_id=tenant_id)
                self.assertEqual(
                    active.generation_sha256, generations[0].generation_sha256
                )
                history = connection.execute(
                    """SELECT reason FROM yap_knowledge_activation_history
                       WHERE tenant_id = %s ORDER BY activation_id""",
                    (tenant_id,),
                ).fetchall()
                self.assertEqual(
                    tuple(row[0] for row in history),
                    ("publish", "publish", "publish", "rollback"),
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_activation_history WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.commit()

    def test_active_generation_survives_reconnect_and_successor_stays_current(
        self,
    ) -> None:
        tenant_id = f"test-{uuid4()}"
        with TemporaryDirectory() as directory:
            root = _bundle(Path(directory), tenant_id)
            first = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="revision-before-reconnect",
            )
            second = compile_okf_bundle(
                root,
                tenant_id=tenant_id,
                source_revision="revision-after-reconnect",
            )

            with psycopg.connect(POSTGRES_DSN) as connection:
                install_knowledge_schema(connection)
                _stage_reviewed_generation(connection, first)
                _embed_and_activate(connection, first)

            with psycopg.connect(POSTGRES_DSN) as connection:
                restored = read_active_generation(connection, tenant_id=tenant_id)
                self.assertEqual(restored.generation_sha256, first.generation_sha256)
                restored_search = search_postgres_knowledge_lexical(
                    connection,
                    principal=PrincipalKey(tenant_id, "alice"),
                    purpose="knowledge.read",
                    agent_capabilities=frozenset({"knowledge.search.lexical"}),
                    search_text="generation promotion atomic",
                    expected_generation_sha256=first.generation_sha256,
                )
                self.assertEqual(
                    restored_search.generation_sha256, first.generation_sha256
                )
                self.assertEqual(len(restored_search.results), 1)
                self.assertEqual(
                    restored_search.results[0].concept_id, "projects/voiceos"
                )
                self.assertEqual(
                    restored_search.results[0].generation_sha256,
                    first.generation_sha256,
                )
                _stage_reviewed_generation(connection, second)
                _embed_and_activate(connection, second)

            with psycopg.connect(POSTGRES_DSN) as connection:
                current = read_active_generation(connection, tenant_id=tenant_id)
                self.assertEqual(current.generation_sha256, second.generation_sha256)
                with self.assertRaisesRegex(ValueError, "stale"):
                    search_postgres_knowledge_lexical(
                        connection,
                        principal=PrincipalKey(tenant_id, "alice"),
                        purpose="knowledge.read",
                        agent_capabilities=frozenset({"knowledge.search.lexical"}),
                        search_text="generation promotion atomic",
                        expected_generation_sha256=first.generation_sha256,
                    )
                current_search = search_postgres_knowledge_lexical(
                    connection,
                    principal=PrincipalKey(tenant_id, "alice"),
                    purpose="knowledge.read",
                    agent_capabilities=frozenset({"knowledge.search.lexical"}),
                    search_text="generation promotion atomic",
                    expected_generation_sha256=second.generation_sha256,
                )
                self.assertEqual(
                    current_search.generation_sha256, second.generation_sha256
                )
                self.assertEqual(len(current_search.results), 1)
                history = connection.execute(
                    """SELECT generation_sha256 FROM yap_knowledge_activation_history
                       WHERE tenant_id = %s ORDER BY activation_id""",
                    (tenant_id,),
                ).fetchall()
                self.assertEqual(
                    [row[0] for row in history],
                    [first.generation_sha256, second.generation_sha256],
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_active_builds WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_activation_history WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.execute(
                    "DELETE FROM yap_knowledge_builds WHERE tenant_id = %s",
                    (tenant_id,),
                )
                connection.commit()


def _bundle(root: Path, tenant_id: str) -> Path:
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n",
        encoding="utf-8",
    )
    (root / "projects").mkdir()
    (root / "projects" / "voiceos.md").write_text(
        f"""---
type: Project
title: VoiceOS
resource: yap://tenant/{tenant_id}/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {{source: synthetic, source_revision: source-1}}
---
# VoiceOS

Generation promotion is atomic.
""",
        encoding="utf-8",
    )
    (root / "permissions").mkdir()
    (root / "permissions" / "projects.yml").write_text(
        f"""path_prefix: projects/
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: alice}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
        encoding="utf-8",
    )
    return root


def _tamper_bundle(root: Path, tenant_id: str) -> Path:
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
    )
    for folder in ("projects", "decisions", "permissions"):
        (root / folder).mkdir()
    (root / "projects" / "voiceos.md").write_text(
        f"""---
type: Project
title: VoiceOS
resource: yap://tenant/{tenant_id}/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {{source: synthetic, source_revision: source-1}}
relationships:
  - {{type: depends_on, target: /decisions/release.md, authority: asserted}}
---
# VoiceOS

See the [release decision](/decisions/release.md).
""",
        encoding="utf-8",
    )
    (root / "decisions" / "release.md").write_text(
        f"""---
type: Decision
title: Release
resource: yap://tenant/{tenant_id}/decision/release
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {{source: synthetic, source_revision: source-1}}
---
# Release
""",
        encoding="utf-8",
    )
    for name in ("projects", "decisions"):
        (root / "permissions" / f"{name}.yml").write_text(
            f"""path_prefix: {name}/
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: alice}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
            encoding="utf-8",
        )
    return root


def _remove_generation_test_tenant(tenant_id: str) -> None:
    with psycopg.connect(POSTGRES_DSN) as connection:
        for table in (
            "yap_knowledge_active_builds",
            "yap_knowledge_activation_history",
            "yap_knowledge_builds",
            "yap_knowledge_source_admissions",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,)
            )


def _embedding_integrity_snapshot(connection, tenant):
    return tuple(
        connection.execute(
            f"SELECT to_jsonb(record) FROM {table} AS record WHERE tenant_id = %s ORDER BY to_jsonb(record)::text",
            (tenant,),
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


def _embed_and_activate(connection, generation) -> None:
    store_generation_embeddings(
        connection,
        tenant_id=generation.tenant_id,
        generation_sha256=generation.generation_sha256,
        embedding_model_id="synthetic-test",
        embedding_model_revision="revision-1",
        embeddings={item.chunk_id: (0.0,) * 768 for item in generation.chunks},
    )
    activate_complete_generation(
        connection,
        tenant_id=generation.tenant_id,
        generation_sha256=generation.generation_sha256,
    )


def _stage_reviewed_generation(connection, generation) -> None:
    admission = admit_curated_knowledge_generation(
        connection,
        principal=_curator(generation.tenant_id, "synthetic-curator"),
        repository_revision=generation.source_revision,
        source_path="tests/fixtures/okf",
        generation=generation,
    )
    stage_compiled_generation(
        connection,
        generation,
        source_admission_sha256=admission.admission_sha256,
    )


def _curator(tenant_id: str, subject_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=subject_id,
        client_id="knowledge-tests",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )


if __name__ == "__main__":
    unittest.main()
