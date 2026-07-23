from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from yap_server.evaluation.provider_runtime_observations import (
    canonical_evidence_sha256,
)
from yap_server.evaluation.resident_provider_lifecycle_evidence import (
    finalize_resident_provider_lifecycle_evidence,
)


CHECKED_HEAD = "a" * 40
SUITE_SHA256 = "b" * 64
PLAN_SHA256 = "c" * 64
FINALIZED_DURATION_SAMPLES = [
    4_000,
    8_000,
    12_000,
    16_000,
    17_920,
    32_000,
    80_000,
    160_000,
    480_000,
]
BATCH_DURATION_SAMPLES = [
    480_000,
    1_920_000,
    4_800_000,
    14_400_000,
    28_800_000,
    57_600_000,
    115_200_000,
    230_400_000,
]
STANDARD_LOADS = {
    "vllm-short-tail": ([1, 2, 4], 1, 600, [480_000]),
    "nemo-finalized-short-tail": ([1, 2, 4], 1, 600, [480_000]),
    "nemo-finalized-long-windows": ([2], 1, 4, [480_000, 14_400_000]),
}
ARTIFACTS = (
    ("vllm", "readiness.json", "readiness", "vllm-cohere-batch", "readiness"),
    ("vllm", "short-tail.json", "load", "vllm-cohere-batch", "vllm-short-tail"),
    ("vllm", "cancellation.json", "load", "vllm-cohere-batch", "vllm-cancelled-sibling"),
    ("vllm", "slot-capacity.json", "load", "vllm-cohere-batch", "vllm-slot-capacity"),
    ("vllm", "pcm-capacity.json", "load", "vllm-cohere-batch", "vllm-pcm-capacity"),
    ("vllm", "duration-batch.json", "duration", "vllm-cohere-batch", "batch-file"),
    ("vllm", "resource-load.json", "resource-load", "vllm-cohere-batch", "vllm-short-tail"),
    ("vllm", "resources.json", "resource", "vllm-cohere-batch", "vllm-short-tail"),
    ("nemo", "readiness.json", "readiness", "nemo-nemotron-finalized", "readiness"),
    ("nemo", "short-tail.json", "load", "nemo-nemotron-finalized", "nemo-finalized-short-tail"),
    ("nemo", "long-windows.json", "load", "nemo-nemotron-finalized", "nemo-finalized-long-windows"),
    ("nemo", "language-contract.json", "load", "nemo-nemotron-finalized", "nemo-finalized-fixed-auto-contract"),
    ("nemo", "cancellation.json", "load", "nemo-nemotron-finalized", "nemo-finalized-cancelled-sibling"),
    ("nemo", "active-capacity.json", "load", "nemo-nemotron-finalized", "nemo-finalized-active-capacity"),
    ("nemo", "duration-finalized.json", "duration", "nemo-nemotron-finalized", "server-finalized-utterance"),
    ("nemo", "duration-batch.json", "duration", "nemo-nemotron-finalized", "batch-file"),
    ("nemo", "resource-load.json", "resource-load", "nemo-nemotron-finalized", "nemo-finalized-short-tail"),
    ("nemo", "resources.json", "resource", "nemo-nemotron-finalized", "nemo-finalized-short-tail"),
)
SNAPSHOTS = {
    "listeners.txt": b"tcp LISTEN 0 128 127.0.0.1:22\n",
    "firewall.txt": b"tool=ufw-config-metadata\nStatus: active\n",
    "services.txt": b"",
    "containers.txt": b"",
    "runtime-processes.txt": b"",
    "networks.txt": b"",
}


def _write_snapshots(root: Path, values: dict[str, bytes] = SNAPSHOTS) -> None:
    root.mkdir()
    for name, value in values.items():
        (root / name).write_bytes(value)


