from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from yap_server.evaluation.agent_vllm_runtime import (
    OwnedAgentVllmRuntime,
    StartedAgentVllmRuntime,
    build_agent_vllm_launch_arguments,
)


class AgentVllmRuntimeTests(unittest.TestCase):
    def test_builds_route_specific_gpu_launch_contracts(self) -> None:
        qwen = build_agent_vllm_launch_arguments(
            _candidate("qwen3.6-35b-a3b-nvfp4", reasoning_parser="qwen3")
        )
        gemma = build_agent_vllm_launch_arguments(
            _candidate("gemma-4-31b-it-nvfp4")
        )

        self.assertNotIn("--generation-config", qwen)
        self.assertNotIn("--generation-config", gemma)
        self.assertIn("--reasoning-parser", qwen)
        self.assertNotIn("--reasoning-parser", gemma)
        self.assertEqual(qwen[qwen.index("--moe-backend") + 1], "marlin")
        self.assertEqual(qwen[qwen.index("--attention-backend") + 1], "flashinfer")
        self.assertEqual(qwen[qwen.index("--load-format") + 1], "fastsafetensors")
        self.assertIn("--speculative-config", qwen)
        self.assertEqual(
            gemma[gemma.index("--load-format") + 1], "fastsafetensors"
        )
        self.assertEqual(
            gemma[gemma.index("--chat-template") + 1],
            "/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja",
        )
        self.assertNotIn("--chat-template", qwen)
        self.assertIn("--language-model-only", qwen)
        self.assertIn("--language-model-only", gemma)

    def test_teardown_rejects_surviving_owned_cgroup_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cgroup = Path(temporary)
            (cgroup / "cgroup.procs").write_text("4242\n", encoding="ascii")
            runtime = _runtime(cgroup)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
                self.assertRaisesRegex(RuntimeError, "teardown"),
            ):
                runtime.stop(timeout_seconds=1, child_evidence_sha256=_children())

            # A failed proof must retain the verified identity so forced
            # containment can be retried after the survivor exits.
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            with patch(
                "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                return_value=True,
            ):
                evidence = runtime.contain_failed_run(timeout_seconds=1)
            self.assertTrue(all(evidence["teardown"].values()))  # type: ignore[union-attr]

    def test_teardown_records_empty_cgroup_and_removed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cgroup = Path(temporary)
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runtime = _runtime(cgroup)
            with patch(
                "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                return_value=True,
            ):
                receipt = runtime.stop(
                    timeout_seconds=1, child_evidence_sha256=_children()
                )

        self.assertEqual(
            receipt["teardown"],
            {
                "containerAbsent": True,
                "listenerAbsent": True,
                "ownedWorkersReaped": True,
                "ownedCgroupEmpty": True,
                "sameLabelOwnersAbsent": True,
            },
        )

    def test_failed_candidate_containment_retains_verified_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cgroup = Path(temporary)
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runtime = _runtime(cgroup)
            with patch(
                "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                return_value=True,
            ):
                evidence = runtime.contain_failed_run(timeout_seconds=1)

        self.assertEqual(evidence["imageId"], "sha256:" + "d" * 64)
        self.assertTrue(all(evidence["teardown"].values()))  # type: ignore[union-attr]

    def test_start_reads_back_immutable_identity_and_full_launch_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cgroup = root / "cgroup"
            cgroup.mkdir()
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runner = _AgentDockerRunner(root)
            runtime = _startable_runtime(root, runner)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._owned_cgroup_path",
                    return_value=cgroup,
                ),
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
            ):
                started = runtime.start(timeout_seconds=1)
                receipt = runtime.stop(
                    timeout_seconds=1, child_evidence_sha256=_children()
                )

        self.assertEqual(started.container_id, runner.container_id)
        launch = next(command for command in runner.commands if command[:2] == ["docker", "run"])
        self.assertIn(["--pull", "never"], [launch[index : index + 2] for index in range(len(launch) - 1)])
        self.assertIn(
            ["--env", "VLLM_ENFORCE_STRICT_TOOL_CALLING=0"],
            [launch[index : index + 2] for index in range(len(launch) - 1)],
        )
        self.assertTrue(receipt["toolCallStructuralGuidanceDisabled"])
        self.assertTrue(receipt["teardown"]["sameLabelOwnersAbsent"])  # type: ignore[index]

    def test_start_rejects_missing_structural_guidance_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cgroup = root / "cgroup"
            cgroup.mkdir()
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runner = _AgentDockerRunner(
                root, structural_guidance_disabled=False
            )
            runtime = _startable_runtime(root, runner)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._owned_cgroup_path",
                    return_value=cgroup,
                ),
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
                self.assertRaisesRegex(ValueError, "ownership"),
            ):
                runtime.start(timeout_seconds=1)
            with patch(
                "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                return_value=True,
            ):
                evidence = runtime.contain_failed_run(timeout_seconds=1)

        self.assertTrue(all(evidence["teardown"].values()))  # type: ignore[union-attr]

    def test_mismatched_inspection_identity_cannot_report_containment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = _AgentDockerRunner(root, inspected_id="b" * 64)
            runtime = _startable_runtime(root, runner)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
                self.assertRaisesRegex(ValueError, "observed identity"),
            ):
                runtime.start(timeout_seconds=1)
            with self.assertRaisesRegex(RuntimeError, "could not be observed"):
                runtime.contain_failed_run(timeout_seconds=1)

        removal = [
            command
            for command in runner.commands
            if command[:3] == ["docker", "rm", "--force"]
        ]
        self.assertEqual(removal[-1][-1], runner.container_id)

    def test_policy_failure_retains_identity_until_cleanup_is_proved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cgroup = root / "cgroup"
            cgroup.mkdir()
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runner = _AgentDockerRunner(root, user="0:0", failed_removals=1)
            runtime = _startable_runtime(root, runner)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._owned_cgroup_path",
                    return_value=cgroup,
                ),
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
                self.assertRaisesRegex(ValueError, "ownership"),
            ):
                runtime.start(timeout_seconds=1)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
                self.assertRaisesRegex(RuntimeError, "containment"),
            ):
                runtime.contain_failed_run(timeout_seconds=1)
            with patch(
                "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                return_value=True,
            ):
                evidence = runtime.contain_failed_run(timeout_seconds=1)

        self.assertTrue(all(evidence["teardown"].values()))  # type: ignore[union-attr]

    def test_name_replacement_cannot_be_removed_as_the_owned_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cgroup = root / "cgroup"
            cgroup.mkdir()
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runner = _AgentDockerRunner(root)
            runtime = _startable_runtime(root, runner)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._owned_cgroup_path",
                    return_value=cgroup,
                ),
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
            ):
                runtime.start(timeout_seconds=1)
                runner.replacement_owner = True
                with self.assertRaisesRegex(RuntimeError, "teardown"):
                    runtime.stop(
                        timeout_seconds=1, child_evidence_sha256=_children()
                    )
                runner.replacement_owner = False
                runtime.contain_failed_run(timeout_seconds=1)

        mutated = [
            command
            for command in runner.commands
            if command[:2] in (["docker", "stop"], ["docker", "rm"])
        ]
        self.assertTrue(mutated)
        self.assertTrue(all(command[-1] == runner.container_id for command in mutated))

    def test_malformed_launch_output_is_observed_then_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cgroup = root / "cgroup"
            cgroup.mkdir()
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            runner = _AgentDockerRunner(root, returned_identity="not-an-id")
            runtime = _startable_runtime(root, runner)
            with (
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._owned_cgroup_path",
                    return_value=cgroup,
                ),
                patch(
                    "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                    return_value=True,
                ),
                self.assertRaisesRegex(RuntimeError, "identity"),
            ):
                runtime.start(timeout_seconds=1)
            with patch(
                "yap_server.evaluation.agent_vllm_runtime._listener_is_absent",
                return_value=True,
            ):
                evidence = runtime.contain_failed_run(timeout_seconds=1)

        self.assertTrue(all(evidence["teardown"].values()))  # type: ignore[union-attr]


