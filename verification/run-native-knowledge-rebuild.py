"""Exercise the native rebuild client against the actual owned SQL/HTTP fixture.

Uses synthetic principals/vectors. No model or enterprise credential is acquired.
The locked native test binary must already be built; no source mutation occurs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "src"))
from tests.api.test_knowledge_embedding_preparation_api import (
    DSN,
    KnowledgeEmbeddingPreparationApiTests,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-binary", required=True, type=Path)
    args = parser.parse_args()
    if not DSN:
        raise RuntimeError("An owned test PostgreSQL runtime is required.")
    binary = args.test_binary.resolve(strict=True)
    fixture = KnowledgeEmbeddingPreparationApiTests("runTest")
    try:
        fixture.setUp()
        host, port = fixture.server.server_address[:2]
        env = dict(os.environ)
        env.update(
            YAP_REBUILD_TEST_ORIGIN=f"http://{host}:{port}",
            YAP_REBUILD_TEST_TARGET=fixture.source_generation.generation_sha256,
            YAP_REBUILD_TEST_BASE=fixture.base.generation_sha256,
        )
        result = subprocess.run(
            [
                str(binary),
                "server_connector::knowledge_rebuild::tests::native_real_postgres_rebuild_journey",
                "--ignored",
                "--exact",
            ],
            env=env,
            check=False,
            timeout=90,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        print(result.stdout.strip())
        result.check_returncode()
        if "test result: ok. 1 passed; 0 failed; 0 ignored;" not in result.stdout:
            raise AssertionError(
                "Native fixture did not execute exactly one passing case."
            )
        if len(fixture.provider_requests) != 1:
            raise AssertionError("Replay must not regenerate completed embeddings.")
        print(
            "Native authenticated source/stage/embedding/publication/replay/retained restore verified with real HTTP/PostgreSQL; fixture identities/vectors only."
        )
    finally:
        fixture.tearDown() if hasattr(fixture, "server") else None
        fixture.doCleanups()


if __name__ == "__main__":
    main()
