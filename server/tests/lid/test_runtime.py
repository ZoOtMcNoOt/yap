from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server.lid.component_lock import load_lid_component_lock
from yap_server.lid.runtime import (
    build_language_detection_runtime,
    fixed_locales_from_asr_catalog,
    publish_language_detection_capabilities,
    reconcile_stale_lid_requests,
    resolve_language_detection_worker_image,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "server" / "lid-component.lock.json"
CHECKED_HEAD = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
CATALOG_REVISION = "c" * 64


def _catalog() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "catalogRevision": CATALOG_REVISION,
        "providers": [
            {
                "capabilities": [
                    {"languageBcp47": "fr-FR", "mode": "fixedBatch"},
                    {"languageBcp47": "en-US", "mode": "fixedBatch"},
                    {"languageBcp47": "de-DE", "mode": "dynamicBatch"},
                    {"languageBcp47": "en-US", "mode": "serverLive"},
                ]
            }
        ],
    }


class LidRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lid_component_lock(LOCK_PATH)

    def test_builds_verified_cpu_preflight_beside_the_private_asr_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "storage"
            model = root / "model"
            storage.mkdir()
            model.mkdir()
            environ = {
                "YAP_LANGUAGE_DETECTION_ENABLED": "1",
                "YAP_LANGUAGE_DETECTION_MODEL_DIR": str(model),
                "YAP_LANGUAGE_DETECTION_WORKER_IMAGE": "yap-lid:test",
                "YAP_CHECKED_HEAD": CHECKED_HEAD,
                "YAP_LANGUAGE_DETECTION_DOCKER_BINARY": "docker-test",
            }
            inspection = {
                "id": IMAGE_ID,
                "labels": {
                    "com.mcnatg1.yap.base-platform-digest": (
                        self.lock.runtime.platform_digest
                    )
                },
            }
            with (
                patch(
                    "yap_server.lid.runtime.verify_lid_model_artifacts"
                ) as verify_model,
                patch(
                    "yap_server.lid.runtime.inspect_worker_image",
                    return_value=inspection,
                ) as inspect,
                patch(
                    "yap_server.lid.runtime.reconcile_lid_containers",
                    return_value=0,
                ) as reconcile_containers,
            ):
                runtime = build_language_detection_runtime(
                    environ,
                    repository_root=REPO_ROOT,
                    storage_dir=storage,
                    asr_capabilities=_catalog(),
                    run_as_uid=1000,
                    run_as_gid=1000,
                    storage_namespace="storage-test",
                )

            self.assertIsNotNone(runtime)
            assert runtime is not None
            self.assertEqual(runtime.work_root, storage / "lid-preflight")
            self.assertEqual(list(runtime.work_root.iterdir()), [])
            self.assertEqual(
                runtime.capabilities,
                {
                    "schemaVersion": 1,
                    "componentId": "speechbrain-lid-preflight",
                    "runtime": {"pythonVersion": "3.12.13", "cpuOnly": True},
                    "model": {
                        "id": "speechbrain/lang-id-voxlingua107-ecapa",
                        "revision": (
                            "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"
                        ),
                    },
                    "transport": {
                        "mediaType": (
                            "application/vnd.yap.lid-preflight.v1+octet-stream"
                        ),
                        "maximumBodyBytes": 1_048_576,
                        "maximumManifestBytes": 32_768,
                        "maximumResponseSeconds": 120,
                    },
                    "policy": {
                        "revision": "speechbrain-two-window-v1",
                        "sampleRateHz": 16_000,
                        "channelCount": 1,
                        "sampleWidthBytes": 2,
                        "minimumSourceSamples": 480_000,
                        "maximumWindows": 2,
                        "maximumWindowSamples": 240_000,
                        "minimumVoicedSamplesPerWindow": 128_000,
                        "scoreSemantics": "uncalibrated-log-posterior",
                        "userConfirmationRequired": True,
                    },
                },
            )
            advertised = publish_language_detection_capabilities(_catalog(), runtime)
            self.assertEqual(
                advertised["languagePreflight"],
                runtime.capabilities,
            )
            self.assertNotIn("languagePreflight", _catalog())
            verify_model.assert_called_once_with(self.lock, model.resolve())
            inspect.assert_called_once_with(
                environ["YAP_LANGUAGE_DETECTION_WORKER_IMAGE"],
                CHECKED_HEAD,
                docker_binary="docker-test",
            )
            reconcile_containers.assert_called_once_with(
                "docker-test",
                storage_namespace="storage-test",
            )
            runtime.close()

    def test_runtime_is_explicit_and_rejects_invalid_enable_values(self) -> None:
        arguments = {
            "repository_root": REPO_ROOT,
            "storage_dir": Path("unused"),
            "asr_capabilities": _catalog(),
            "run_as_uid": 1000,
            "run_as_gid": 1000,
            "storage_namespace": "storage-test",
        }
        self.assertIsNone(build_language_detection_runtime({}, **arguments))
        with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
            build_language_detection_runtime(
                {"YAP_LANGUAGE_DETECTION_ENABLED": "yes"},
                **arguments,
            )

    def test_resolves_only_an_arm64_checked_head_image_with_locked_base(self) -> None:
        environ = {
            "YAP_LANGUAGE_DETECTION_WORKER_IMAGE": "yap-lid:test",
            "YAP_CHECKED_HEAD": CHECKED_HEAD,
        }
        valid = {
            "id": IMAGE_ID,
            "labels": {
                "com.mcnatg1.yap.base-platform-digest": (
                    self.lock.runtime.platform_digest
                )
            },
        }
        with patch(
            "yap_server.lid.runtime.inspect_worker_image",
            return_value=valid,
        ):
            self.assertEqual(
                resolve_language_detection_worker_image(
                    environ,
                    lock=self.lock,
                    docker_binary="docker-test",
                ),
                IMAGE_ID,
            )

        invalid = {
            "id": IMAGE_ID,
            "labels": {
                "com.mcnatg1.yap.base-platform-digest": "sha256:" + "d" * 64
            },
        }
        with (
            patch(
                "yap_server.lid.runtime.inspect_worker_image",
                return_value=invalid,
            ),
            self.assertRaisesRegex(ValueError, "base platform digest"),
        ):
            resolve_language_detection_worker_image(
                environ,
                lock=self.lock,
                docker_binary="docker-test",
            )

    def test_catalog_contributes_only_unique_fixed_locale_destinations(self) -> None:
        self.assertEqual(
            fixed_locales_from_asr_catalog(_catalog()),
            ("en-US", "fr-FR"),
        )
        with self.assertRaisesRegex(ValueError, "catalog revision"):
            fixed_locales_from_asr_catalog({"providers": []})

        with self.assertRaisesRegex(ValueError, "already contains"):
            publish_language_detection_capabilities(
                {**_catalog(), "languagePreflight": {}},
                object(),  # type: ignore[arg-type]
            )

    def test_startup_removes_only_exact_owned_transient_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "lid-request-01"
            stale.mkdir()
            (stale / "probe-0.wav").write_bytes(b"probe")
            (stale / ".request.json.part").write_bytes(b"request")

            self.assertEqual(reconcile_stale_lid_requests(root), 1)
            self.assertEqual(list(root.iterdir()), [])

            unrelated = root / "user-data"
            unrelated.mkdir()
            marker = unrelated / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unexpected entry"):
                reconcile_stale_lid_requests(root)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
