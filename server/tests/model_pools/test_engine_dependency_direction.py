from __future__ import annotations

import ast
from pathlib import Path
import unittest


POOLS_ROOT = Path(__file__).resolve().parents[2] / "src" / "yap_server" / "pools"
WORKER_MODULE = "yap_server.pools.batch_asr_worker"


class EngineDependencyDirectionTests(unittest.TestCase):
    def test_provider_engines_depend_on_pcm_contract_not_worker_entrypoint(
        self,
    ) -> None:
        violations: list[str] = []
        for name in ("cohere_engine.py", "nemotron_engine.py"):
            path = POOLS_ROOT / name
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = node.module if isinstance(node, ast.ImportFrom) else None
                if module == WORKER_MODULE:
                    violations.append(f"{name}:{node.lineno}")
                if isinstance(node, ast.Import):
                    violations.extend(
                        f"{name}:{node.lineno}"
                        for alias in node.names
                        if alias.name == WORKER_MODULE
                    )

        self.assertEqual(
            violations,
            [],
            "provider engines imported the executable worker entrypoint",
        )


if __name__ == "__main__":
    unittest.main()
