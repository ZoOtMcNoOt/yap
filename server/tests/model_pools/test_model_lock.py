import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from yap_server.language_tags import canonical_bcp47
from yap_server.pools.model_lock import (
    ModelArtifactError,
    load_model_pool_lock,
    verify_model_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_LOCK = REPO_ROOT / "server" / "model-pools.lock.json"
NEMOTRON_MODEL_LOCK = REPO_ROOT / "server" / "nemotron-model-pool.lock.json"
NEMOTRON_NEMO_SERVING_LOCK = (
    REPO_ROOT / "server" / "nemotron-nemo-serving.lock.json"
)


class ModelPoolLockTests(unittest.TestCase):
    def test_committed_lock_pins_runtime_model_and_fixture(self) -> None:
        lock = load_model_pool_lock(MODEL_LOCK)

        self.assertEqual(lock.schema_version, 1)
        self.assertEqual(lock.pool_id, "cohere-batch")
        self.assertEqual(lock.engine, "transformers")
        self.assertEqual(lock.model_id, "CohereLabs/cohere-transcribe-03-2026")
        self.assertEqual(len(lock.model_revision), 40)
        self.assertEqual(lock.model_license, "Apache-2.0")
        self.assertEqual(
            lock.model_distribution_id,
            "ZoOtMcNoOt/yap-cohere-transcribe-03-2026",
        )
        self.assertEqual(len(lock.model_distribution_revision), 40)
        self.assertIn("Xet object identity", lock.model_distribution_provenance)
        self.assertEqual(
            set(lock.supported_languages),
            {
                "ar",
                "de",
                "el",
                "en",
                "es",
                "fr",
                "it",
                "ja",
                "ko",
                "nl",
                "pl",
                "pt",
                "vi",
                "zh",
            },
        )
        self.assertEqual(lock.runtime_platform, "linux/arm64")
        self.assertEqual(
            lock.runtime_source,
            "https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch/tags",
        )
        self.assertIn("NVIDIA Software License Agreement", lock.runtime_license)
        self.assertEqual(lock.runtime_cuda_version, "13.3.0")
        self.assertEqual(lock.runtime_torch_cuda_version, "13.3")
        self.assertEqual(
            dict(lock.runtime_overlay_packages),
            {
                "audioread": "3.1.0",
                "joblib": "1.5.3",
                "lazy-loader": "0.5",
                "librosa": "0.11.0",
                "msgpack": "1.2.1",
                "narwhals": "2.24.0",
                "pooch": "1.9.0",
                "scikit-learn": "1.9.0",
                "sentencepiece": "0.2.1",
                "soundfile": "0.14.0",
                "soxr": "1.1.0",
                "threadpoolctl": "3.6.0",
                "tokenizers": "0.22.2",
                "transformers": "5.13.1",
            },
        )
        self.assertRegex(lock.runtime_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn(":latest", lock.runtime_image)
        self.assertGreaterEqual(len(lock.artifacts), 5)
        self.assertEqual(lock.fixture.license, "CC-BY-4.0")
        self.assertRegex(lock.fixture.sha256, r"^[0-9a-f]{64}$")
        self.assertTrue((REPO_ROOT / lock.fixture.path).is_file())

    def test_nemotron_reference_lock_pins_the_direct_transformers_artifacts(self) -> None:
        lock = load_model_pool_lock(NEMOTRON_MODEL_LOCK)

        self.assertEqual(lock.pool_id, "nemotron-batch")
        self.assertEqual(lock.engine, "transformers")
        self.assertEqual(
            lock.model_id,
            "nvidia/nemotron-3.5-asr-streaming-0.6b",
        )
        self.assertEqual(
            lock.model_revision,
            "f3d333391852ba876df169dcc9ba902d25b6ab0b",
        )
        self.assertEqual(lock.model_license, "OpenMDW-1.1")
        self.assertEqual(lock.model_distribution_id, lock.model_id)
        self.assertEqual(lock.model_distribution_revision, lock.model_revision)
        self.assertEqual(lock.runtime_python_version, "3.12")
        self.assertEqual(lock.runtime_torch_version, "2.13.0a0+8145d630e8.nv26.06")
        self.assertEqual(dict(lock.runtime_overlay_packages)["transformers"], "5.13.1")
        self.assertIn("auto", lock.supported_languages)
        self.assertEqual(len(lock.supported_languages), 33)
        enabled_locales = set(lock.supported_languages) - {"auto"}
        self.assertEqual(
            enabled_locales,
            {
                "ar-AR",
                "bg-BG",
                "cs-CZ",
                "da-DK",
                "de-DE",
                "en-GB",
                "en-US",
                "es-ES",
                "es-US",
                "et-EE",
                "fi-FI",
                "fr-CA",
                "fr-FR",
                "hi-IN",
                "hr-HR",
                "hu-HU",
                "it-IT",
                "ja-JP",
                "ko-KR",
                "nb-NO",
                "nl-NL",
                "pl-PL",
                "pt-BR",
                "pt-PT",
                "ro-RO",
                "ru-RU",
                "sk-SK",
                "sv-SE",
                "tr-TR",
                "uk-UA",
                "vi-VN",
                "zh-CN",
            },
        )
        self.assertEqual(
            {canonical_bcp47(locale, "enabled locale") for locale in enabled_locales},
            enabled_locales,
        )
        self.assertTrue(
            enabled_locales.isdisjoint(
                {"enGB", "esES", "hi-HI", "ja-JA", "ko-KO", "sl-SL", "zh-ZH"}
            )
        )
        self.assertEqual(
            {artifact.path for artifact in lock.artifacts},
            {
                "README.md",
                "config.json",
                "generation_config.json",
                "model.safetensors",
                "processor_config.json",
                "tokenizer.json",
                "tokenizer_config.json",
            },
        )

    def test_native_nemo_lock_pins_the_checkpoint_and_python_312_runtime(self) -> None:
        lock = load_model_pool_lock(NEMOTRON_NEMO_SERVING_LOCK)

        self.assertEqual(lock.pool_id, "nemotron-batch")
        self.assertEqual(lock.engine, "nemo")
        self.assertEqual(lock.model_id, "nvidia/nemotron-3.5-asr-streaming-0.6b")
        self.assertEqual(lock.model_revision, "f3d333391852ba876df169dcc9ba902d25b6ab0b")
        self.assertEqual(lock.runtime_image, "nvcr.io/nvidia/pytorch")
        self.assertEqual(lock.runtime_source_tag, "26.06-py3")
        self.assertEqual(lock.runtime_python_version, "3.12")
        self.assertEqual(lock.runtime_torch_version, "2.13.0a0+8145d630e8.nv26.06")
        self.assertEqual(lock.runtime_torch_cuda_version, "13.3")
        self.assertEqual(dict(lock.runtime_overlay_packages)["nemo_toolkit"], "3.1.0+ba2cd63ef")
        self.assertEqual(
            [(artifact.path, artifact.size, artifact.sha256) for artifact in lock.artifacts],
            [
                (
                    "nemotron-3.5-asr-streaming-0.6b.nemo",
                    2_368_284_501,
                    "210214ed94039bf6bfbb9a047c7fa289628db75b103e2bf6381fa78285436a74",
                )
            ],
        )

    def test_verifies_every_artifact_without_trusting_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            model_dir.mkdir()
            content = b"pinned-model-content"
            (model_dir / "weights.bin").write_bytes(content)
            fixture = root / "fixture.wav"
            fixture.write_bytes(b"fixture")
            lock_path = root / "lock.json"
            lock_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "runtime": {
                            "image": "registry.example/asr:1",
                            "source": "https://example.invalid/runtime",
                            "license": "Example runtime license",
                            "platform": "linux/arm64",
                            "digest": "sha256:" + "a" * 64,
                            "sourceTag": "1.2.3",
                            "pythonVersion": "3.12",
                            "torchVersion": "2.13.0a0+example",
                            "cudaVersion": "13.3.0",
                            "torchCudaVersion": "13.3",
                            "overlayPackages": {"transformers": "5.13.1"},
                        },
                        "pool": {
                            "id": "example-batch",
                            "engine": "transformers",
                            "model": {
                                "id": "example/model",
                                "revision": "b" * 40,
                                "license": "CC-BY-4.0",
                                "source": "https://example.invalid/model",
                                "distribution": {
                                    "id": "example/model-mirror",
                                    "revision": "c" * 40,
                                    "source": "https://example.invalid/model-mirror",
                                    "provenance": "verified test distribution",
                                },
                            },
                            "supportedLanguages": ["en"],
                            "artifacts": [
                                {
                                    "path": "weights.bin",
                                    "size": len(content),
                                    "sha256": hashlib.sha256(content).hexdigest(),
                                }
                            ],
                        },
                        "fixture": {
                            "path": "fixture.wav",
                            "source": "https://example.invalid/fixture.wav",
                            "license": "CC-BY-4.0",
                            "sha256": hashlib.sha256(b"fixture").hexdigest(),
                            "goldenTranscript": "fixture",
                        },
                    }
                ),
                encoding="utf-8",
            )

            lock = load_model_pool_lock(lock_path)
            verify_model_artifacts(lock, model_dir)

            (model_dir / "weights.bin").write_bytes(b"tampered")
            with self.assertRaises(ModelArtifactError):
                verify_model_artifacts(lock, model_dir)

    def test_rejects_traversal_artifact_path(self) -> None:
        payload = json.loads(MODEL_LOCK.read_text(encoding="utf-8"))
        payload["pool"]["artifacts"][0]["path"] = "../weights.bin"
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_model_pool_lock(lock_path)

    def test_rejects_an_oversized_model_lock_before_json_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_bytes(b" " * (2 * 1024 * 1024 + 1))

            with self.assertRaisesRegex(ValueError, "oversized"):
                load_model_pool_lock(lock_path)


if __name__ == "__main__":
    unittest.main()
