import unittest
from pathlib import Path
import runpy

from yap_server.pools.model_lock import load_model_pool_lock


SERVER_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = SERVER_ROOT / "runtime" / "cohere-vllm" / "Dockerfile"
SERVING_LOCK = SERVER_ROOT / "cohere-vllm-serving.lock.json"
MELSCALE_COMPATIBILITY = (
    SERVER_ROOT
    / "runtime"
    / "cohere-vllm"
    / "compatibility"
    / "torchaudio"
    / "functional.py"
)
PYTORCH_FINALIZER_PATCH = (
    SERVER_ROOT
    / "runtime"
    / "cohere-vllm"
    / "compatibility"
    / "patch_pytorch_library_finalizer.py"
)
PYTORCH_LICENSE = (
    SERVER_ROOT
    / "runtime"
    / "cohere-vllm"
    / "licenses"
    / "PYTORCH-BSD-3-Clause.txt"
)
THIRD_PARTY_NOTICES = SERVER_ROOT / "runtime/cohere-vllm/THIRD_PARTY_NOTICES.md"


class CohereVllmContainerContractTests(unittest.TestCase):
    def test_uses_the_observed_arm64_nvidia_vllm_image_without_an_overlay(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "FROM nvcr.io/nvidia/vllm@sha256:"
            "bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e",
            dockerfile,
        )
        self.assertIn("sys.version_info[:2] == (3, 12)", dockerfile)
        self.assertIn(
            'torch.__version__ == "2.13.0a0+8145d630e8.nv26.06"',
            dockerfile,
        )
        self.assertIn('torch.version.cuda == "13.3"', dockerfile)
        self.assertIn(
            'm.version("vllm") == "0.22.1+7b9cb5b7.nv26.6.55915567"', dockerfile
        )
        self.assertNotIn("pip install", dockerfile)
        self.assertNotIn("tritonserver", dockerfile)
        self.assertNotIn("sglang", dockerfile.lower())

    def test_carries_only_the_attributed_mel_filterbank_compatibility_surface(
        self,
    ) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        compatibility = MELSCALE_COMPATIBILITY.read_text(encoding="utf-8")

        self.assertIn(
            "COPY runtime/cohere-vllm/compatibility /opt/yap-vllm-compatibility",
            dockerfile,
        )
        self.assertIn("PYTHONPATH=/opt/yap-vllm-compatibility", dockerfile)
        self.assertIn(
            'm.distribution("vllm").locate_file('
            '"vllm/model_executor/models/cohere_asr.py")',
            dockerfile,
        )
        self.assertIn('"class CohereAsrForConditionalGeneration"', dockerfile)
        self.assertIn(
            "from torchaudio.functional import melscale_fbanks",
            dockerfile,
        )
        self.assertIn("chmod -R a+rX", dockerfile)
        self.assertNotIn(
            "from vllm.model_executor.models.cohere_asr import",
            dockerfile,
        )
        self.assertIn("SPDX-License-Identifier: BSD-2-Clause", compatibility)
        self.assertIn("pytorch/audio", compatibility)
        self.assertIn("def melscale_fbanks(", compatibility)
        for unsupported in ("resample", "spectrogram", "rnnt_loss", "load"):
            self.assertNotIn(f"def {unsupported}(", compatibility)

    def test_backports_the_upstream_pytorch_finalizer_fix_exactly(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertTrue(PYTORCH_FINALIZER_PATCH.is_file())
        patcher = runpy.run_path(str(PYTORCH_FINALIZER_PATCH))
        patch_source = patcher["patch_pytorch_library_source"]
        original = (
            "        namespace = getattr(torch.ops, ns)\n"
            "        if not hasattr(namespace, name):\n"
            "            continue\n"
        )

        patched = patch_source(original)

        self.assertIn("if name not in vars(namespace):", patched)
        self.assertNotIn("if not hasattr(namespace, name):", patched)
        with self.assertRaisesRegex(RuntimeError, "exact pinned source"):
            patch_source(patched)
        self.assertIn(
            "python3 /opt/yap-vllm-compatibility/"
            "patch_pytorch_library_finalizer.py",
            dockerfile,
        )
        self.assertIn("BSD-3-Clause", dockerfile)
        notices = THIRD_PARTY_NOTICES.read_text(encoding="utf-8")
        self.assertIn("c5f8ebc91a8727a9056734f73329c217328b8989", notices)
        self.assertIn("BSD-3-Clause", notices)
        self.assertTrue(PYTORCH_LICENSE.is_file())
        self.assertIn(
            "Redistribution and use in source and binary forms",
            PYTORCH_LICENSE.read_text(encoding="utf-8"),
        )

    def test_exposes_one_bounded_authenticated_cohere_serving_profile(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=512", dockerfile)
        self.assertIn('ENTRYPOINT ["vllm", "serve"]', dockerfile)
        self.assertIn('"/models/asr"', dockerfile)
        self.assertIn('"--served-model-name"', dockerfile)
        self.assertIn('"CohereLabs/cohere-transcribe-03-2026"', dockerfile)
        self.assertIn('"--dtype", "bfloat16"', dockerfile)
        self.assertIn('"--kv-cache-memory-bytes", "1073741824"', dockerfile)
        self.assertNotIn('"--gpu-memory-utilization"', dockerfile)
        self.assertIn('"--max-num-seqs", "8"', dockerfile)
        self.assertIn('"--disable-fastapi-docs"', dockerfile)
        self.assertRegex(dockerfile, r"(?m)^USER 10001:10001$")
        self.assertIn("BSD-2-Clause", dockerfile)

    def test_serving_lock_matches_the_container_and_canonical_model(self) -> None:
        lock = load_model_pool_lock(SERVING_LOCK)

        self.assertEqual(lock.pool_id, "cohere-batch")
        self.assertEqual(lock.model_id, "CohereLabs/cohere-transcribe-03-2026")
        self.assertEqual(lock.runtime_image, "nvcr.io/nvidia/vllm")
        self.assertEqual(lock.runtime_source_tag, "26.06-py3")
        self.assertEqual(
            lock.runtime_digest,
            "sha256:bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e",
        )
        self.assertEqual(lock.runtime_python_version, "3.12")
        self.assertEqual(
            lock.runtime_reported_serving_version,
            "0.22.1+7b9cb5b7.dev",
        )
        self.assertEqual(
            lock.runtime_torch_version,
            "2.13.0a0+8145d630e8.nv26.06",
        )
        self.assertEqual(lock.runtime_torch_cuda_version, "13.3")
        self.assertEqual(
            dict(lock.runtime_overlay_packages),
            {
                "librosa": "0.11.0",
                "numpy": "2.1.0",
                "soundfile": "0.14.0",
                "soxr": "1.1.0",
                "transformers": "5.6.0",
                "vllm": "0.22.1+7b9cb5b7.nv26.6.55915567",
            },
        )


if __name__ == "__main__":
    unittest.main()
