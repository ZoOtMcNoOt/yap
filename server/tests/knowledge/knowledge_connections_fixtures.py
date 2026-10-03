from pathlib import Path
from tempfile import TemporaryDirectory

from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from tests.knowledge.test_postgres_permission_safe_retrieval import (
    _concept,
    _generation,
    _stage_reviewed_generation,
)


def activate_connection_fixture(
    connection,
    tenant,
    *,
    subject="alice",
    neighbors=0,
    hidden_neighbors=0,
    reviewed_authorities=False,
):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _generation(root, tenant, subject=subject)
        project = root / "projects/voiceos.md"
        source = project.read_text(encoding="utf-8").replace(
            "\n---\n",
            "\nrelationships:\n"
            "  - {type: related_to, target: /decisions/public.md, authority: agent_proposed}\n"
            "---\n",
            1,
        )
        if reviewed_authorities:
            source = source.replace(
                "\n---\n",
                "\n  - {type: derives_from, target: /decisions/public.md, authority: derived}\n---\n",
                1,
            )
        for index in range(neighbors):
            (root / f"decisions/neighbor-{index}.md").write_text(
                _concept(
                    tenant,
                    "Decision",
                    f"Neighbor {index}",
                    f"decision/neighbor-{index}",
                    "Reviewed decision.\n",
                ),
                encoding="utf-8",
            )
            source += f"\n[Neighbor {index}](/decisions/neighbor-{index}.md).\n"
        for index in range(hidden_neighbors):
            (root / f"secret/neighbor-{index}.md").write_text(
                _concept(
                    tenant,
                    "Decision",
                    f"Hidden {index}",
                    f"decision/hidden-{index}",
                    "Restricted decision.\n",
                ),
                encoding="utf-8",
            )
            source += f"\n[Hidden {index}](/secret/neighbor-{index}.md).\n"
        project.write_text(source, encoding="utf-8")
        public = root / "decisions/public.md"
        public.write_text(
            public.read_text(encoding="utf-8") + "\n[Project](/projects/voiceos.md).\n",
            encoding="utf-8",
        )
        if reviewed_authorities:
            public.write_text(
                public.read_text(encoding="utf-8").replace(
                    "\n---\n",
                    "\nrelationships:\n  - {type: supports, target: /projects/voiceos.md, authority: human_confirmed}\n---\n",
                    1,
                ),
                encoding="utf-8",
            )
        generation = compile_okf_bundle(
            root,
            tenant_id=tenant,
            source_revision="reviewed-connection-fixture",
        )
    _stage_reviewed_generation(connection, generation)
    store_generation_embeddings(
        connection,
        tenant_id=tenant,
        generation_sha256=generation.generation_sha256,
        embedding_model_id="synthetic-connection-fixture",
        embedding_model_revision="fixture-v1",
        embeddings={item.chunk_id: (1.0,) + (0.0,) * 767 for item in generation.chunks},
    )
    activate_complete_generation(
        connection,
        tenant_id=tenant,
        generation_sha256=generation.generation_sha256,
    )
    connection.commit()
    return generation
