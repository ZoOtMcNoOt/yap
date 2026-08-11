import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
UNIT_TEMPLATE = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "yap-provider-supervisor@.service.in"
)
INSTALLER = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "install-provider-supervisor-service.sh"
)
PROFILE_PYTHON_SOURCE = REPOSITORY_ROOT / "server" / "src" / "yap_server" / "pools"
PROFILE_PYTHON_MODULES = (
    "agent_model_snapshot.py",
    "agent_vllm_launch_contract.py",
    "agent_vllm_service_profile.py",
    "agent_vllm_service_profile_cli.py",
    "numeric_loopback_endpoint.py",
)


class ProviderSupervisorServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.unit = UNIT_TEMPLATE.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_unit_assigns_outer_containment_without_duplicating_child_restart(self) -> None:
        self.assertIn("User=@YAP_PROVIDER_OWNER@", self.unit)
        self.assertIn("Group=@YAP_PROVIDER_GROUP@", self.unit)
        self.assertIn("KillMode=mixed", self.unit)
        self.assertIn("Restart=on-abnormal", self.unit)
        self.assertIn("StartLimitIntervalSec=60", self.unit)
        self.assertIn("StartLimitBurst=3", self.unit)
        self.assertNotIn("Restart=always", self.unit)
        self.assertNotIn("Restart=on-failure", self.unit)

    def test_unit_uses_one_explicit_supervisor_and_required_private_configuration(self) -> None:
        self.assertIn("EnvironmentFile=/etc/yap/providers/%i.env", self.unit)
        self.assertIn("RuntimeDirectory=yap-provider-%i", self.unit)
        self.assertIn("RuntimeDirectoryMode=0700", self.unit)
        self.assertIn("UMask=0077", self.unit)
        self.assertIn(
            "ExecStart=/usr/local/libexec/yap-provider-supervisor \\",
            self.unit,
        )
        for control in (
            "--service %i",
            "--profile ${YAP_PROVIDER_PROFILE}",
            "--profile-sha256 ${YAP_PROVIDER_PROFILE_SHA256}",
            "--candidate-lock ${YAP_PROVIDER_CANDIDATE_LOCK}",
            "--state-path /run/yap-provider-%i/service-state.json",
            "--launcher ${YAP_PROVIDER_LAUNCHER}",
        ):
            self.assertIn(control, self.unit)
        self.assertIn("  --\n", self.unit)
        self.assertNotIn("YAP_PROVIDER_SERVICE", self.unit)
        self.assertNotIn("YAP_PROVIDER_ENDPOINT", self.unit)
        self.assertNotIn("YAP_PROVIDER_MODEL", self.unit)
        self.assertNotIn("docker ", self.unit)
        self.assertNotIn("API_KEY", self.unit)
        self.assertNotIn("fallback", self.unit.lower())

    def test_unit_has_a_bounded_hardening_profile_without_network_namespace_substitution(
        self,
    ) -> None:
        for policy in (
            "NoNewPrivileges=yes",
            "PrivateDevices=yes",
            "PrivateTmp=yes",
            "ProtectControlGroups=yes",
            "ProtectHome=read-only",
            "ProtectKernelModules=yes",
            "ProtectKernelTunables=yes",
            "ProtectSystem=strict",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            "RestrictRealtime=yes",
            "RestrictSUIDSGID=yes",
        ):
            self.assertIn(policy, self.unit)
        self.assertIn("PrivateNetwork=no", self.unit)

    def test_installer_requires_an_existing_nonroot_owner_and_only_installs_files(self) -> None:
        self.assertIn(': "${YAP_PROVIDER_OWNER:?', self.installer)
        self.assertIn(': "${YAP_PROVIDER_GROUP:?', self.installer)
        self.assertIn(': "${YAP_SUPERVISOR_BINARY:?', self.installer)
        for required in (
            "YAP_CHECKED_HEAD",
            "YAP_RAPID_MODEL_SNAPSHOT",
            "YAP_COMPLEX_MODEL_SNAPSHOT",
            "YAP_RAPID_PRIVATE_INFERENCE_NETWORK",
            "YAP_COMPLEX_PRIVATE_INFERENCE_NETWORK",
            "YAP_RAPID_RUNTIME_OWNER_TOKEN",
            "YAP_COMPLEX_RUNTIME_OWNER_TOKEN",
        ):
            self.assertIn(f': "${{{required}:?', self.installer)
        self.assertIn('if [ "$(id -u "$YAP_PROVIDER_OWNER")" -eq 0 ]', self.installer)
        self.assertIn("install -m 0755 -o root -g root", self.installer)
        self.assertIn("install -d -m 0700 -o root -g root /etc/yap/providers", self.installer)
        self.assertIn('"$profile_source_root/rapid-automation.json"', self.installer)
        self.assertIn('"$profile_source_root/complex-orchestration.json"', self.installer)
        self.assertIn("agent-reasoning-candidates.lock.json", self.installer)
        self.assertIn("agent-vllm-server.sh", self.installer)
        self.assertIn("private-container-loopback-proxy.sh", self.installer)
        self.assertIn("owned-process-group.sh", self.installer)
        self.assertIn("owned-process-supervisor.py", self.installer)
        self.assertIn("agent_vllm_service_profile_cli.py", self.installer)
        self.assertIn("numeric_loopback_endpoint.py", self.installer)
        self.assertIn("rev-parse HEAD", self.installer)
        self.assertIn("status --porcelain=v1 --untracked-files=all", self.installer)
        self.assertIn("rapid-automation.env", self.installer)
        self.assertIn("complex-orchestration.env", self.installer)
        self.assertIn("install -m 0600 -o root -g root", self.installer)
        self.assertIn(
            "agent services require distinct private inference networks",
            self.installer,
        )
        self.assertIn("realpath -e", self.installer)
        self.assertIn("must not contain symbolic-link ancestry", self.installer)
        self.assertIn("systemctl daemon-reload", self.installer)
        self.assertIn('if [ -L "$path" ]', self.installer)
        self.assertIn('[ ! -f "$path" ]', self.installer)
        self.assertIn('validate_destination "$destination"', self.installer)
        for forbidden in ("useradd", "groupadd", "usermod", "systemctl enable", "systemctl start"):
            self.assertNotIn(forbidden, self.installer)

    def test_installed_profile_reader_is_a_closed_minimal_python_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            python_root = Path(temporary) / "python"
            destination = python_root / "yap_server" / "pools"
            destination.mkdir(parents=True)
            for module in PROFILE_PYTHON_MODULES:
                shutil.copy2(PROFILE_PYTHON_SOURCE / module, destination / module)
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(python_root)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "yap_server.pools.agent_vllm_service_profile_cli",
                    "--help",
                ],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Read one exact Yap agent vLLM service profile", result.stdout)


if __name__ == "__main__":
    unittest.main()