def _artifact(kind: str, system_id: str, identity: str) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "systemId": system_id,
        "passed": True,
        "candidate": {
            "checkedHead": CHECKED_HEAD,
            "repositoryState": "clean",
            "inputs": {"server/asr-evaluation-plan.json": PLAN_SHA256},
        },
    }
    if kind == "readiness":
        value.update(
            {
                "readinessBoundary": "probe-start-to-exact-model-ready",
                "attemptCount": 2,
                "readyAfterMs": 100,
            }
        )
    elif kind == "duration":
        selected_durations = (
            FINALIZED_DURATION_SAMPLES
            if identity == "server-finalized-utterance"
            else BATCH_DURATION_SAMPLES
        )
        value.update(
            {
                "durationLadderId": identity,
                "qualificationScope": "duration-transport-and-lifecycle",
                "representativeAccuracyClaim": False,
                "selectedDurationSamples": selected_durations,
                "exactMaximumIncluded": identity == "batch-file",
                "completedRequestCount": len(selected_durations),
            }
        )
    else:
        value["loadCaseId"] = identity
        if kind == "resource-load":
            value.update(
                {
                    "qualificationScope": "resource-lifecycle",
                    "selectedConcurrencies": [8],
                    "repeatCount": 8,
                    "completedRequestCount": 1600,
                }
            )
        elif identity in STANDARD_LOADS:
            concurrencies, repeats, completions, _durations = STANDARD_LOADS[identity]
            value.update(
                {
                    "qualificationScope": "request-lifecycle",
                    "selectedConcurrencies": concurrencies,
                    "repeatCount": repeats,
                    "completedRequestCount": completions,
                }
            )
        elif identity == "nemo-finalized-fixed-auto-contract":
            value["qualificationScope"] = "request-lifecycle"
        if kind == "resource":
            value.update(
                {
                    "hardwareProfile": "dgx-spark-gb10",
                    "concurrency": 8,
                    "completedRequestCount": 1600,
                }
            )
    if kind not in {"readiness", "resource"}:
        selected_suite_durations = [480_000]
        if kind == "duration":
            selected_suite_durations = value["selectedDurationSamples"]  # type: ignore[assignment]
        elif kind != "resource-load" and identity in STANDARD_LOADS:
            selected_suite_durations = STANDARD_LOADS[identity][3]
        value["durationSuite"] = {
            "sha256": SUITE_SHA256,
            "planSha256": PLAN_SHA256,
            "selectedDurationSamples": selected_suite_durations,
        }
    value["evidenceSha256"] = canonical_evidence_sha256(value)
    return value


def _write_artifacts(root: Path) -> None:
    for provider, name, kind, system_id, identity in ARTIFACTS:
        directory = root / provider
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(
            json.dumps(_artifact(kind, system_id, identity)),
            encoding="utf-8",
        )


