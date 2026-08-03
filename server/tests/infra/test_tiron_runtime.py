from __future__ import annotations

from pathlib import Path
import runpy
import unittest


SERVER_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = SERVER_ROOT / "runtime" / "tiron" / "Dockerfile"
ECAPA_PATCH = (
    SERVER_ROOT / "runtime" / "tiron" / "compatibility" / "patch_local_ecapa_source.py"
)
NOTICES = SERVER_ROOT / "runtime" / "tiron" / "THIRD_PARTY_NOTICES.md"


class TironRuntimeContractTests(unittest.TestCase):
    def test_patches_only_the_upstream_ecapa_loader_for_verified_local_artifacts(
        self,
    ) -> None:
        patcher = runpy.run_path(str(ECAPA_PATCH))
        patch_source = patcher["patch_tiron_engine_source"]
        upstream = (
            "        self.ecapa = EncoderClassifier.from_hparams(\n"
            "            source=config.ECAPA_MODEL,\n"
            '            run_opts={"device": self.ecapa_device},\n'
            "        )\n"
        )

        patched = patch_source(upstream)

        self.assertIn(
            'overrides={"pretrained_path": config.ECAPA_MODEL}',
            patched,
        )
        self.assertEqual(patched.count("overrides="), 1)
        with self.assertRaisesRegex(RuntimeError, "exact pinned source"):
            patch_source(patched)

    def test_image_runs_the_pinned_upstream_runtime_offline(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "nvcr.io/nvidia/pytorch@sha256:"
            "dcae8df08ef61b019b8eb109113428cba4ef0e37484c6e722406150dd5ada759",
            dockerfile,
        )
        self.assertIn(
            "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
            dockerfile,
        )
        self.assertIn(
            "34c52a67e8941bbd8e6adaca0eb0b9eabec11d78",
            dockerfile,
        )
        self.assertIn("HF_HUB_OFFLINE=1", dockerfile)
        self.assertIn("TRANSFORMERS_OFFLINE=1", dockerfile)
        self.assertIn(
            "python3 /opt/tiron-compatibility/patch_local_ecapa_source.py",
            dockerfile,
        )
        self.assertIn('com.mcnatg1.yap.runtime="meeting-transcription"', dockerfile)
        self.assertIn("ISC AND LGPL-2.1-or-later", dockerfile)
        self.assertIn("SHARED_PYTHON_THIRD_PARTY_NOTICES.md", dockerfile)
        source_prune = "rm -rf /tmp/yap-application-source/yap_server/evaluation"
        final_copy = (
            "COPY --from=application-source /tmp/yap-application-source/yap_server "
            "/opt/yap-server/yap_server"
        )
        self.assertIn(source_prune, dockerfile)
        self.assertLess(dockerfile.index(source_prune), dockerfile.index(final_copy))
        self.assertNotIn("rm -rf /opt/yap-server/yap_server/evaluation", dockerfile)
        self.assertIn(
            "test ! -e /opt/yap-server/yap_server/evaluation",
            dockerfile,
        )
        self.assertRegex(dockerfile, r"(?m)^USER 10001:10001$")
        self.assertNotIn("git clone", dockerfile)
        self.assertNotIn('Trelis/tiron",', dockerfile)

        notices = NOTICES.read_text(encoding="utf-8")
        self.assertIn("verified local ECAPA", notices)
        self.assertIn(
            "d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c",
            notices,
        )
        self.assertIn("SHARED_PYTHON_THIRD_PARTY_NOTICES.md", notices)
        self.assertIn("LGPL-2.1-or-later", notices)


if __name__ == "__main__":
    unittest.main()
