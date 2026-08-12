from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from yap_server.agents.transcript_correction_runtime import (
    TRANSCRIPT_CORRECTION_ADMISSION_SOCKET,
    TRANSCRIPT_CORRECTION_CANDIDATE_LOCK,
    TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE,
    TRANSCRIPT_CORRECTION_PROFILE,
    TRANSCRIPT_CORRECTION_RUNTIME,
    build_transcript_correction_runtime,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE = REPOSITORY_ROOT / "server" / "agent-service-profiles" / "rapid-automation.json"
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"


def _environment(socket_path: Path, dsn_path: Path) -> dict[str, str]:
    return {
        TRANSCRIPT_CORRECTION_RUNTIME: "warm_qwen",
        TRANSCRIPT_CORRECTION_ADMISSION_SOCKET: str(socket_path),
        TRANSCRIPT_CORRECTION_PROFILE: str(PROFILE),
        TRANSCRIPT_CORRECTION_CANDIDATE_LOCK: str(CANDIDATE_LOCK),
        TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE: str(dsn_path),
    }


class TranscriptCorrectionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dsn_path = Path(self.temporary.name).resolve() / "knowledge.dsn"
        self.dsn_path.write_text("dbname=yap", encoding="utf-8")
        self.dsn_path.chmod(0o600)

    def _environment(self, socket_path: Path) -> dict[str, str]:
        return _environment(socket_path, self.dsn_path)

    def test_runtime_is_disabled_only_when_no_scribe_configuration_is_present(
        self,
    ) -> None:
        self.assertIsNone(
            build_transcript_correction_runtime(
                {},
                authenticated_team_mode=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "requires an explicit runtime mode"):
            build_transcript_correction_runtime(
                {TRANSCRIPT_CORRECTION_PROFILE: str(PROFILE)},
                authenticated_team_mode=True,
            )

    def test_warm_qwen_runtime_binds_exact_profile_and_team_identity(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        runtime = build_transcript_correction_runtime(
            self._environment(socket_path),
            authenticated_team_mode=True,
        )
        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.addCleanup(runtime.close)

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
            build_transcript_correction_runtime(
                self._environment(socket_path),
                authenticated_team_mode=False,
            )

    def test_mode_paths_and_profile_bytes_fail_closed(self) -> None:
        socket_path = (Path(tempfile.gettempdir()) / "agent-admission.sock").resolve()
        environment = self._environment(socket_path)
        environment[TRANSCRIPT_CORRECTION_RUNTIME] = "ollama"
        with self.assertRaisesRegex(ValueError, "runtime mode is invalid"):
            build_transcript_correction_runtime(
                environment,
                authenticated_team_mode=True,
            )

        environment = self._environment(socket_path)
        environment[TRANSCRIPT_CORRECTION_PROFILE] = "relative/profile.json"
        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            build_transcript_correction_runtime(
                environment,
                authenticated_team_mode=True,
            )

        with tempfile.TemporaryDirectory() as temporary:
            changed_profile = Path(temporary).resolve() / "rapid.json"
            changed_profile.write_bytes(PROFILE.read_bytes() + b"\n")
            environment = self._environment(socket_path)
            environment[TRANSCRIPT_CORRECTION_PROFILE] = str(changed_profile)
            with self.assertRaisesRegex(ValueError, "profile bytes differ"):
                build_transcript_correction_runtime(
                    environment,
                    authenticated_team_mode=True,
                )


if __name__ == "__main__":
    unittest.main()