def _runtime(cgroup: Path) -> OwnedAgentVllmRuntime:
    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1 if command[:3] == ["docker", "container", "inspect"] else 0,
            "",
            "",
        )

    runtime = OwnedAgentVllmRuntime(
        checked_head="a" * 40,
        runtime={"engine": "vllm"},
        candidate={
            "candidateId": "candidate",
            "model": "model",
            "revision": "b" * 40,
            "quantization": "nvfp4",
        },
        runner=runner,
    )
    runtime._started = StartedAgentVllmRuntime(  # type: ignore[attr-defined]
        endpoint="http://127.0.0.1:30000",
        container_name="yap-agent-vllm",
        container_id="c" * 64,
        image_id="sha256:" + "d" * 64,
        model_artifact_manifest_sha256="e" * 64,
        launch_arguments_sha256="f" * 64,
        launch_arguments=("vllm", "serve"),
        cgroup_path=cgroup,
        process_id=2_147_483_647,
    )
    return runtime


def _startable_runtime(root: Path, runner) -> OwnedAgentVllmRuntime:
    model_root = root / "model"
    snapshot = model_root / "snapshots" / ("b" * 40)
    snapshot.mkdir(parents=True)
    runtime = OwnedAgentVllmRuntime(
        checked_head="a" * 40,
        runtime={"engine": "vllm"},
        candidate={
            "candidateId": "qwen3.6-35b-a3b-nvfp4",
            "model": "model/qwen",
            "revision": "b" * 40,
            "quantization": "w4afp8",
            "artifactManifestSha256": "e" * 64,
            "toolCallParser": "qwen3_xml",
            "reasoningParser": "qwen3",
            "finalResponseProtocol": "json-schema",
        },
        runner=runner,
    )
    runtime._verified_image_id = lambda: "sha256:" + "d" * 64  # type: ignore[method-assign]
    runtime._verified_model_snapshot = lambda: (  # type: ignore[method-assign]
        model_root,
        snapshot,
        "e" * 64,
    )
    runtime._launch_arguments = lambda _snapshot: [  # type: ignore[method-assign]
        "vllm",
        "serve",
    ]
    runtime._wait_ready = lambda _timeout: None  # type: ignore[method-assign]
    return runtime


