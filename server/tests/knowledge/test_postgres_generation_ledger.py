from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

import psycopg

from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    read_active_generation,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle


POSTGRES_DSN = os.environ.get("YAP_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "YAP_TEST_POSTGRES_DSN is not configured")
class PostgresGenerationLedgerTests(unittest.TestCase):
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
                stage_compiled_generation(connection, first)
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
                    stage_compiled_generation(connection, second)
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


if __name__ == "__main__":
    unittest.main()
