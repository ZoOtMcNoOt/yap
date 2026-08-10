from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    stage_compiled_generation,
    store_generation_embeddings,
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
            stage_compiled_generation(connection, generation)
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
            hidden = search_postgres_knowledge_lexical(
                connection,
                principal=alice,
                purpose="knowledge.read",
                agent_capabilities=capabilities,
                search_text="zircon hidden",
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
            stage_compiled_generation(connection, revoked_generation)
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
            tuple(item.concept_id for item in tree),
            ("decisions/public", "projects/voiceos"),
        )
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].text, "Approved roadmap work is ready.")
        self.assertEqual(hidden, ())
        self.assertEqual(
            tuple(item.concept_id for item in vector), ("projects/voiceos",)
        )
        self.assertEqual(vector[0].permission_hash, visible[0].permission_hash)
        self.assertEqual(hybrid[0].concept_id, "projects/voiceos")
        self.assertEqual(after_revocation, ())
        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0].target_concept_id, "decisions/public")
        self.assertNotIn(
            "secret",
            repr(tree)
            + repr(visible)
            + repr(hidden)
            + repr(vector)
            + repr(hybrid)
            + repr(relationships),
        )


def _generation(root: Path, tenant_id: str, *, subject: str):
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
    return compile_okf_bundle(root, tenant_id=tenant_id, source_revision="commit-a")


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