class _AgentDockerRunner:
    def __init__(
        self,
        model_root: Path,
        *,
        inspected_id: str | None = None,
        returned_identity: str | None = None,
        user: str = "1000:1000",
        failed_removals: int = 0,
        structural_guidance_disabled: bool = True,
    ) -> None:
        self.container_id = "c" * 64
        self.inspected_id = inspected_id or self.container_id
        self.returned_identity = returned_identity or self.container_id
        self.model_root = model_root / "model"
        self.user = user
        self.failed_removals = failed_removals
        self.structural_guidance_disabled = structural_guidance_disabled
        self.launched = False
        self.exists = False
        self.replacement_owner = False
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append(command)
        returncode = 0
        stdout = ""
        if command[:2] == ["docker", "run"]:
            self.launched = True
            self.exists = True
            stdout = self.returned_identity + "\n"
        elif command[:3] == ["docker", "container", "inspect"]:
            if not self.exists:
                returncode = 1
            else:
                stdout = json.dumps([self._inspection()])
        elif command[:3] == ["docker", "rm", "--force"] or command[:2] == [
            "docker",
            "rm",
        ]:
            if self.failed_removals:
                self.failed_removals -= 1
                returncode = 1
            else:
                self.exists = False
        elif command[:3] == ["docker", "ps", "--all"]:
            stdout = "f" * 64 if self.replacement_owner else ""
        completed = subprocess.CompletedProcess(command, returncode, stdout, "")
        if kwargs.get("check") and returncode:
            raise subprocess.CalledProcessError(returncode, command, stdout, "")
        return completed

    def _inspection(self) -> dict[str, object]:
        return {
            "Id": self.inspected_id,
            "Name": "/yap-agent-vllm",
            "Image": "sha256:" + "d" * 64,
            "State": {"Running": True, "Pid": 2_147_483_647},
            "Config": {
                "Cmd": ["vllm", "serve"],
                "User": self.user,
                "Env": [
                    "HOME=/tmp",
                    *(
                        ["VLLM_ENFORCE_STRICT_TOOL_CALLING=0"]
                        if self.structural_guidance_disabled
                        else []
                    ),
                ],
                "Labels": {
                    "io.yap.owner": "private-inference",
                    "io.yap.revision": "a" * 40,
                },
            },
            "HostConfig": {
                "NetworkMode": "host",
                "IpcMode": "host",
                "Ulimits": [
                    {"Name": "memlock", "Soft": -1, "Hard": -1},
                    {
                        "Name": "stack",
                        "Soft": 67_108_864,
                        "Hard": 67_108_864,
                    },
                ],
                "DeviceRequests": [{"Count": -1, "Capabilities": [["gpu"]]}],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(self.model_root),
                    "Destination": "/model-cache",
                    "RW": False,
                }
            ],
        }


def _children() -> dict[str, str]:
    return {
        name: "1" * 64
        for name in (
            "fixtures",
            "pressure",
            "cancellation",
            "resources",
            "lifecycle",
        )
    }


def _candidate(
    candidate_id: str, *, reasoning_parser: str | None = None
) -> dict[str, object]:
    candidate: dict[str, object] = {
        "candidateId": candidate_id,
        "model": f"model/{candidate_id}",
        "revision": "b" * 40,
        "toolCallParser": "qwen3_xml" if candidate_id.startswith("qwen") else "gemma4",
        "finalResponseProtocol": (
            "json-schema" if candidate_id.startswith("qwen") else "forced-answer-tool"
        ),
    }
    if candidate_id.startswith("gemma"):
        candidate["chatTemplate"] = (
            "/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja"
        )
    if reasoning_parser is not None:
        candidate["reasoningParser"] = reasoning_parser
    return candidate


if __name__ == "__main__":
    unittest.main()
