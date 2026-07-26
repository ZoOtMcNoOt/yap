from __future__ import annotations

import ast
from pathlib import Path
import unittest


POOLS_ROOT = Path(__file__).resolve().parents[2] / "src" / "yap_server" / "pools"
WORKER_MODULE = "yap_server.pools.batch_asr_worker"


def _worker_dependents() -> list[Path]:
    return sorted(
        path
        for path in POOLS_ROOT.glob("*.py")
        if path.name != "batch_asr_worker.py"
    )


def _imports_worker_entrypoint(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name == WORKER_MODULE for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return False
    if node.module == WORKER_MODULE:
        return True
    if node.level > 0 and (node.module or "").split(".")[-1] == "batch_asr_worker":
        return True
    package_import = node.module in (None, "yap_server.pools") or (
        node.level > 0 and (node.module or "").split(".")[-1] == "pools"
    )
    return package_import and any(
        alias.name == "batch_asr_worker" for alias in node.names
    )


def _worker_import_lines(source: str, *, filename: str = "<test>") -> list[int]:
    tree = ast.parse(source, filename=filename)
    return [node.lineno for node in ast.walk(tree) if _imports_worker_entrypoint(node)]


class EngineDependencyDirectionTests(unittest.TestCase):
    def test_pool_modules_do_not_depend_on_the_executable_worker_entrypoint(
        self,
    ) -> None:
        violations: list[str] = []
        dependents = _worker_dependents()
        self.assertTrue(dependents, "no pool modules were enumerated")
        for path in dependents:
            violations.extend(
                f"{path.name}:{line}"
                for line in _worker_import_lines(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                )
            )

        self.assertEqual(
            violations,
            [],
            "a pool module imported the executable worker entrypoint",
        )

    def test_guard_detects_absolute_and_relative_worker_imports(self) -> None:
        source = "\n".join(
            (
                "import yap_server.pools.batch_asr_worker",
                "from yap_server.pools.batch_asr_worker import transcribe",
                "from yap_server.pools import batch_asr_worker",
                "from .batch_asr_worker import transcribe",
                "from . import batch_asr_worker",
                "from ..pools import batch_asr_worker",
            )
        )

        self.assertEqual(_worker_import_lines(source), [1, 2, 3, 4, 5, 6])


if __name__ == "__main__":
    unittest.main()
