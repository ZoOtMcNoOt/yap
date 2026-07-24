from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"
DOCKERFILE = REPO_ROOT / "server" / "runtime" / "lid" / "Dockerfile"
REQUIREMENTS = REPO_ROOT / "server" / "runtime" / "lid" / "requirements.lock"
NOTICE = REPO_ROOT / "server" / "runtime" / "lid" / "THIRD_PARTY_NOTICES.md"
BUILD_CHECK = REPO_ROOT / "server" / "runtime" / "lid" / "build_check.py"


class LanguageDetectionContainerContractTests(unittest.TestCase):
    def test_container_uses_the_exact_arm64_python_312_base(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["component"]
        runtime = lock["runtime"]
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        build_check = BUILD_CHECK.read_text(encoding="utf-8")
        expected = (
            f"FROM {runtime['image']}:{runtime['sourceTag']}@"
            f"{runtime['platformDigest']}"
        )

        self.assertIn(expected, dockerfile)
        self.assertNotIn("--platform=", dockerfile)
        self.assertNotEqual(runtime["indexDigest"], runtime["platformDigest"])
        self.assertNotIn(":latest", dockerfile)
        self.assertNotIn("nvcr.io", dockerfile.lower())
        self.assertNotRegex(dockerfile.lower(), r"(?m)^from .*nvidia")
        self.assertIn("sys.version_info[:3] == (3, 12, 13)", build_check)
        self.assertIn('"CPUExecutionProvider" in providers', build_check)
        self.assertIn('"CUDAExecutionProvider" not in providers', build_check)
        self.assertIn('"TensorrtExecutionProvider" not in providers', build_check)

    def test_container_installs_only_the_hash_locked_cpu_environment(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        requirements = REQUIREMENTS.read_text(encoding="utf-8")

        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("runtime/lid/requirements.lock", dockerfile)
        self.assertIn("numpy==2.4.6", requirements)
        self.assertIn("onnxruntime==1.27.0", requirements)
        self.assertNotIn("speechbrain==", requirements)
        self.assertNotIn("torch==", requirements)
        self.assertNotIn("torchaudio==", requirements)
        self.assertNotRegex(requirements, r"(?m)^nvidia-")
        self.assertNotRegex(requirements, r"(?m)^triton==")
        self.assertGreater(
            len(re.findall(r"--hash=sha256:[0-9a-f]{64}", requirements)),
            30,
        )
        self.assertLess(
            dockerfile.index("python3 -m pip install"),
            dockerfile.index("ARG YAP_CHECKED_HEAD"),
        )
        self.assertLess(
            dockerfile.index("python3 -m pip install"),
            dockerfile.index(
                'org.opencontainers.image.revision="${YAP_CHECKED_HEAD}"'
            ),
        )

    def test_container_carries_and_verifies_the_component_contract(self) -> None:
        payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["component"]
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        build_check = BUILD_CHECK.read_text(encoding="utf-8")
        requirements_digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()

        self.assertEqual(
            requirements_digest,
            payload["runtime"]["requirementsSha256"],
        )
        self.assertIn("lid-component.lock.json", dockerfile)
        self.assertIn("verify_lid_requirements", build_check)
        self.assertIn("yap-lid-build-check.py", dockerfile)
        self.assertIn("YAP_LID_COMPONENT_LOCK", dockerfile)
        self.assertIn("ARG YAP_CHECKED_HEAD", dockerfile)
        self.assertIn(
            'org.opencontainers.image.revision="${YAP_CHECKED_HEAD}"',
            dockerfile,
        )
        self.assertIn('com.mcnatg1.yap.runtime="language-detection"', dockerfile)
        self.assertIn(
            'ENTRYPOINT ["python3", "-m", "yap_server.lid.worker"]',
            dockerfile,
        )

    def test_container_is_nonroot_offline_and_contains_no_model_weights(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("OMP_NUM_THREADS=1", dockerfile)
        self.assertIn("OPENBLAS_NUM_THREADS=1", dockerfile)
        self.assertNotRegex(dockerfile, r"(?im)\b(curl|wget)\b")
        self.assertNotRegex(dockerfile, r"(?im)^COPY .*\.(ckpt|pt|pth|onnx)")
        self.assertNotIn("huggingface-cli", dockerfile)
        self.assertNotIn("snapshot_download", dockerfile)
        self.assertIn("AS application-source", dockerfile)
        self.assertIn("COPY --from=application-source", dockerfile)
        self.assertIn(
            "test ! -e /opt/yap-repo/server/src/yap_server/evaluation",
            dockerfile,
        )

    def test_runtime_notice_records_direct_package_and_model_provenance(self) -> None:
        notice = NOTICE.read_text(encoding="utf-8")
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["component"]

        for text in (
            "NumPy 2.4.6",
            "ONNX Runtime 1.27.0",
            lock["model"]["id"],
            lock["model"]["revision"],
            "NVIDIA NGC Terms of Use",
            "BSD-3-Clause",
            "Redistribution approval is not granted",
        ):
            self.assertIn(text, notice)


if __name__ == "__main__":
    unittest.main()
