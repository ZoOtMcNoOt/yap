"""Prove governed retrieval survives a gate-owned Postgres restart."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_curated_knowledge_generation,
)
from yap_server.knowledge.okf_compiler import compile_okf_bundle
from yap_server.knowledge.postgres_knowledge_retrieval import (
    search_postgres_knowledge_lexical,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUBJECT_ID = "restart-probe"
_CONCEPT_ID = "projects/restart-probe"
_RESOURCE_ID = "project/restart-probe"
_CAPABILITIES = frozenset({"knowledge.search.lexical"})


def seed_restart_probe(dsn: str) -> dict[str, object]:
    tenant_id = f"gate-{uuid4().hex}"
    with TemporaryDirectory() as directory:
        generation = _generation(
            Path(directory),
            tenant_id=tenant_id,
            source_revision="restart-original",
            body="Persistence sentinel original is available.",
        )
    with psycopg.connect(dsn) as connection:
        install_knowledge_schema(connection)
        _stage_and_activate(connection, generation)
        _assert_retrieval(
            connection,
            tenant_id=tenant_id,
            expected_generation_sha256=generation.generation_sha256,
            search_text="persistence sentinel original",
        )
    return {
        "schemaVersion": 1,
        "tenantId": tenant_id,
        "subjectId": _SUBJECT_ID,
        "generationSha256": generation.generation_sha256,
        "seedRetrievalPassed": True,
    }


def verify_restart_probe(
    dsn: str,
    *,
    tenant_id: str,
    generation_sha256: str,
) -> dict[str, object]:
    _identity(tenant_id, "restart probe tenant")
    if _SHA256.fullmatch(generation_sha256) is None:
        raise ValueError("restart probe generation identity is invalid")
    with TemporaryDirectory() as directory:
        successor = _generation(
            Path(directory),
            tenant_id=tenant_id,
            source_revision="restart-successor",
            body="Persistence sentinel successor is current.",
        )
    with psycopg.connect(dsn) as connection:
        _assert_retrieval(
            connection,
            tenant_id=tenant_id,
            expected_generation_sha256=generation_sha256,
            search_text="persistence sentinel original",
        )
        _stage_and_activate(connection, successor)
        try:
            search_postgres_knowledge_lexical(
                connection,
                principal=PrincipalKey(tenant_id, _SUBJECT_ID),
                purpose="knowledge.read",
                agent_capabilities=_CAPABILITIES,
                search_text="persistence sentinel original",
                expected_generation_sha256=generation_sha256,
            )
        except ValueError as error:
            if str(error) != "knowledge generation is stale":
                raise
        else:
            raise RuntimeError("stale knowledge generation remained queryable")
        _assert_retrieval(
            connection,
            tenant_id=tenant_id,
            expected_generation_sha256=successor.generation_sha256,
            search_text="persistence sentinel successor",
        )
    return {
        "schemaVersion": 1,
        "originalGenerationSha256": generation_sha256,
        "successorGenerationSha256": successor.generation_sha256,
        "retrievalRecoveredAfterRestart": True,
        "staleGenerationRejected": True,
        "successorRetrievalPassed": True,
    }


def _generation(
    root: Path,
    *,
    tenant_id: str,
    source_revision: str,
    body: str,
):
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n",
        encoding="utf-8",
    )
    (root / "projects").mkdir()
    (root / "permissions").mkdir()
    (root / "projects" / "restart-probe.md").write_text(
        f"""---
type: Project
title: Restart Probe
resource: yap://tenant/{tenant_id}/{_RESOURCE_ID}
timestamp: 2026-08-10T12:00:00Z
yap_schema: 1
provenance: {{source: synthetic-gate, source_revision: {source_revision}}}
---
# Restart Probe

{body}
""",
        encoding="utf-8",
    )
    (root / "permissions" / "projects.yml").write_text(
        f"""path_prefix: projects/
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: {_SUBJECT_ID}}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
        encoding="utf-8",
    )
    return compile_okf_bundle(
        root,
        tenant_id=tenant_id,
        source_revision=source_revision,
    )


def _stage_and_activate(connection, generation) -> None:
    admission = admit_curated_knowledge_generation(
        connection,
        reviewer=PrincipalKey(generation.tenant_id, _SUBJECT_ID),
        repository_revision=generation.source_revision,
        source_path="verification/restart-probe",
        source_manifest_sha256="c" * 64,
        generation=generation,
    )
    stage_compiled_generation(
        connection,
        generation,
        source_admission_sha256=admission.admission_sha256,
    )
    store_generation_embeddings(
        connection,
        tenant_id=generation.tenant_id,
        generation_sha256=generation.generation_sha256,
        embedding_model_id="synthetic-gate",
        embedding_model_revision="revision-1",
        embeddings={item.chunk_id: (0.0,) * 768 for item in generation.chunks},
    )
    activate_complete_generation(
        connection,
        tenant_id=generation.tenant_id,
        generation_sha256=generation.generation_sha256,
    )


def _assert_retrieval(
    connection,
    *,
    tenant_id: str,
    expected_generation_sha256: str,
    search_text: str,
) -> None:
    result = search_postgres_knowledge_lexical(
        connection,
        principal=PrincipalKey(tenant_id, _SUBJECT_ID),
        purpose="knowledge.read",
        agent_capabilities=_CAPABILITIES,
        search_text=search_text,
        expected_generation_sha256=expected_generation_sha256,
        maximum_results=1,
    )
    if (
        result.generation_sha256 != expected_generation_sha256
        or len(result.results) != 1
        or result.results[0].concept_id != _CONCEPT_ID
        or result.results[0].generation_sha256 != expected_generation_sha256
        or result.results[0].content_sha256 == ""
        or result.results[0].char_start < 0
        or result.results[0].char_end <= result.results[0].char_start
    ):
        raise RuntimeError("governed knowledge restart retrieval differs")


def _identity(value: str, field: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(f"{field} is invalid")
    return value


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("seed")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--tenant-id", required=True)
    verify.add_argument("--generation-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    dsn = os.environ.get("YAP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("YAP_TEST_POSTGRES_DSN is required")
    options = _parse_arguments()
    if options.operation == "seed":
        result = seed_restart_probe(dsn)
    else:
        result = verify_restart_probe(
            dsn,
            tenant_id=options.tenant_id,
            generation_sha256=options.generation_sha256,
        )
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
