from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from yap_server.agents.student_runtime import (
    STUDENT_ADMISSION_SOCKET,
    STUDENT_CANDIDATE_LOCK,
    STUDENT_KNOWLEDGE_DSN_FILE,
    STUDENT_PROFILE,
    STUDENT_RUNTIME,
    build_student_runtime,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE = REPOSITORY_ROOT / "server" / "agent-service-profiles" / "rapid-automation.json"
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"


def _environment(socket_path: Path, dsn_path: Path) -> dict[str, str]:
    return {
        STUDENT_RUNTIME: "warm_qwen",
        STUDENT_ADMISSION_SOCKET: str(socket_path),
        STUDENT_PROFILE: str(PROFILE),
        STUDENT_CANDIDATE_LOCK: str(CANDIDATE_LOCK),
        STUDENT_KNOWLEDGE_DSN_FILE: str(dsn_path),
    }


class StudentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dsn_path = Path(self.temporary.name).resolve() / "knowledge.dsn"
        self.dsn_path.write_text("dbname=yap", encoding="utf-8")
        self.dsn_path.chmod(0o600)

    def _environment(self, socket_path: Path) -> dict[str, str]:
        return _environment(socket_path, self.dsn_path)

    def test_runtime_is_disabled_only_without_student_paths(self) -> None:
        self.assertIsNone(
            build_student_runtime({}, authenticated_team_mode=True)
        )
        with self.assertRaisesRegex(ValueError, "explicit runtime mode"):
            build_student_runtime(
                {STUDENT_PROFILE: str(PROFILE)},
                authenticated_team_mode=True,
            )

    def test_warm_qwen_runtime_binds_exact_route_and_team_identity(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        runtime = build_student_runtime(
            self._environment(socket_path),
            authenticated_team_mode=True,
        )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(runtime.profile_id, "rapid-automation")
        self.assertEqual(runtime.model, "nvidia/Qwen3.6-35B-A3B-NVFP4")
        self.assertEqual(
            runtime.profile_sha256,
            "14712e6951802daaae323a3a7d69e78a8b3d5ac32ad52cbd0f546df327649da8",
        )
        self.assertEqual(
            runtime.candidate_lock_sha256,
            "3e9218c8245863c5f1bda8166a629361b51ed23cec259d7c69f11b1dee83d013",
        )
        self.assertEqual(runtime.maximum_output_tokens, 512)

        with self.assertRaisesRegex(ValueError, "organization authentication"):
            build_student_runtime(
                self._environment(socket_path),
                authenticated_team_mode=False,
            )

    def test_mode_paths_and_profile_bytes_fail_closed(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        environment = self._environment(socket_path)
        environment[STUDENT_RUNTIME] = "ollama"
        with self.assertRaisesRegex(ValueError, "runtime mode is invalid"):
            build_student_runtime(environment, authenticated_team_mode=True)

        environment = self._environment(socket_path)
        environment[STUDENT_PROFILE] = "relative/profile.json"
        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            build_student_runtime(environment, authenticated_team_mode=True)

        with tempfile.TemporaryDirectory() as temporary:
            changed_profile = Path(temporary).resolve() / "rapid.json"
            changed_profile.write_bytes(PROFILE.read_bytes() + b"\n")
            environment = self._environment(socket_path)
            environment[STUDENT_PROFILE] = str(changed_profile)
            with self.assertRaisesRegex(ValueError, "profile bytes differ"):
                build_student_runtime(environment, authenticated_team_mode=True)


if __name__ == "__main__":
    unittest.main()
