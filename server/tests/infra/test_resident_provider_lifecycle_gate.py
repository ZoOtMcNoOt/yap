from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GATE = (
    REPOSITORY_ROOT
    / "infra"
    / "yap-server-node"
    / "resident-provider-lifecycle-gate.sh"
)
PLAN = REPOSITORY_ROOT / "server" / "asr-evaluation-plan.json"


class ResidentProviderLifecycleGateContractTests(unittest.TestCase):
    def test_runs_both_checked_providers_sequentially_and_finalizes_after_teardown(
        self,
    ) -> None:
        script = GATE.read_text(encoding="utf-8")
        plan = PLAN.read_text(encoding="utf-8")

        for required in (
            "YAP_CHECKED_HEAD:?",
            "YAP_EVAL_CACHE:?",
            "YAP_PROVIDER_DURATION_SUITE:?",
            "YAP_PROVIDER_DURATION_SUITE_SHA256:?",
            "YAP_COHERE_MODEL_DIR:?",
            "YAP_NEMOTRON_MODEL_DIR:?",
            "YAP_COHERE_VLLM_API_KEY:?",
            "YAP_NEMOTRON_NEMO_API_KEY:?",
            "status --porcelain=v1 --untracked-files=normal",
            "runtime/cohere-vllm/Dockerfile",
            "runtime/nemotron-nemo/Dockerfile",
            "cohere-vllm-server.sh",
            "nemotron-nemo-server.sh",
            "resident_provider_readiness",
            "provider_runtime_qualification",
            "provider_cancellation_qualification",
            "provider_capacity_qualification",
            "provider_language_parity_qualification",
            "resident_provider_duration_qualification",
            "resident_provider_resource_sampler",
            "provider_resource_observations",
            "resident_provider_lifecycle_evidence",
            "vllm-short-tail",
            "vllm-cancelled-sibling",
            "vllm-slot-capacity",
            "vllm-pcm-capacity",
            "nemo-finalized-short-tail",
            "nemo-finalized-fixed-auto-parity",
            "nemo-finalized-long-windows",
            "nemo-finalized-cancelled-sibling",
            "nemo-finalized-active-capacity",
            "server-finalized-utterance",
            "batch-file",
            '"--repeat-count" "$repeat_count"',
            '"--completed-request-count" "1600"',
            '"--concurrency" "8"',
            "workload-start",
            "workload-end",
            "workload-window.json",
            "capture_host_boundary",
            "verify_private_container_network",
            "runtime-processes.txt",
            "[d]ocker logs --follow (yap-cohere-vllm|yap-nemotron-nemo)",
            "Resident providers require distinct loopback ports",
            'docker port "$container"',
            '("1.1.1.1", 443)',
            'launcher_status="$?"',
            "Resident provider launcher reported unclean teardown",
            "--verify-only",
        ):
            self.assertIn(required, script)

        for promotion_only in ("vllm-long-waves", "vllm-mixed-eight"):
            self.assertNotIn(promotion_only, script)
            self.assertIn(f'"id": "{promotion_only}"', plan)

        self.assertLess(
            script.rindex("\nrun_vllm_qualification\n"),
            script.rindex('stop_provider "yap-cohere-vllm"'),
        )
        self.assertLess(
            script.rindex('stop_provider "yap-cohere-vllm"'),
            script.rindex("\nrun_nemo_qualification\n"),
        )
        self.assertLess(
            script.index('stop_provider "yap-nemotron-nemo"'),
            script.index('capture_host_boundary "$gate_root/after"'),
        )
        self.assertLess(
            script.index('capture_host_boundary "$gate_root/after"'),
            script.index("resident_provider_lifecycle_evidence"),
        )
        self.assertIn(
            '"$catalog_language" "$provider_language" 8 8',
            script,
        )

    def test_uses_a_temporary_internal_network_and_never_mutates_host_policy(self) -> None:
        script = GATE.read_text(encoding="utf-8")

        self.assertIn("docker network create", script)
        self.assertIn("--internal", script)
        self.assertIn("io.yap.owner=private-inference", script)
        self.assertIn('io.yap.revision=$YAP_CHECKED_HEAD', script)
        self.assertIn("docker network rm", script)
        self.assertIn("networks.txt", script)
        self.assertNotIn("--network host", script)
        self.assertNotIn("nohup", script)
        for mutation in (
            "ufw allow",
            "ufw delete",
            "ufw enable",
            "systemctl enable",
            "systemctl start",
            "systemctl restart",
        ):
            self.assertNotIn(mutation, script.lower())


if __name__ == "__main__":
    unittest.main()
