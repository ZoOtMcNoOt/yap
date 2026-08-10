from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import unittest

import psycopg


_MODULES = (
    "tests.knowledge.test_postgres_generation_ledger",
    "tests.knowledge.test_postgres_permission_safe_retrieval",
    "tests.knowledge.test_reviewed_meeting_postgres_route",
    "tests.knowledge.test_terminology_ledger",
)
_EXPECTED_TEST_COUNT = 14


def _configure_server_test_imports() -> None:
    server_root = Path.cwd().resolve(strict=True)
    if not (server_root / "tests").is_dir():
        raise RuntimeError("governed knowledge Postgres suite root differs")
    sys.path.insert(0, str(server_root))


def _postgres_version(dsn: str) -> str:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        postgres_version = connection.execute("SHOW server_version").fetchone()
    if postgres_version is None or not isinstance(postgres_version[0], str):
        raise RuntimeError("the required Postgres runtime is unavailable")
    return postgres_version[0]


def _installed_pgvector_version(dsn: str) -> str:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        pgvector_version = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    if pgvector_version is None or not isinstance(pgvector_version[0], str):
        raise RuntimeError("the required pgvector extension is not installed")
    return pgvector_version[0]


def _load_required_suite() -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suites: list[unittest.TestSuite] = []
    for module_name in _MODULES:
        module = importlib.import_module(module_name)
        suite = loader.loadTestsFromModule(module)
        if suite.countTestCases() < 1:
            raise RuntimeError(f"required Postgres test module is empty: {module_name}")
        suites.append(suite)
    if loader.errors:
        raise RuntimeError("required Postgres test modules could not be loaded")
    suite = unittest.TestSuite(suites)
    if suite.countTestCases() != _EXPECTED_TEST_COUNT:
        raise RuntimeError(
            "required Postgres test count differs from the gate contract"
        )
    return suite


def main() -> int:
    if sys.argv[1:]:
        raise RuntimeError("the governed-knowledge Postgres suite takes no arguments")
    _configure_server_test_imports()
    dsn = os.environ.get("YAP_TEST_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("YAP_TEST_POSTGRES_DSN is required")
    postgres_version = _postgres_version(dsn)
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(
        _load_required_suite()
    )
    passed = (
        result.wasSuccessful()
        and result.testsRun == _EXPECTED_TEST_COUNT
        and not result.skipped
        and not result.expectedFailures
        and not result.unexpectedSuccesses
    )
    if not passed:
        return 1
    pgvector_version = _installed_pgvector_version(dsn)
    print(
        json.dumps(
            {
                "modules": list(_MODULES),
                "pgvectorVersion": pgvector_version,
                "postgresVersion": postgres_version,
                "schemaVersion": 1,
                "skipped": 0,
                "testsRun": result.testsRun,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
