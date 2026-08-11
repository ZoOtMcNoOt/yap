from __future__ import annotations

from dataclasses import replace
import json
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

from yap_server.evaluation.agent_service_lifecycle_gate import (
    run_agent_service_lifecycle_gate,
)
from yap_server.evaluation.agent_service_lifecycle_observation import (
    AgentServiceLifecycleResult,
)


CHECKED_HEAD = "a" * 40


class _FakeRuntime:
    calls: list[str] = []
    fail_profile: str | None = None
    result_mutation: str | None = None
    mutate_supervisor_profile: str | None = None

    def __init__(self, **arguments: object) -> None:
        self.repository_root = Path(arguments["repository_root"])

    def run(
        self,
        *,
        profile_id: str,
        model_snapshot: Path,
        timeout_seconds: int = 900,
    ) -> AgentServiceLifecycleResult:
        del model_snapshot, timeout_seconds
        self.calls.append(profile_id)
        if profile_id == self.fail_profile:
            raise RuntimeError("synthetic route failure")
        if profile_id == self.mutate_supervisor_profile:
            supervisor = (
                self.repository_root
                / "server"
                / "orchestrator"
                / "target"
                / "release"
                / "yap-provider-supervisor"
            )
            supervisor.write_bytes(b"changed executable")
        profile_path = (
            self.repository_root
            / "server"
            / "agent-service-profiles"
            / f"{profile_id}.json"
        )
        candidate_lock = (
            self.repository_root
            / "server"
            / "agent-reasoning-candidates.lock.json"
        )
        result = _result(
            profile_id,
            profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
            candidate_lock_sha256=hashlib.sha256(
                candidate_lock.read_bytes()
            ).hexdigest(),
        )
        if self.result_mutation == profile_id:
            result = replace(result, listener_absent=False)
        return result


def _result(
    profile_id: str,
    *,
    profile_sha256: str,
    candidate_lock_sha256: str,
) -> AgentServiceLifecycleResult:
    digit = "b" if profile_id == "rapid-automation" else "c"
    return AgentServiceLifecycleResult(
        profile_id=profile_id,
        profile_sha256=profile_sha256,
        candidate_lock_sha256=candidate_lock_sha256,
        image_id="sha256:" + digit * 64,
        initial_readiness_observed=True,
        restart_readiness_observed=True,
        new_container_observed=True,
        new_process_observed=True,
        stopped_state_observed=True,
        container_absent=True,
        listener_absent=True,
        owned_process_absent=True,
        network_absent=True,
        same_label_owners_absent=True,
    )


def _command_runner(
    arguments: list[str],
    **_options: object,
) -> subprocess.CompletedProcess[str]:
    if len(arguments) >= 4 and arguments[:2] == ["git", "-C"] and arguments[3] == "rev-parse":
        if arguments[-1] == "--show-toplevel":
            stdout = f"{arguments[2]}\n"
        else:
            stdout = f"{CHECKED_HEAD}\n"
    elif len(arguments) >= 4 and arguments[:2] == ["git", "-C"] and arguments[3] == "status":
        stdout = ""
    elif arguments == ["uname", "-m"]:
        stdout = "aarch64\n"
    elif arguments[:3] == ["docker", "info", "--format"]:
        stdout = "linux|arm64\n"
    elif Path(arguments[0]).stem in {"cargo", "cargo.exe"} and arguments[1] == "build":
        stdout = ""
    else:
        raise AssertionError(f"unexpected command: {arguments}")
    return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")


class AgentServiceLifecycleGateTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeRuntime.calls = []
        _FakeRuntime.fail_profile = None
        _FakeRuntime.result_mutation = None
        _FakeRuntime.mutate_supervisor_profile = None

    def test_publishes_only_after_both_routes_pass_and_teardown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs = _inputs(Path(temporary))

            evidence = run_agent_service_lifecycle_gate(
                **inputs,
                runtime_factory=_FakeRuntime,
                command_runner=_command_runner,
            )

            receipt = inputs["evidence_root"] / "receipt.json"
            self.assertEqual(
                _FakeRuntime.calls,
                ["rapid-automation", "complex-orchestration"],
            )
            self.assertTrue(evidence["passed"])
            self.assertFalse(evidence["simultaneousResidencyClaim"])
            self.assertFalse(evidence["capacityClaim"])
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), evidence)
            self.assertNotIn(str(Path(temporary)), json.dumps(evidence))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

    def test_route_failure_or_incomplete_teardown_never_publishes(self) -> None:
        for mutation in ("route-failure", "teardown-failure"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                inputs = _inputs(Path(temporary))
                if mutation == "route-failure":
                    _FakeRuntime.fail_profile = "complex-orchestration"
                else:
                    _FakeRuntime.result_mutation = "complex-orchestration"

                with self.assertRaises((RuntimeError, ValueError)):
                    run_agent_service_lifecycle_gate(
                        **inputs,
                        runtime_factory=_FakeRuntime,
                        command_runner=_command_runner,
                    )

                self.assertFalse((inputs["evidence_root"] / "receipt.json").exists())

    def test_evidence_root_must_be_empty_and_create_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs = _inputs(Path(temporary))
            (inputs["evidence_root"] / "unexpected").write_text(
                "occupied",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "must be empty"):
                run_agent_service_lifecycle_gate(
                    **inputs,
                    runtime_factory=_FakeRuntime,
                    command_runner=_command_runner,
                )

            self.assertEqual(_FakeRuntime.calls, [])

    def test_supervisor_binary_must_remain_exact_through_both_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs = _inputs(Path(temporary))
            _FakeRuntime.mutate_supervisor_profile = "complex-orchestration"

            with self.assertRaisesRegex(RuntimeError, "changed during the gate"):
                run_agent_service_lifecycle_gate(
                    **inputs,
                    runtime_factory=_FakeRuntime,
                    command_runner=_command_runner,
                )

            self.assertFalse((inputs["evidence_root"] / "receipt.json").exists())


def _inputs(root: Path) -> dict[str, object]:
    repository = root / "repository"
    repository.mkdir()
    profile_root = repository / "server" / "agent-service-profiles"
    profile_root.mkdir(parents=True)
    for profile_id in ("rapid-automation", "complex-orchestration"):
        (profile_root / f"{profile_id}.json").write_text(
            f'{{"profileId":"{profile_id}"}}\n',
            encoding="utf-8",
        )
    (repository / "server" / "agent-reasoning-candidates.lock.json").write_text(
        '{"schemaVersion":3}\n',
        encoding="utf-8",
    )
    supervisor = (
        repository
        / "server"
        / "orchestrator"
        / "target"
        / "release"
        / "yap-provider-supervisor"
    )
    supervisor.parent.mkdir(parents=True)
    supervisor.write_bytes(b"synthetic executable")
    rapid_snapshot = root / "rapid-snapshot"
    complex_snapshot = root / "complex-snapshot"
    rapid_snapshot.mkdir()
    complex_snapshot.mkdir()
    evidence_root = root / "evidence"
    evidence_root.mkdir()
    if os.name == "posix":
        supervisor.chmod(0o700)
        evidence_root.chmod(0o700)
    return {
        "repository_root": repository.resolve(),
        "checked_head": CHECKED_HEAD,
        "rapid_model_snapshot": rapid_snapshot.resolve(),
        "complex_model_snapshot": complex_snapshot.resolve(),
        "evidence_root": evidence_root.resolve(),
    }


if __name__ == "__main__":
    unittest.main()
