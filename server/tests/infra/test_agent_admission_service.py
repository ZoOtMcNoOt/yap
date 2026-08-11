from __future__ import annotations

from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[3]
_UNIT = (
    _ROOT / "infra/yap-server-node/yap-agent-admission-broker.service.in"
).read_text(encoding="utf-8")
_INSTALLER = (
    _ROOT / "infra/yap-server-node/install-agent-admission-service.sh"
).read_text(encoding="utf-8")


class AgentAdmissionServiceTests(unittest.TestCase):
    def test_unit_uses_one_owner_private_unix_socket_and_both_exact_states(self) -> None:
        self.assertIn("User=@YAP_PROVIDER_OWNER@", _UNIT)
        self.assertIn("Group=@YAP_PROVIDER_GROUP@", _UNIT)
        self.assertIn("RuntimeDirectory=yap-agent-admission", _UNIT)
        self.assertIn("RuntimeDirectoryMode=0700", _UNIT)
        self.assertIn("UMask=0077", _UNIT)
        self.assertIn("--socket-path /run/yap-agent-admission/agent-admission.sock", _UNIT)
        self.assertIn(
            "--rapid-state-path /run/yap-provider-rapid-automation/service-state.json",
            _UNIT,
        )
        self.assertIn(
            "--complex-state-path /run/yap-provider-complex-orchestration/service-state.json",
            _UNIT,
        )
        self.assertIn("PrivateNetwork=yes", _UNIT)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", _UNIT)
        self.assertNotIn("AF_INET", _UNIT)
        self.assertNotIn("Wants=yap-provider-supervisor", _UNIT)
        self.assertNotIn("Requires=yap-provider-supervisor", _UNIT)

    def test_unit_is_bounded_and_never_substitutes_a_route(self) -> None:
        for expected in [
            "Restart=no",
            "TimeoutStopSec=5s",
            "TasksMax=128",
            "LimitNOFILE=256",
            "MemoryMax=256M",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ReadWritePaths=/run/yap-agent-admission",
        ]:
            self.assertIn(expected, _UNIT)
        self.assertNotIn("fallback", _UNIT.lower())
        self.assertNotIn("automatic", _UNIT.lower())
        self.assertNotIn("Restart=on-failure", _UNIT)

    def test_installer_requires_clean_exact_head_and_preinstalled_route_identities(self) -> None:
        self.assertIn('git -C "$repository_root" rev-parse HEAD', _INSTALLER)
        self.assertIn('status --porcelain=v1 --untracked-files=all', _INSTALLER)
        self.assertIn("YAP_ADMISSION_BROKER_BINARY", _INSTALLER)
        self.assertIn("YAP_CHECKED_HEAD", _INSTALLER)
        self.assertIn('cmp -s "$profile_source_root/rapid-automation.json"', _INSTALLER)
        self.assertIn('cmp -s "$profile_source_root/complex-orchestration.json"', _INSTALLER)
        self.assertIn('cmp -s "$candidate_lock_source"', _INSTALLER)
        self.assertIn("systemctl daemon-reload", _INSTALLER)
        self.assertNotIn("systemctl enable", _INSTALLER)
        self.assertNotIn("systemctl start", _INSTALLER)


if __name__ == "__main__":
    unittest.main()