class ResidentProviderLifecycleEvidenceTests(unittest.TestCase):
    def test_publishes_only_after_every_checked_cell_and_host_teardown_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = root / "before"
            after = root / "after"
            evidence_root = root / "provider-evidence"
            _write_snapshots(before)
            _write_snapshots(after)
            _write_artifacts(evidence_root)
            output = root / "lifecycle-evidence.json"

            evidence = finalize_resident_provider_lifecycle_evidence(
                before_dir=before,
                after_dir=after,
                provider_evidence_root=evidence_root,
                checked_head=CHECKED_HEAD,
                output_path=output,
            )

            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["checkedHead"], CHECKED_HEAD)
            self.assertEqual(evidence["hardwareProfile"], "dgx-spark-gb10")
            self.assertEqual(
                evidence["hostBoundary"]["remainingProviderRuntimeProcesses"],
                0,
            )
            self.assertEqual(len(evidence["childEvidence"]), len(ARTIFACTS))
            self.assertEqual(
                evidence["durationSuite"],
                {"sha256": SUITE_SHA256, "planSha256": PLAN_SHA256},
            )
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                evidence,
            )
            self.assertNotIn(str(root), json.dumps(evidence))

    def test_rejects_failed_or_mismatched_child_evidence(self) -> None:
        for mutation in (
            "failed",
            "wrong-head",
            "wrong-suite",
            "partial-load",
            "wrong-resource-scope",
            "wrong-request-scope",
            "partial-long-window-suite",
            "missing-maximum",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                before = root / "before"
                after = root / "after"
                evidence_root = root / "provider-evidence"
                _write_snapshots(before)
                _write_snapshots(after)
                _write_artifacts(evidence_root)
                target = evidence_root / "vllm" / "short-tail.json"
                value = json.loads(target.read_text(encoding="utf-8"))
                if mutation == "failed":
                    value["passed"] = False
                elif mutation == "wrong-head":
                    value["candidate"]["checkedHead"] = "d" * 40
                elif mutation == "wrong-suite":
                    value["durationSuite"]["sha256"] = "e" * 64
                elif mutation == "partial-load":
                    value["selectedConcurrencies"] = [1]
                    value["completedRequestCount"] = 200
                elif mutation == "wrong-resource-scope":
                    target = evidence_root / "vllm" / "resource-load.json"
                    value = json.loads(target.read_text(encoding="utf-8"))
                    value["qualificationScope"] = "provider-behavior"
                elif mutation == "wrong-request-scope":
                    value["qualificationScope"] = "provider-behavior"
                elif mutation == "partial-long-window-suite":
                    target = evidence_root / "nemo" / "long-windows.json"
                    value = json.loads(target.read_text(encoding="utf-8"))
                    value["durationSuite"]["selectedDurationSamples"] = [
                        14_400_000
                    ]
                else:
                    target = evidence_root / "vllm" / "duration-batch.json"
                    value = json.loads(target.read_text(encoding="utf-8"))
                    value["selectedDurationSamples"] = BATCH_DURATION_SAMPLES[:-1]
                    value["exactMaximumIncluded"] = False
                    value["completedRequestCount"] = len(BATCH_DURATION_SAMPLES) - 1
                    value["durationSuite"]["selectedDurationSamples"] = (
                        BATCH_DURATION_SAMPLES[:-1]
                    )
                value.pop("evidenceSha256")
                value["evidenceSha256"] = canonical_evidence_sha256(value)
                target.write_text(json.dumps(value), encoding="utf-8")

                with self.assertRaises((ValueError, RuntimeError)):
                    finalize_resident_provider_lifecycle_evidence(
                        before_dir=before,
                        after_dir=after,
                        provider_evidence_root=evidence_root,
                        checked_head=CHECKED_HEAD,
                        output_path=root / "lifecycle-evidence.json",
                    )

    def test_rejects_residual_runtime_state_or_an_unexpected_evidence_file(self) -> None:
        for mutation in (
            "container",
            "runtime-process",
            "network",
            "extra-evidence",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                before = root / "before"
                after = root / "after"
                evidence_root = root / "provider-evidence"
                _write_snapshots(before)
                changed = dict(SNAPSHOTS)
                if mutation == "container":
                    changed["containers.txt"] = b"yap-cohere-vllm\n"
                elif mutation == "runtime-process":
                    changed["runtime-processes.txt"] = b"socat loopback proxy\n"
                elif mutation == "network":
                    changed["networks.txt"] = b"yap-private-inference\n"
                _write_snapshots(after, changed)
                _write_artifacts(evidence_root)
                if mutation == "extra-evidence":
                    (evidence_root / "vllm" / "unexpected.json").write_text(
                        "{}",
                        encoding="utf-8",
                    )

                with self.assertRaises((ValueError, RuntimeError)):
                    finalize_resident_provider_lifecycle_evidence(
                        before_dir=before,
                        after_dir=after,
                        provider_evidence_root=evidence_root,
                        checked_head=CHECKED_HEAD,
                        output_path=root / "lifecycle-evidence.json",
                    )


if __name__ == "__main__":
    unittest.main()
