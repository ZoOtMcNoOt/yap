from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_acceptance import (
    _candidate_lock,
    _fixtures,
    _runtime_tracks,
    load_agent_model_acceptance,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelAcceptanceTests(unittest.TestCase):
    def test_freezes_route_specific_arm64_runtimes(self) -> None:
        candidate_lock = json.loads(
            (
                REPOSITORY_ROOT
                / "server"
                / "agent-reasoning-candidates.lock.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(candidate_lock["schemaVersion"], 3)
        self.assertEqual(
            candidate_lock["runtimes"],
            {
                "qwen-vllm-26.07-xgrammar-0.2.1": {
                    "engine": "vllm",
                    "image": "yap-agent-vllm:qwen-26.07-xgrammar-0.2.1",
                    "observedImageId": "sha256:cbbe822b63b6e3d7fd4d18ac727108d84b06974f6e1632ea4ea85df2b18d27cb",
                    "platform": "linux/arm64",
                    "python": "3.12",
                    "vllm": "0.24.0+092c4842.nv26.7.59534043",
                    "xgrammar": "0.2.1",
                    "provenance": {
                        "kind": "xgrammar-wheel-overlay",
                        "baseImage": "nvcr.io/nvidia/vllm:26.07-py3",
                        "baseManifestDigest": "sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2",
                        "dockerfile": "runtime/agent-vllm/Dockerfile",
                        "dockerfileSha256": "943433baeefef0e167b5a8d27b744b305ba2f32f47841d43f53f2d27625af264",
                        "buildScript": "runtime/agent-vllm/build-qwen-vllm-runtime.sh",
                        "buildScriptSha256": "6a7feff232485d43f4b2ec550ef050cd7ec1595d4d4f056d623bef4da8b1b6cb",
                        "notice": "runtime/agent-vllm/THIRD_PARTY_NOTICES.md",
                        "noticeSha256": "8c13a052aa3a1f5f77918617490bfdb37509a5252d684283a724ec965d0b25c8",
                        "wheel": "xgrammar-0.2.1-cp312-cp312-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl",
                        "wheelSha256": "9e8dd9853958a263b4015ce79133a0ff4eaa9d22ef781fb2350c7dfc40c2c012",
                        "sourceRevision": "5b4e9ce9e72524037ae24ecd831b9b6604d2eb48",
                        "license": "Apache-2.0",
                    },
                },
                "gemma-vllm-26.06": {
                    "engine": "vllm",
                    "image": "nvcr.io/nvidia/vllm:26.06-py3",
                    "manifestDigest": "sha256:bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e",
                    "observedImageId": "sha256:59f44d868668552a6d63a5fa3425fa8d63591bf0b9cc1eba1dc0624371068af7",
                    "platform": "linux/arm64",
                    "python": "3.12",
                    "vllm": "0.22.1+7b9cb5b7.dev",
                    "xgrammar": "0.2.0",
                    "provenance": {"kind": "upstream-manifest"},
                },
            },
        )
        self.assertEqual(
            {
                candidate["candidateId"]: candidate["runtimeId"]
                for candidate in candidate_lock["candidates"]
            },
            {
                "qwen3.6-35b-a3b-nvfp4": "qwen-vllm-26.07-xgrammar-0.2.1",
                "gemma-4-31b-it-nvfp4": "gemma-vllm-26.06",
            },
        )

    def test_route_runtime_recipe_is_hash_bound(self) -> None:
        candidate_lock = json.loads(
            (
                REPOSITORY_ROOT
                / "server"
                / "agent-reasoning-candidates.lock.json"
            ).read_text(encoding="utf-8")
        )
        runtime = candidate_lock["runtimes"][
            "qwen-vllm-26.07-xgrammar-0.2.1"
        ]
        provenance = runtime["provenance"]
        dockerfile = REPOSITORY_ROOT / "server" / provenance["dockerfile"]
        build_script = REPOSITORY_ROOT / "server" / provenance["buildScript"]
        notice = REPOSITORY_ROOT / "server" / provenance["notice"]

        import hashlib

        self.assertEqual(
            hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
            provenance["dockerfileSha256"],
        )
        self.assertEqual(
            hashlib.sha256(build_script.read_bytes()).hexdigest(),
            provenance["buildScriptSha256"],
        )
        self.assertEqual(
            hashlib.sha256(notice.read_bytes()).hexdigest(),
            provenance["noticeSha256"],
        )
        self.assertIn(
            "sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2",
            dockerfile.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "9e8dd9853958a263b4015ce79133a0ff4eaa9d22ef781fb2350c7dfc40c2c012",
            dockerfile.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "--output type=docker,rewrite-timestamp=true",
            build_script.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "SOURCE_DATE_EPOCH=0",
            build_script.read_text(encoding="utf-8"),
        )

    def test_rejects_candidate_without_exact_route_runtime(self) -> None:
        candidate_lock = json.loads(
            (
                REPOSITORY_ROOT
                / "server"
                / "agent-reasoning-candidates.lock.json"
            ).read_text(encoding="utf-8")
        )
        candidate_lock["candidates"][0]["runtimeId"] = "gemma-vllm-26.06"
        candidate_lock["candidates"][1]["runtimeId"] = "gemma-vllm-26.06"

        with self.assertRaises(ValueError):
            _candidate_lock(candidate_lock)

    def test_legacy_single_runtime_lock_is_rejected(self) -> None:
        candidate_lock = json.loads(
            (
                REPOSITORY_ROOT
                / "server"
                / "agent-reasoning-candidates.lock.json"
            ).read_text(encoding="utf-8")
        )
        candidate_lock["schemaVersion"] = 2
        candidate_lock["runtime"] = {
                "engine": "vllm",
                "image": "nvcr.io/nvidia/vllm:26.07-py3",
                "digest": "sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2",
                "platform": "linux/arm64",
                "python": "3.12",
                "vllm": "0.24.0+092c4842.nv26.7.59534043",
        }
        candidate_lock.pop("runtimes", None)
        with self.assertRaises(ValueError):
            _candidate_lock(candidate_lock)

    def test_loads_frozen_candidate_runtime_and_workload_identity(self) -> None:
        acceptance = json.loads(
            (
                REPOSITORY_ROOT / "server" / "agent-model-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(acceptance["schemaVersion"], 5)
        plan = load_agent_model_acceptance(REPOSITORY_ROOT)

        self.assertEqual(
            plan.candidate_ids,
            (
                "qwen3.6-35b-a3b-nvfp4",
                "gemma-4-31b-it-nvfp4",
            ),
        )
        self.assertEqual(
            plan.required_routes,
            {
                "complex-orchestration": "gemma-4-31b-it-nvfp4",
                "rapid-automation": "qwen3.6-35b-a3b-nvfp4",
            },
        )
        self.assertEqual(len(plan.case_ids), 13)
        self.assertEqual(
            plan.permitted_outcomes,
            ("required-workload-routes-qualified", "deterministic-no-model"),
        )
        self.assertEqual(plan.runtime_tracks["requestTimeoutSeconds"], 30)
        self.assertEqual(plan.runtime_tracks["maximumFinalResponseAttempts"], 2)
        self.assertEqual(
            plan.route_evidence["complex-orchestration"]["requestTimeoutSeconds"],
            60,
        )
        self.assertEqual(
            plan.route_evidence["rapid-automation"]["maximumOutputTokens"], 256
        )
        self.assertEqual(
            plan.route_evidence["rapid-automation"],
            {
                "candidateId": "qwen3.6-35b-a3b-nvfp4",
                "maximumOutputTokens": 256,
                "maximumProposalOutputTokens": 160,
                "maximumCommonFixtureP95LatencyMilliseconds": 3_000,
                "maximumProposalFixtureP95LatencyMilliseconds": 10_000,
                "proposalFixtureRepetitionsPerCase": 8,
                "proposalFixtureCaseIds": [
                    "cited-summary-proposal",
                    "terminology-preservation-en",
                    "terminology-preservation-es",
                ],
                "maximumWarmP95LatencyMilliseconds": 750,
                "maximumC8P95LatencyMilliseconds": 1_500,
            },
        )
        self.assertEqual(
            plan.route_evidence["complex-orchestration"]["maximumOutputTokens"],
            512,
        )

        fixtures = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        visible_case = next(case for case in fixtures["cases"] if case["visibleContext"])
        visible_case["visibleContext"][0]["charEnd"] -= 1
        with self.assertRaisesRegex(ValueError, "visible context span"):
            _fixtures(fixtures)
        visible_case["visibleContext"][0]["charEnd"] += 1
        digest = visible_case["visibleContext"][0]["contentSha256"]
        visible_case["visibleContext"][0]["contentSha256"] = int("1" * 64)
        with self.assertRaisesRegex(ValueError, "visible context identity"):
            _fixtures(fixtures)
        visible_case["visibleContext"][0]["contentSha256"] = digest

        empty_case = next(
            case for case in fixtures["cases"] if case["visibleContext"] == []
        )
        empty_case.pop("expectedAnswer")
        with self.assertRaisesRegex(ValueError, "empty agent evidence"):
            _fixtures(fixtures)

        empty_case["expectedAnswer"] = "Evidence is unavailable."
        empty_case["maximumOutputTokens"] = True
        with self.assertRaisesRegex(ValueError, "case output bound"):
            _fixtures(fixtures)

        empty_case["maximumOutputTokens"] = 128
        proposal_case = next(
            case
            for case in fixtures["cases"]
            if case["caseId"] == "cited-summary-proposal"
        )
        source_citations = proposal_case["expectedArguments"].pop("source_citations")
        with self.assertRaisesRegex(ValueError, "expected arguments"):
            _fixtures(fixtures)
        proposal_case["expectedArguments"]["source_citations"] = source_citations
        proposal_case["expectedArguments"]["proposal_type"] = "relationship"
        with self.assertRaisesRegex(ValueError, "cited proposal"):
            _fixtures(fixtures)

    def test_freezes_two_final_response_attempts(self) -> None:
        tracks = load_agent_model_acceptance(REPOSITORY_ROOT).runtime_tracks

        for invalid in (True, 1, 2.0, 3):
            with self.subTest(invalid=invalid):
                changed = {**tracks, "maximumFinalResponseAttempts": invalid}
                with self.assertRaisesRegex(ValueError, "final response attempts"):
                    _runtime_tracks(changed)


if __name__ == "__main__":
    unittest.main()
