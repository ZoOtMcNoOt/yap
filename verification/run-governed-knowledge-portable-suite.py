from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from yap_server.evaluation.governed_knowledge_gate import (
    _EXPECTED_PORTABLE_MODULES,
    _EXPECTED_PORTABLE_TEST_COUNT,
)


def main() -> int:
    server_root = Path.cwd().resolve(strict=True)
    if not (server_root / "tests").is_dir():
        raise RuntimeError("governed knowledge portable suite root differs")
    sys.path.insert(0, str(server_root))
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        list(_EXPECTED_PORTABLE_MODULES)
    )
    if suite.countTestCases() != _EXPECTED_PORTABLE_TEST_COUNT:
        raise RuntimeError("governed knowledge portable test membership differs")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "expectedFailures": len(result.expectedFailures),
        "modules": list(_EXPECTED_PORTABLE_MODULES),
        "schemaVersion": 1,
        "skipped": len(result.skipped),
        "testsRun": result.testsRun,
        "unexpectedSuccesses": len(result.unexpectedSuccesses),
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
