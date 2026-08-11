from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch, sentinel

from yap_server.evaluation.agent_service_lifecycle_runtime import (
    AgentServiceLifecycleRuntime,
)
from yap_server.pools.agent_vllm_service_profile import (
    load_agent_vllm_service_profile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = (
    REPOSITORY_ROOT
    / "server"
    / "agent-service-profiles"
    / "rapid-automation.json"
)
CANDIDATE_LOCK = REPOSITORY_ROOT / "server" / "agent-reasoning-candidates.lock.json"


class AgentServiceLifecycleRuntimeTests(unittest.TestCase):
    def test_network_mutation_is_inside_failure_containment_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            runtime = AgentServiceLifecycleRuntime(
                repository_root=REPOSITORY_ROOT,
                checked_head="a" * 40,
                supervisor_binary=private_root / "supervisor",
                private_root=private_root,
            )
            with (
                patch(
                    "yap_server.evaluation.agent_service_lifecycle_runtime."
                    "verify_agent_model_snapshot"
                ),
                patch.object(
                    runtime,
                    "_stage_launcher",
                    return_value=private_root / "launcher",
                ),
                patch.object(runtime, "_create_network") as create_network,
                patch.object(
                    runtime,
                    "_start_supervisor",
                    side_effect=RuntimeError("synthetic start failure"),
                ),
                patch.object(runtime, "contain_failed_run") as contain_failed_run,
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic start failure"):
                    runtime.run(
                        profile_id="rapid-automation",
                        model_snapshot=private_root / "snapshot",
                        timeout_seconds=60,
                    )

            create_network.assert_called_once()
            contain_failed_run.assert_called_once_with()

    def test_teardown_checks_every_observed_process_identity(self) -> None:
        profile = load_agent_vllm_service_profile(
            PROFILE_PATH,
            CANDIDATE_LOCK,
            expected_profile_sha256=hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest(),
        )
        runtime = AgentServiceLifecycleRuntime(
            repository_root=REPOSITORY_ROOT,
            checked_head="a" * 40,
            supervisor_binary=Path("supervisor"),
            private_root=Path("private"),
        )
        runtime._observed_process_ids.update((111, 222))
        with (
            patch.object(runtime, "_owned_container_ids", return_value=[]),
            patch.object(runtime, "_same_label_owner_ids", return_value=[]),
            patch(
                "yap_server.evaluation.agent_service_lifecycle_runtime.listener_absent",
                return_value=True,
            ),
            patch(
                "yap_server.evaluation.agent_service_lifecycle_runtime."
                "recorded_proxy_absent",
                return_value=True,
            ),
            patch(
                "yap_server.evaluation.agent_service_lifecycle_runtime."
                "owner_token_processes",
                return_value=(),
            ),
            patch(
                "yap_server.evaluation.agent_service_lifecycle_runtime.process_absent",
                side_effect=(False, True),
            ) as process_absent,
        ):
            teardown = runtime._teardown_state(profile, "network", "b" * 64)

        self.assertEqual(process_absent.call_args_list, [call(111), call(222)])
        self.assertFalse(teardown["ownedProcessAbsent"])

    def test_supervisor_receives_only_bounded_runtime_environment(self) -> None:
        profile = load_agent_vllm_service_profile(
            PROFILE_PATH,
            CANDIDATE_LOCK,
            expected_profile_sha256=hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = AgentServiceLifecycleRuntime(
                repository_root=REPOSITORY_ROOT,
                checked_head="a" * 40,
                supervisor_binary=root / "supervisor",
                private_root=root,
            )
            with patch(
                "yap_server.evaluation.agent_service_lifecycle_runtime.subprocess.Popen",
                return_value=sentinel.process,
            ) as popen:
                observed = runtime._start_supervisor(
                    profile=profile,
                    profile_path=PROFILE_PATH,
                    profile_sha256=profile.profile_sha256,
                    candidate_lock=CANDIDATE_LOCK,
                    model_snapshot=root / "snapshot",
                    launcher=root / "launcher",
                    network_name="private-network",
                    owner_token="b" * 64,
                    proxy_group_file=root / "proxy-group",
                    state_path=root / "service-state.json",
                )
                environment = popen.call_args.kwargs["env"]
                runtime._clear_runtime()

        self.assertIs(observed, sentinel.process)
        self.assertEqual(
            set(environment),
            {
                "PATH",
                "YAP_CHECKED_HEAD",
                "YAP_AGENT_MODEL_SNAPSHOT",
                "YAP_PRIVATE_INFERENCE_NETWORK",
                "YAP_RUNTIME_OWNER_TOKEN",
                "YAP_PROXY_PROCESS_GROUP_FILE",
            },
        )
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)


if __name__ == "__main__":
    unittest.main()
