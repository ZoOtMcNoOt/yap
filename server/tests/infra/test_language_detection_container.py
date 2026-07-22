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
            f"FROM --platform={runtime['platform']} "
            f"{runtime['image']}:{runtime['sourceTag']}@{runtime['indexDigest']}"
        )

        self.assertIn(expected, dockerfile)
        self.assertIn(runtime["platformDigest"], dockerfile)
        self.assertNotIn(":latest", dockerfile)
        self.assertNotIn("nvcr.io", dockerfile.lower())
        self.assertNotRegex(dockerfile.lower(), r"(?m)^from .*nvidia")
        self.assertIn("sys.version_info[:3] == (3, 12, 13)", build_check)
        self.assertIn("torch.version.cuda is None", build_check)
        self.assertIn("not torch.cuda.is_available()", build_check)

    def test_container_installs_only_the_hash_locked_cpu_environment(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        requirements = REQUIREMENTS.read_text(encoding="utf-8")

        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("runtime/lid/requirements.lock", dockerfile)
        self.assertIn("speechbrain==1.1.0", requirements)
        self.assertIn("torch==2.11.0+cpu", requirements)
        self.assertIn("torchaudio==2.11.0+cpu", requirements)
        self.assertNotRegex(requirements, r"(?m)^nvidia-")
        self.assertNotRegex(requirements, r"(?m)^triton==")
        for digest in (
            "0f1bc7d5c5ce07b9ed752a9d931a4858180f825f4d079b44035a0aed645f4dd2",
            "70ecb2659af6373b7c5336e692e665605b0201ea21ff51aaea47e1d75ea6b5aa",
            "b9dd2c6ac144001dc6dac38b564c1de73ac26ef0c195d5037c4a94990b0e2b5a",
        ):
            self.assertIn(f"--hash=sha256:{digest}", requirements)
        self.assertGreater(
            len(re.findall(r"--hash=sha256:[0-9a-f]{64}", requirements)),
            30,
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
        self.assertIn(
            'ENTRYPOINT ["python3", "-m", "yap_server.lid.worker"]',
            dockerfile,
        )

    def test_container_is_nonroot_offline_and_contains_no_model_weights(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("HF_HUB_OFFLINE=1", dockerfile)
        self.assertIn("TRANSFORMERS_OFFLINE=1", dockerfile)
        self.assertIn("HF_HUB_DISABLE_TELEMETRY=1", dockerfile)
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
            "SpeechBrain 1.1.0",
            "PyTorch 2.11.0+cpu",
            "TorchAudio 2.11.0+cpu",
            lock["model"]["id"],
            lock["model"]["revision"],
            "Apache-2.0",
            "BSD-2-Clause",
            "BSD-3-Clause",
        ):
            self.assertIn(text, notice)


if __name__ == "__main__":
    unittest.main()
