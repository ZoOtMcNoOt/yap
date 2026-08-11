import unittest
from pathlib import Path


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
            "--endpoint ${YAP_PROVIDER_ENDPOINT}",
            "--expected-model ${YAP_PROVIDER_MODEL}",
            "--state-path /run/yap-provider-%i/service-state.json",
            "--launcher ${YAP_PROVIDER_LAUNCHER}",
        ):
            self.assertIn(control, self.unit)
        self.assertIn("  --\n", self.unit)
        self.assertNotIn("YAP_PROVIDER_SERVICE", self.unit)
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
        self.assertIn('if [ "$(id -u "$YAP_PROVIDER_OWNER")" -eq 0 ]', self.installer)
        self.assertIn("install -m 0755 -o root -g root", self.installer)
        self.assertIn("install -d -m 0700 -o root -g root /etc/yap/providers", self.installer)
        self.assertIn("systemctl daemon-reload", self.installer)
        self.assertIn('[ -L "$binary_destination" ]', self.installer)
        self.assertIn('[ -L "$unit_destination" ]', self.installer)
        self.assertIn('[ ! -f "$binary_destination" ]', self.installer)
        self.assertIn('[ ! -f "$unit_destination" ]', self.installer)
        for forbidden in ("useradd", "groupadd", "usermod", "systemctl enable", "systemctl start"):
            self.assertNotIn(forbidden, self.installer)


if __name__ == "__main__":
    unittest.main()
