import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_LAUNCH = (
    REPO_ROOT / "infra" / "yap-server-node" / "development-batch-server.sh"
)


class DevelopmentBatchServerContractTests(unittest.TestCase):
    @staticmethod
    def _write_executable(path: Path, source: str) -> None:
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)

    def test_launch_is_clean_head_foreground_and_loopback_only(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        self.assertIn('git -C "$repo_root" rev-parse --is-inside-work-tree', script)
        self.assertIn('git -C "$repo_root" rev-parse HEAD', script)
        self.assertIn("status --porcelain=v1 --untracked-files=normal", script)
        self.assertIn('YAP_UV_BINARY:=uv', script)
        self.assertIn('command -v "$YAP_UV_BINARY"', script)
        for locked_runtime_argument in (
            '--project "$repo_root/server"',
            "--offline",
            "sync",
            "--locked",
            "--no-dev",
            "--python python3.12",
            "--no-python-downloads",
            '"$server_python" -m yap_server',
        ):
            self.assertIn(locked_runtime_argument, script)
        self.assertNotIn("  python3.12 -m yap_server", script)
        self.assertNotIn("python3.12 -c", script)
        self.assertNotIn(" run \\", script)
        self.assertIn("exec env", script)
        self.assertIn("YAP_SERVER_CONFIGURATION=development", script)
        self.assertIn("YAP_AUTH_MODE=development_loopback", script)
        self.assertIn("YAP_SERVER_HOST=127.0.0.1", script)
        self.assertIn("YAP_SERVER_PORT=18765", script)
        self.assertIn("YAP_BATCH_ASR_ENABLED=1", script)
        self.assertIn('YAP_CHECKED_HEAD="$YAP_CHECKED_HEAD"', script)
        self.assertIn("YAP_COHERE_ASR_RUNTIME=vllm", script)
        self.assertIn(
            'YAP_COHERE_VLLM_ENDPOINT="$YAP_COHERE_VLLM_ENDPOINT"',
            script,
        )
        self.assertIn(
            'YAP_COHERE_VLLM_API_KEY="$YAP_COHERE_VLLM_API_KEY"',
            script,
        )
        self.assertIn(
            'YAP_NEMOTRON_ASR_RUNTIME="$YAP_NEMOTRON_ASR_RUNTIME"',
            script,
        )
        self.assertIn(
            'YAP_NEMOTRON_NEMO_ENDPOINT="$YAP_NEMOTRON_NEMO_ENDPOINT"',
            script,
        )
        self.assertIn(
            'YAP_NEMOTRON_NEMO_API_KEY="$YAP_NEMOTRON_NEMO_API_KEY"',
            script,
        )
        self.assertIn('YAP_ASR_MODEL_LOCK="$YAP_ASR_MODEL_LOCK"', script)
        self.assertIn(
            'YAP_ASR_CAPABILITY_LOCK="$YAP_ASR_CAPABILITY_LOCK"',
            script,
        )
        self.assertIn('YAP_ASR_MODEL_DIR="$YAP_ASR_MODEL_DIR"', script)
        self.assertIn(
            'YAP_BATCH_JOB_STORAGE_DIR="$YAP_BATCH_JOB_STORAGE_DIR"', script
        )
        for language_detection_setting in (
            'YAP_LANGUAGE_DETECTION_ENABLED="$YAP_LANGUAGE_DETECTION_ENABLED"',
            'YAP_LANGUAGE_DETECTION_COMPONENT_LOCK="$YAP_LANGUAGE_DETECTION_COMPONENT_LOCK"',
            'YAP_LANGUAGE_DETECTION_MODEL_DIR="$YAP_LANGUAGE_DETECTION_MODEL_DIR"',
            'YAP_LANGUAGE_DETECTION_TIMEOUT_SECONDS="$YAP_LANGUAGE_DETECTION_TIMEOUT_SECONDS"',
            'YAP_LANGUAGE_DETECTION_DOCKER_BINARY="$YAP_LANGUAGE_DETECTION_DOCKER_BINARY"',
            'YAP_LANGUAGE_DETECTION_WORKER_IMAGE="$YAP_LANGUAGE_DETECTION_WORKER_IMAGE"',
            'YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT="$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT"',
            'YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256="$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256"',
        ):
            self.assertIn(language_detection_setting, script)
        self.assertIn('storage_mode="$(stat -Lc \'%a\'', script)
        self.assertIn('if [ "$storage_mode" != "700" ]', script)
        for forbidden in (
            "0.0.0.0",
            "localhost",
            "nohup",
            "systemctl",
            "ufw ",
            "--publish",
        ):
            self.assertNotIn(forbidden, script)

    def test_launch_requires_the_checked_head_and_private_vllm_inputs(self) -> None:
        script = SERVER_LAUNCH.read_text(encoding="utf-8")

        for required in (
            "YAP_CHECKED_HEAD:?",
            "YAP_ASR_MODEL_DIR:?",
            "YAP_BATCH_JOB_STORAGE_DIR:?",
            "YAP_COHERE_VLLM_API_KEY:?",
        ):
            self.assertIn(required, script)
        self.assertIn(
            "server/cohere-vllm-serving.lock.json",
            script,
        )
        self.assertIn("server/nemotron-nemo-serving.lock.json", script)
        self.assertIn("nemo-resident", script)
        self.assertIn("http://127.0.0.1:18001", script)
        self.assertIn(
            "resident Nemotron requires an explicit candidate capability lock",
            script,
        )
        self.assertIn(
            "candidate capability locks must remain outside the repository",
            script,
        )
        self.assertIn('YAP_LANGUAGE_DETECTION_ENABLED:=0', script)
        self.assertIn('YAP_LANGUAGE_DETECTION_MODEL_DIR:?', script)
        self.assertIn('YAP_LANGUAGE_DETECTION_WORKER_IMAGE:?', script)
        self.assertIn('YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT:?', script)
        self.assertIn(
            'YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256:?',
            script,
        )
        self.assertIn(
            "YAP_LANGUAGE_DETECTION_ENABLED must be 0 or 1",
            script,
        )
        self.assertNotIn("nvcr.io/nvidia/pytorch", script)
        self.assertNotIn("YAP_ASR_WORKER_IMAGE:?", script)

    @unittest.skipUnless(os.name == "posix", "the launcher targets Linux")
    def test_launch_syncs_clean_uv_environment_and_execs_python(self) -> None:
        checked_head = "a" * 40
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            launcher = root / "infra" / "yap-server-node" / SERVER_LAUNCH.name
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(SERVER_LAUNCH.read_bytes())
            launcher.chmod(0o700)

            server = root / "server"
            server.mkdir()
            for lock_name in (
                "cohere-vllm-serving.lock.json",
                "asr-capabilities.lock.json",
            ):
                (server / lock_name).write_text("{}\n", encoding="utf-8")
            model = root / "model"
            model.mkdir(mode=0o700)
            storage = root / "storage"
            storage.mkdir(mode=0o700)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            capture = root / "uv-capture.txt"
            environment_capture = root / "uv-environment.txt"
            server_capture = root / "server-capture.txt"
            server_environment_capture = root / "server-environment.txt"
            server_python = server / ".venv" / "bin" / "python"
            server_python_stub = root / "server-python-stub"

            self._write_executable(
                fake_bin / "git",
                """#!/bin/sh
case "$*" in
  *"--is-inside-work-tree"*) printf '%s\\n' true ;;
  *"rev-parse HEAD"*) printf '%s\\n' "$YAP_TEST_CHECKED_HEAD" ;;
  *"status --porcelain=v1 --untracked-files=normal"*) ;;
  *) exit 64 ;;
esac
""",
            )
            self._write_executable(
                fake_bin / "uv",
                """#!/bin/sh
printf '%s\\n' "$@" >"$YAP_TEST_UV_CAPTURE"
printf '%s\\n' \
  "${UV_NO_SYNC-unset}|${UV_PROJECT_ENVIRONMENT-unset}|${UV_PROJECT-unset}|${UV_WORKING_DIR-unset}|${UV_NO_PROJECT-unset}|${UV_PYTHON-unset}|${VIRTUAL_ENV-unset}|${PYTHONHOME-unset}|${PYTHONPLATLIBDIR-unset}|${PYTHONPATH-unset}|${PYTHONUSERBASE-unset}|${PYTHONNOUSERSITE-unset}" \
  >"$YAP_TEST_UV_ENVIRONMENT_CAPTURE"
mkdir -p "$(dirname "$YAP_TEST_SERVER_PYTHON")"
cp "$YAP_TEST_SERVER_PYTHON_STUB" "$YAP_TEST_SERVER_PYTHON"
chmod 700 "$YAP_TEST_SERVER_PYTHON"
""",
            )
            self._write_executable(
                server_python_stub,
                """#!/bin/sh
if [ "$1" = "-c" ]; then
  printf '%s\\n' 3.12
  exit 0
fi
printf '%s\\n' "$@" >"$YAP_TEST_SERVER_CAPTURE"
printf '%s\\n' \
  "${UV_NO_SYNC-unset}|${UV_PROJECT_ENVIRONMENT-unset}|${UV_PROJECT-unset}|${UV_WORKING_DIR-unset}|${UV_NO_PROJECT-unset}|${UV_PYTHON-unset}|${VIRTUAL_ENV-unset}|${PYTHONHOME-unset}|${PYTHONPLATLIBDIR-unset}|${PYTHONUSERBASE-unset}|${PYTHONNOUSERSITE-unset}|${PYTHONPATH-unset}|${YAP_SERVER_CONFIGURATION-unset}|${YAP_AUTH_MODE-unset}" \
  >"$YAP_TEST_SERVER_ENVIRONMENT_CAPTURE"
exit 23
""",
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                    "YAP_ASR_MODEL_DIR": str(model),
                    "YAP_BATCH_JOB_STORAGE_DIR": str(storage),
                    "YAP_CHECKED_HEAD": checked_head,
                    "YAP_COHERE_VLLM_API_KEY": "test-only-key",
                    "YAP_TEST_CHECKED_HEAD": checked_head,
                    "YAP_TEST_UV_CAPTURE": str(capture),
                    "YAP_TEST_UV_ENVIRONMENT_CAPTURE": str(environment_capture),
                    "YAP_TEST_SERVER_CAPTURE": str(server_capture),
                    "YAP_TEST_SERVER_ENVIRONMENT_CAPTURE": str(
                        server_environment_capture
                    ),
                    "YAP_TEST_SERVER_PYTHON": str(server_python),
                    "YAP_TEST_SERVER_PYTHON_STUB": str(server_python_stub),
                    "YAP_UV_BINARY": str(fake_bin / "uv"),
                    "UV_NO_SYNC": "1",
                    "UV_PROJECT_ENVIRONMENT": str(root / "stale-environment"),
                    "UV_PROJECT": str(root / "wrong-project"),
                    "UV_WORKING_DIR": str(root / "wrong-working-directory"),
                    "UV_NO_PROJECT": "1",
                    "UV_PYTHON": str(root / "wrong-python"),
                    "VIRTUAL_ENV": str(root / "active-environment"),
                    "PYTHONHOME": str(root / "wrong-python-home"),
                    "PYTHONPLATLIBDIR": "wrong-platlib",
                    "PYTHONPATH": str(root / "wrong-python-path"),
                    "PYTHONUSERBASE": str(root / "wrong-user-base"),
                    "YAP_AUTH_MODE": "entra",
                    "YAP_SERVER_CONFIGURATION": "release",
                }
            )

            completed = subprocess.run(
                [str(launcher)],
                cwd=root,
                env=environment,
                capture_output=True,
                check=False,
                text=True,
            )

            self.assertEqual(completed.returncode, 23, completed.stderr)
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                [
                    "--offline",
                    "--project",
                    str(server),
                    "sync",
                    "--locked",
                    "--no-dev",
                    "--python",
                    "python3.12",
                    "--no-python-downloads",
                ],
            )
            self.assertEqual(
                environment_capture.read_text(encoding="utf-8").strip(),
                "unset|unset|unset|unset|unset|unset|unset|unset|unset|unset|unset|1",
            )
            self.assertEqual(
                server_capture.read_text(encoding="utf-8").splitlines(),
                ["-m", "yap_server"],
            )
            self.assertEqual(
                server_environment_capture.read_text(encoding="utf-8").strip(),
                (
                    "unset|unset|unset|unset|unset|unset|unset|unset|unset|unset|1|"
                    f"{server / 'src'}|development|development_loopback"
                ),
            )


if __name__ == "__main__":
    unittest.main()
