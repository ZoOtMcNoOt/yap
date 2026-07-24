from __future__ import annotations

import re
import unittest
from pathlib import Path

from yap_server.pools.model_lock import load_model_pool_lock


SERVER_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = SERVER_ROOT / "runtime" / "nemotron-nemo" / "Dockerfile"
REQUIREMENTS = SERVER_ROOT / "runtime" / "nemotron-nemo" / "requirements.lock"
NOTICE = SERVER_ROOT / "runtime" / "nemotron-nemo" / "THIRD_PARTY_NOTICES.md"
STREAMING_CONFIG = (
    SERVER_ROOT / "runtime" / "nemotron-nemo" / "cache-aware-streaming.yaml"
)
PIPELINE_SOURCE = (
    SERVER_ROOT / "src" / "yap_server" / "pools" / "nemotron_nemo_pipeline.py"
)
SERVING_LOCK = SERVER_ROOT / "nemotron-nemo-serving.lock.json"
NEMO_REVISION = "ba2cd63ef8de8a3183a3c02b310c66d616b9a991"


class NemotronNemoContainerContractTests(unittest.TestCase):
    def test_builds_exact_nemo_source_on_the_locked_arm64_base(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        lock = load_model_pool_lock(SERVING_LOCK)

        self.assertIn(f"{lock.runtime_image}@{lock.runtime_digest}", dockerfile)
        self.assertIn(f"ARG NEMO_REVISION={NEMO_REVISION}", dockerfile)
        self.assertIn('git -C /tmp/nemo-source rev-parse HEAD', dockerfile)
        self.assertIn('git -C /tmp/nemo-source config core.abbrev 9', dockerfile)
        self.assertIn('m.version("nemo_toolkit") == "3.1.0+ba2cd63ef"', dockerfile)
        self.assertNotIn(":latest", dockerfile)

    def test_installs_the_arm64_overlay_only_from_exact_hashes(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        requirements = REQUIREMENTS.read_text(encoding="utf-8")

        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("--no-deps", dockerfile)
        self.assertNotIn(">=", requirements)
        requirement_count = len(
            [line for line in requirements.splitlines() if line.endswith(" \\")]
        )
        self.assertEqual(requirement_count, 50)
        self.assertEqual(
            len(re.findall(r"--hash=sha256:[0-9a-f]{64}", requirements)),
            requirement_count,
        )
        self.assertIn(
            "triton-kernels 1.0.0+gitb7fa781f.nv26.6 requires pytest",
            dockerfile,
        )
        self.assertNotIn("pip check || true", dockerfile)
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

    def test_bakes_only_the_native_nemotron_lock_and_runs_offline_nonroot(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        lock = load_model_pool_lock(SERVING_LOCK)

        self.assertEqual(lock.pool_id, "nemotron-batch")
        self.assertEqual(lock.engine, "nemo")
        self.assertEqual(len(lock.artifacts), 1)
        self.assertTrue(lock.artifacts[0].path.endswith(".nemo"))
        self.assertIn(
            "COPY nemotron-nemo-serving.lock.json "
            "/opt/yap-server/model-locks/nemotron-batch.json",
            dockerfile,
        )
        self.assertNotIn("model-pools.lock.json", dockerfile)
        self.assertIn("HF_HUB_OFFLINE=1", dockerfile)
        self.assertIn("TRANSFORMERS_OFFLINE=1", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn(
            'ENTRYPOINT ["python3", "-m", "yap_server.pools.batch_asr_worker"]',
            dockerfile,
        )
        self.assertIn("Yap native NeMo Nemotron runtime", dockerfile)
        self.assertIn("AS application-source", dockerfile)
        self.assertIn("COPY --from=application-source", dockerfile)
        self.assertIn("test ! -e /opt/yap-server/yap_server/evaluation", dockerfile)
        service = (
            SERVER_ROOT
            / "src"
            / "yap_server"
            / "pools"
            / "nemotron_nemo_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class NemotronNemoApplication", service)
        self.assertIn("NEMOTRON_NEMO_MAX_ACTIVE_REQUESTS", service)

    def test_bakes_the_locked_bf16_cache_aware_streaming_profile(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        config = STREAMING_CONFIG.read_text(encoding="utf-8")

        self.assertIn("YAP_NEMOTRON_STREAMING_CONFIG=", dockerfile)
        self.assertIn("COPY runtime/nemotron-nemo/cache-aware-streaming.yaml", dockerfile)
        for expected in (
            "compute_dtype: bfloat16",
            "use_cuda_graph_decoder: false",
            "enable_per_stream_biasing: false",
            "batch_size: 8",
            "num_slots: 8",
            "att_context_size: [56, 13]",
            "use_cache: true",
            "use_feat_cache: true",
            "request_type: frame",
        ):
            self.assertIn(expected, config)
        self.assertNotIn("[70, 13]", config)
        self.assertNotIn("EuroLLM", config)
        for expected in (
            "OMP_NUM_THREADS=8",
            "MKL_NUM_THREADS=8",
            "OPENBLAS_NUM_THREADS=8",
            "NUMEXPR_NUM_THREADS=8",
            "RAYON_NUM_THREADS=8",
            "TOKENIZERS_PARALLELISM=false",
        ):
            self.assertIn(expected, dockerfile)

    def test_preserves_each_stream_prompt_at_the_decoder_boundary(self) -> None:
        source = PIPELINE_SOURCE.read_text(encoding="utf-8")

        for expected in (
            "prompt_vectors.shape[0] != batch_size",
            "prompt_vectors.shape[1] != prompt_count",
            "self.asr_model.prompt_kernel",
            "torch_module.cat([encoded, prompts], dim=-1)",
        ):
            self.assertIn(expected, source)

    def test_notice_records_source_model_and_overlay_license_boundaries(self) -> None:
        notice = NOTICE.read_text(encoding="utf-8")

        for expected in (
            NEMO_REVISION,
            "f3d333391852ba876df169dcc9ba902d25b6ab0b",
            "OpenMDW-1.1",
            "Apache-2.0",
            "BSD-2-Clause",
            "BSD-3-Clause",
            "LGPL-2.1-or-later",
            "MIT",
            "Artistic License",
        ):
            self.assertIn(expected, notice)


if __name__ == "__main__":
    unittest.main()
