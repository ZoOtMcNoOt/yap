from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


SERVER_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = SERVER_ROOT / "runtime" / "asr-evaluation"


class AsrEvaluationRuntimeTests(unittest.TestCase):
    def test_scoring_overlay_matches_the_locked_evaluation_extra(self) -> None:
        project = tomllib.loads(
            (SERVER_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        requirements = (RUNTIME_ROOT / "requirements.lock").read_text(
            encoding="utf-8"
        )
        uv_lock = (SERVER_ROOT / "uv.lock").read_text(encoding="utf-8")

        self.assertEqual(
            project["project"]["optional-dependencies"]["evaluation"],
            ["rapidfuzz==3.14.5", "regex==2026.7.10"],
        )
        self.assertIn("rapidfuzz==3.14.5", requirements)
        self.assertIn(
            "01550fe5f60fd176aa66b7611289d46dc4aa4b1b904874c7b6d1d54e581c5ec1",
            requirements,
        )
        self.assertIn("regex==2026.7.10", requirements)
        self.assertIn(
            "f3463a5f26be513a49e4d497debcf1b252a2db7b92c77d89621aa90b83d2dd38",
            requirements,
        )
        for locked_line in requirements.splitlines():
            if "sha256:" in locked_line:
                self.assertIn(locked_line.split("sha256:", 1)[1], uv_lock)

    def test_overlay_keeps_the_worker_unprivileged_and_names_its_function(self) -> None:
        dockerfile = (RUNTIME_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("ARG YAP_ASR_WORKER_IMAGE", dockerfile)
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("assert sys.version_info[:2] == (3, 12)", dockerfile)
        self.assertIn("WORKDIR /opt/yap-evaluation", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn(
            '"yap_server.evaluation.fleurs_cohere_comparator"',
            dockerfile,
        )
        self.assertNotIn("phase", dockerfile.casefold())

    def test_overlay_notice_marks_the_dependencies_nonproduction(self) -> None:
        notice = (RUNTIME_ROOT / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("RapidFuzz 3.14.5", notice)
        self.assertIn("regex 2026.7.10", notice)
        self.assertIn("not part of the desktop application or serving hot path", notice)


if __name__ == "__main__":
    unittest.main()
