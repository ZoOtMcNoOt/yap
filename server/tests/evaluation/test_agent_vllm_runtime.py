from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from yap_server.evaluation.agent_vllm_runtime import (
    OwnedAgentVllmRuntime,
    StartedAgentVllmRuntime,
)


class AgentVllmRuntimeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
