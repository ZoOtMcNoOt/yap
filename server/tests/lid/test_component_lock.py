from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from yap_server.lid.component_lock import (
    LidComponentArtifactError,
    load_lid_component_lock,
    verify_lid_model_artifacts,
    verify_lid_requirements,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_LOCK = REPO_ROOT / "server" / "lid-component.lock.json"
EXPECTED_ARTIFACTS = {
    "ambernet-1.12.0-classifier-int8-qdq.onnx",
}
MODEL_FILE = next(iter(EXPECTED_ARTIFACTS))


def _payload() -> dict[str, object]:
    return json.loads(COMPONENT_LOCK.read_text(encoding="utf-8"))


def _write_lock(root: Path, payload: dict[str, object]) -> Path:
    path = root / "lid-component.lock.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class LidComponentLockTests(unittest.TestCase):
    def test_committed_lock_pins_cpu_runtime_model_policy_and_requirements(
        self,
    ) -> None:
        lock = load_lid_component_lock(COMPONENT_LOCK)

        self.assertEqual(lock.schema_version, 3)
        self.assertEqual(lock.component_id, "ambernet-batch-language-preflight")
        self.assertEqual(lock.runtime.platform, "linux/arm64")
        self.assertEqual(lock.runtime.python_version, "3.12.13")
        self.assertTrue(lock.runtime.cpu_only)
        self.assertEqual(
            dict(lock.runtime.packages),
            {
                "numpy": "2.4.6",
                "onnxruntime": "1.27.0",
            },
        )
        self.assertEqual(
            lock.model.model_id,
            "nvidia/nemo/langid_ambernet",
        )
        self.assertEqual(
            lock.model.revision,
            "1.12.0",
        )
        self.assertEqual(lock.model.license, "NVIDIA-NGC-Terms")
        self.assertEqual(lock.model.distribution_policy, "verify-only-import")
        self.assertEqual(lock.model.redistribution_approval, "not-approved")
        self.assertEqual(lock.model.frontend_revision, "nemo-fixed-3s-v1")
        self.assertEqual(
            lock.model.label_order_sha256,
            "9c64d2027a37ed72852eea368a7c81eff62efb3c39e72a1567dad35fb83d2e50",
        )
        self.assertEqual(lock.model.label_count, 107)
        self.assertEqual(
            {artifact.path for artifact in lock.model.artifacts},
            EXPECTED_ARTIFACTS,
        )
        self.assertEqual(lock.policy.sample_rate_hz, 16_000)
        self.assertEqual(lock.policy.maximum_windows, 5)
        self.assertEqual(lock.policy.maximum_window_samples, 96_000)
        self.assertEqual(lock.policy.minimum_voiced_samples_per_window, 51_200)
        self.assertEqual(lock.policy.score_semantics, "mean-logit-log-softmax")
        self.assertTrue(lock.policy.user_confirmation_required)
        self.assertEqual(
            verify_lid_requirements(lock, REPO_ROOT),
            (
                REPO_ROOT
                / "server"
                / "runtime"
                / "lid"
                / "requirements.lock"
            ).resolve(),
        )

    def test_verifies_every_staged_model_artifact_by_size_and_digest(self) -> None:
        payload = _payload()
        component = payload["component"]
        assert isinstance(component, dict)
        model = component["model"]
        assert isinstance(model, dict)
        artifacts = model["artifacts"]
        assert isinstance(artifacts, list)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            model_dir.mkdir()
            for artifact in artifacts:
                assert isinstance(artifact, dict)
                content = f"locked:{artifact['path']}".encode()
                (model_dir / str(artifact["path"])).write_bytes(content)
                artifact["size"] = len(content)
                artifact["sha256"] = hashlib.sha256(content).hexdigest()

            lock = load_lid_component_lock(_write_lock(root, payload))
            verify_lid_model_artifacts(lock, model_dir)

            (model_dir / MODEL_FILE).write_bytes(b"tampered")
            with self.assertRaisesRegex(
                LidComponentArtifactError,
                MODEL_FILE,
            ):
                verify_lid_model_artifacts(lock, model_dir)

    def test_rejects_missing_directory_and_link_artifacts(self) -> None:
        payload = _payload()
        component = payload["component"]
        assert isinstance(component, dict)
        model = component["model"]
        assert isinstance(model, dict)
        artifacts = model["artifacts"]
        assert isinstance(artifacts, list)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            model_dir.mkdir()
            for artifact in artifacts:
                assert isinstance(artifact, dict)
                content = f"locked:{artifact['path']}".encode()
                artifact["size"] = len(content)
                artifact["sha256"] = hashlib.sha256(content).hexdigest()
                (model_dir / str(artifact["path"])).write_bytes(content)
            lock = load_lid_component_lock(_write_lock(root, payload))

            (model_dir / MODEL_FILE).unlink()
            with self.assertRaisesRegex(LidComponentArtifactError, "missing"):
                verify_lid_model_artifacts(lock, model_dir)

            (model_dir / MODEL_FILE).mkdir()
            with self.assertRaisesRegex(LidComponentArtifactError, "regular file"):
                verify_lid_model_artifacts(lock, model_dir)

            (model_dir / MODEL_FILE).rmdir()
            target = root / "outside.onnx"
            target.write_bytes(f"locked:{MODEL_FILE}".encode())
            try:
                os.symlink(target, model_dir / MODEL_FILE)
            except OSError:
                return
            with self.assertRaisesRegex(LidComponentArtifactError, "regular file"):
                verify_lid_model_artifacts(lock, model_dir)

    def test_rejects_traversal_mutable_revision_and_wrong_artifact_set(self) -> None:
        mutations = (
            (
                "artifact traversal",
                lambda value: value["component"]["model"]["artifacts"][0].update(
                    {"path": "../classifier.onnx"}
                ),
            ),
            (
                "mutable revision",
                lambda value: value["component"]["model"].update(
                    {"revision": "main"}
                ),
            ),
            (
                "wrong artifact set",
                lambda value: value["component"]["model"]["artifacts"].pop(),
            ),
            (
                "wrong label count",
                lambda value: value["component"]["model"].update(
                    {"labelCount": 106}
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                payload = _payload()
                mutate(payload)
                with self.assertRaises(ValueError):
                    load_lid_component_lock(_write_lock(Path(directory), payload))

    def test_rejects_unpinned_packages_or_a_false_cpu_only_claim(self) -> None:
        mutations = (
            lambda value: value["component"]["runtime"]["packages"].update(
                {"numpy": "2.4"}
            ),
            lambda value: value["component"]["runtime"].update(
                {"cpuOnly": False}
            ),
        )
        for mutate in mutations:
            with (
                self.subTest(mutate=mutate),
                tempfile.TemporaryDirectory() as directory,
            ):
                payload = _payload()
                mutate(payload)
                with self.assertRaises(ValueError):
                    load_lid_component_lock(_write_lock(Path(directory), payload))

    def test_rejects_unknown_fields_and_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _payload()
            payload["unexpected"] = True
            with self.assertRaisesRegex(ValueError, "unexpected"):
                load_lid_component_lock(_write_lock(root, payload))

            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"schemaVersion":1,"schemaVersion":1,"component":{}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_lid_component_lock(duplicate)

    def test_rejects_oversized_lock_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lid-component.lock.json"
            path.write_bytes(b" " * (256 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "oversized"):
                load_lid_component_lock(path)


if __name__ == "__main__":
    unittest.main()
