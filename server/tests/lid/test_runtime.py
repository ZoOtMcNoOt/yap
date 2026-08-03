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
PREPARATION_RECEIPT = str(REPO_ROOT / "private-lid-preparation.json")
PREPARATION_RECEIPT_SHA256 = "d" * 64


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
            work_root = storage / "lid-preflight"
            recovery = work_root / "lid-recovery-request"
            recovery.mkdir(parents=True)
            (recovery / ".yap-container-id").write_text(
                "e" * 64,
                encoding="utf-8",
            )
            startup_order: list[str] = []

            def reconcile_containers(*_args: object, **_kwargs: object) -> int:
                startup_order.append("containers")
                return 1

            def reconcile_requests(path: Path, **kwargs: object) -> int:
                self.assertEqual(startup_order, ["containers"])
                startup_order.append("requests")
                return reconcile_stale_lid_requests(path, **kwargs)

            environ = {
                "YAP_LANGUAGE_DETECTION_ENABLED": "1",
                "YAP_LANGUAGE_DETECTION_MODEL_DIR": str(model),
                "YAP_LANGUAGE_DETECTION_WORKER_IMAGE": IMAGE_ID,
                "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT": (PREPARATION_RECEIPT),
                "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256": (
                    PREPARATION_RECEIPT_SHA256
                ),
                "YAP_CHECKED_HEAD": CHECKED_HEAD,
                "YAP_LANGUAGE_DETECTION_DOCKER_BINARY": "docker-test",
            }
            with (
                patch(
                    "yap_server.lid.runtime.verify_lid_model_artifacts"
                ) as verify_model,
                patch(
                    "yap_server.lid.runtime.resolve_receipt_bound_runtime_image",
                    return_value=IMAGE_ID,
                ) as resolve_image,
                patch(
                    "yap_server.lid.runtime.reconcile_lid_containers",
                    side_effect=reconcile_containers,
                ) as reconcile_containers,
                patch(
                    "yap_server.lid.runtime.reconcile_stale_lid_requests",
                    side_effect=reconcile_requests,
                ) as reconcile_requests,
                patch(
                    "yap_server.lid.runtime.verify_lid_container_absent",
                ) as verify_recovery_container,
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
                    "componentId": "ambernet-batch-language-preflight",
                    "runtime": {"pythonVersion": "3.12.13", "cpuOnly": True},
                    "model": {
                        "id": "nvidia/nemo/langid_ambernet",
                        "revision": "1.12.0",
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
                        "revision": "ambernet-stratified-five-region-v1",
                        "sampleRateHz": 16_000,
                        "channelCount": 1,
                        "sampleWidthBytes": 2,
                        "minimumSourceSamples": 480_000,
                        "maximumWindows": 5,
                        "maximumWindowSamples": 96_000,
                        "minimumVoicedSamplesPerWindow": 51_200,
                        "scoreSemantics": "mean-logit-log-softmax",
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
            resolve_image.assert_called_once_with(
                environ,
                runtime="language-detection",
                image_environment_variable="YAP_LANGUAGE_DETECTION_WORKER_IMAGE",
                checked_head_environment_variable="YAP_CHECKED_HEAD",
                receipt_environment_variable=(
                    "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT"
                ),
                receipt_sha256_environment_variable=(
                    "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256"
                ),
                docker_binary="docker-test",
                repository_root=REPO_ROOT,
                expected_base_digest=self.lock.runtime.platform_digest,
            )
            reconcile_containers.assert_called_once_with(
                "docker-test",
                storage_namespace="storage-test",
            )
            reconcile_requests.assert_called_once()
            self.assertEqual(reconcile_requests.call_args.args, (work_root,))
            self.assertTrue(
                reconcile_requests.call_args.kwargs["retire_container_identities"]
            )
            self.assertTrue(
                callable(reconcile_requests.call_args.kwargs["verify_container_absent"])
            )
            verify_recovery_container.assert_called_once_with(
                "docker-test",
                "e" * 64,
            )
            self.assertEqual(startup_order, ["containers", "requests"])
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

    def test_resolves_only_the_receipt_bound_immutable_image_id(self) -> None:
        environ = {
            "YAP_LANGUAGE_DETECTION_WORKER_IMAGE": IMAGE_ID,
            "YAP_CHECKED_HEAD": CHECKED_HEAD,
            "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT": PREPARATION_RECEIPT,
            "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256": (
                PREPARATION_RECEIPT_SHA256
            ),
        }
        with patch(
            "yap_server.lid.runtime.resolve_receipt_bound_runtime_image",
            return_value=IMAGE_ID,
        ) as resolve_image:
            self.assertEqual(
                resolve_language_detection_worker_image(
                    environ,
                    lock=self.lock,
                    docker_binary="docker-test",
                    repository_root=REPO_ROOT,
                ),
                IMAGE_ID,
            )
        resolve_image.assert_called_once_with(
            environ,
            runtime="language-detection",
            image_environment_variable="YAP_LANGUAGE_DETECTION_WORKER_IMAGE",
            checked_head_environment_variable="YAP_CHECKED_HEAD",
            receipt_environment_variable=("YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT"),
            receipt_sha256_environment_variable=(
                "YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256"
            ),
            docker_binary="docker-test",
            repository_root=REPO_ROOT,
            expected_base_digest=self.lock.runtime.platform_digest,
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

            marker.unlink()
            unrelated.rmdir()
            fenced = root / "lid-fenced-request"
            fenced.mkdir()
            identity = fenced / ".yap-container-id"
            identity.write_text("e" * 64, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unexpected artifact"):
                reconcile_stale_lid_requests(root)
            self.assertEqual(
                reconcile_stale_lid_requests(
                    root,
                    retire_container_identities=True,
                    verify_container_absent=lambda _identity: None,
                ),
                1,
            )

            whitespace = root / "lid-whitespace-recovery"
            whitespace.mkdir()
            (whitespace / ".yap-container-id").write_bytes(b" \n")
            with self.assertRaisesRegex(RuntimeError, "identity is invalid"):
                reconcile_stale_lid_requests(
                    root,
                    retire_container_identities=True,
                    verify_container_absent=lambda _identity: None,
                )
            self.assertTrue(whitespace.exists())
            (whitespace / ".yap-container-id").unlink()
            whitespace.rmdir()
            self.assertEqual(list(root.iterdir()), [])

            invalid = root / "lid-invalid-recovery"
            invalid.mkdir()
            (invalid / ".yap-container-id").write_text(
                "not-an-id",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "identity is invalid"):
                reconcile_stale_lid_requests(
                    root,
                    retire_container_identities=True,
                    verify_container_absent=lambda _identity: None,
                )

            (invalid / ".yap-container-id").unlink()
            invalid.rmdir()
            empty = root / "lid-empty-recovery"
            empty.mkdir()
            (empty / ".yap-container-id").write_bytes(b"")
            self.assertEqual(
                reconcile_stale_lid_requests(
                    root,
                    retire_container_identities=True,
                    verify_container_absent=lambda _identity: self.fail(
                        "empty pre-create identity must not be inspected"
                    ),
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
