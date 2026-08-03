from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from yap_server.capabilities import load_asr_capability_catalog
from yap_server.jobs.contract_values import MAX_JOB_PCM_BYTES
from yap_server.jobs.runtime import build_batch_runtime
from yap_server.meeting_transcription.contract import (
    MAX_MEETING_PCM_BYTES,
    MEETING_TRANSCRIPTION_POOL_ID,
)
from yap_server.meeting_transcription.runtime import (
    load_meeting_transcription_runtime_configuration,
)
from yap_server.pools.provider_worker_factory import (
    AsrWorkerPlan,
    build_meeting_transcription_worker_plan,
    resolve_prepared_meeting_transcription_image,
)

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION


SERVER_ROOT = Path(__file__).resolve().parents[2]


class MeetingTranscriptionRuntimeConfigurationTests(unittest.TestCase):
    def test_explicit_candidate_configuration_verifies_both_locked_model_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "tiron"
            speaker_encoder = root / "ecapa"
            model.mkdir()
            speaker_encoder.mkdir()
            with patch(
                "yap_server.meeting_transcription.runtime."
                "verify_repository_source_directory",
                side_effect=lambda _source, path: path.resolve(strict=True),
            ) as verify:
                configuration = load_meeting_transcription_runtime_configuration(
                    {
                        "YAP_TIRON_MODEL_DIR": str(model),
                        "YAP_TIRON_ECAPA_DIR": str(speaker_encoder),
                    },
                    SERVER_ROOT,
                )

        self.assertIsNotNone(configuration)
        assert configuration is not None
        self.assertEqual(configuration.model_dir, model.resolve())
        self.assertEqual(configuration.speaker_encoder_dir, speaker_encoder.resolve())
        self.assertEqual(
            configuration.capability_identity.pool_id, MEETING_TRANSCRIPTION_POOL_ID
        )
        self.assertEqual(configuration.capability_identity.supported_languages, ("en",))
        self.assertEqual(
            [call.args[0] for call in verify.call_args_list],
            [
                configuration.authority.provenance.model,
                configuration.authority.provenance.speaker_encoder,
            ],
        )
        catalog = load_asr_capability_catalog(
            SERVER_ROOT / "tiron-candidate-asr-capabilities.lock.json",
            (configuration.capability_identity,),
        )
        self.assertEqual(
            catalog["providers"][0]["modelRevision"],
            configuration.authority.provenance.model.revision,
        )

    def test_candidate_configuration_requires_both_model_roots(self) -> None:
        cases = (
            {"YAP_TIRON_MODEL_DIR": "tiron-only"},
            {"YAP_TIRON_RUNTIME_LOCK": "runtime-lock-only"},
            {"YAP_TIRON_WORKER_IMAGE": "worker-image-only"},
            {"YAP_TIRON_PREPARATION_RECEIPT": "receipt-only"},
            {"YAP_TIRON_PREPARATION_RECEIPT_SHA256": "f" * 64},
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "YAP_TIRON_MODEL_DIR"):
                    load_meeting_transcription_runtime_configuration(
                        source,
                        SERVER_ROOT,
                    )

    def test_candidate_worker_plan_uses_checked_upstream_runtime_image(self) -> None:
        authority = MagicMock()
        authority.provenance.base_runtime.digest = "sha256:" + "c" * 64
        image_id = "sha256:" + "b" * 64
        with (
            patch(
                "yap_server.pools.provider_worker_factory."
                "resolve_prepared_meeting_transcription_image",
                return_value=image_id,
            ) as resolve_image,
            patch(
                "yap_server.pools.provider_worker_factory.reconcile_owned_containers"
            ) as reconcile,
            patch(
                "yap_server.pools.provider_worker_factory."
                "ContainerMeetingTranscriptionWorker"
            ) as container_worker,
            patch(
                "yap_server.pools.provider_worker_factory."
                "MeetingTranscriptionBatchWorker"
            ) as batch_worker,
        ):
            plan = build_meeting_transcription_worker_plan(
                {
                    "YAP_TIRON_WORKER_IMAGE": "yap-tiron:checked",
                    "YAP_CHECKED_HEAD": "a" * 40,
                },
                model_dir=Path("tiron-model"),
                speaker_encoder_dir=Path("ecapa-model"),
                runtime_lock_path=Path("meeting-runtime.json"),
                authority=authority,
                repository_root=Path("repository"),
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=1000,
                run_as_gid=1001,
                storage_namespace="storage-test",
                timeout_seconds=1800,
            )

        resolve_image.assert_called_once_with(
            {
                "YAP_TIRON_WORKER_IMAGE": "yap-tiron:checked",
                "YAP_CHECKED_HEAD": "a" * 40,
            },
            docker_binary="docker",
            repository_root=Path("repository"),
            expected_base_digest="sha256:" + "c" * 64,
        )
        reconcile.assert_called_once_with(
            "docker",
            storage_namespace="storage-test",
        )
        container_worker.assert_called_once_with(
            image=image_id,
            model_dir=Path("tiron-model"),
            speaker_encoder_dir=Path("ecapa-model"),
            runtime_lock_path=Path("meeting-runtime.json"),
            run_as_uid=1000,
            run_as_gid=1001,
            checked_head="a" * 40,
            storage_namespace="storage-test",
            docker_binary="docker",
            timeout_seconds=1800,
        )
        batch_worker.assert_called_once_with(
            worker=container_worker.return_value,
            authority=authority,
        )
        self.assertIs(plan.worker, batch_worker.return_value)
        self.assertEqual((plan.max_workers, plan.max_queued), (1, 2))

    def test_candidate_worker_rejects_an_image_outside_its_receipt(self) -> None:
        environ = {
            "YAP_TIRON_WORKER_IMAGE": "sha256:" + "b" * 64,
            "YAP_CHECKED_HEAD": "a" * 40,
            "YAP_TIRON_PREPARATION_RECEIPT": str(Path.cwd() / "tiron-receipt.json"),
            "YAP_TIRON_PREPARATION_RECEIPT_SHA256": "e" * 64,
        }
        with patch(
            "yap_server.pools.provider_worker_factory."
            "resolve_receipt_bound_runtime_image",
            side_effect=ValueError("receipt-bound immutable image ID"),
        ) as resolve_image:
            with self.assertRaisesRegex(ValueError, "receipt-bound immutable image ID"):
                resolve_prepared_meeting_transcription_image(
                    environ,
                    docker_binary="docker",
                    repository_root=Path("repository"),
                    expected_base_digest="sha256:" + "c" * 64,
                )
        resolve_image.assert_called_once_with(
            environ,
            runtime="meeting-transcription",
            image_environment_variable="YAP_TIRON_WORKER_IMAGE",
            checked_head_environment_variable="YAP_CHECKED_HEAD",
            receipt_environment_variable="YAP_TIRON_PREPARATION_RECEIPT",
            receipt_sha256_environment_variable=(
                "YAP_TIRON_PREPARATION_RECEIPT_SHA256"
            ),
            docker_binary="docker",
            repository_root=Path("repository"),
            expected_base_digest="sha256:" + "c" * 64,
        )

    def test_batch_runtime_composes_the_candidate_without_a_default_model_pool(
        self,
    ) -> None:
        authority = MagicMock()
        capability_identity = MagicMock(pool_id=MEETING_TRANSCRIPTION_POOL_ID)
        configuration = SimpleNamespace(
            authority=authority,
            capability_identity=capability_identity,
            model_dir=Path("tiron-model"),
            speaker_encoder_dir=Path("ecapa-model"),
            runtime_lock_path=Path("meeting-runtime.json"),
        )
        worker = MagicMock()
        plan = AsrWorkerPlan(
            worker=worker,
            max_workers=1,
            max_queued=2,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
            startup_cleanup_verified=True,
        )
        route_resolver = MagicMock()
        route_resolver.supported_languages = ("en-US",)
        capability_catalog = {
            "catalogRevision": TEST_ASR_CATALOG_REVISION,
            "providers": [
                {
                    "providerId": "tiron",
                    "poolId": MEETING_TRANSCRIPTION_POOL_ID,
                }
            ],
        }
        posix_runtime_os = SimpleNamespace(
            name="posix",
            environ=os.environ,
            fsencode=os.fsencode,
            getuid=lambda: 1000,
            getgid=lambda: 1001,
        )
        service = MagicMock()
        pool = MagicMock()
        lease = MagicMock()
        with (
            patch("yap_server.jobs.runtime.os", posix_runtime_os),
            patch(
                "yap_server.jobs.runtime."
                "load_meeting_transcription_runtime_configuration",
                return_value=configuration,
            ),
            patch(
                "yap_server.jobs.runtime.load_meeting_result_authority",
                return_value=authority,
            ),
            patch(
                "yap_server.jobs.runtime._configured_model_pools",
                return_value=(),
            ) as configured_model_pools,
            patch(
                "yap_server.jobs.runtime.load_asr_capability_catalog",
                return_value=capability_catalog,
            ) as load_catalog,
            patch(
                "yap_server.jobs.runtime._private_storage_directory",
                return_value=Path("private-storage"),
            ),
            patch(
                "yap_server.jobs.runtime.StorageRuntimeLease",
                return_value=lease,
            ),
            patch(
                "yap_server.jobs.runtime.BatchCatalogRouter",
                return_value=route_resolver,
            ),
            patch(
                "yap_server.jobs.runtime.build_meeting_transcription_worker_plan",
                return_value=plan,
            ) as build_plan,
            patch(
                "yap_server.jobs.runtime.BatchAsrPool",
                return_value=pool,
            ),
            patch(
                "yap_server.jobs.runtime.RecordingJobService",
                return_value=service,
            ) as service_type,
            patch(
                "yap_server.jobs.runtime.build_language_detection_runtime",
                return_value=None,
            ),
        ):
            runtime = build_batch_runtime(
                {
                    "YAP_BATCH_ASR_ENABLED": "1",
                    "YAP_BATCH_JOB_STORAGE_DIR": "private-storage",
                },
                server_root=SERVER_ROOT,
                development_principal=None,
            )

        self.assertIsNotNone(runtime)
        configured_model_pools.assert_not_called()
        load_catalog.assert_called_once_with(
            SERVER_ROOT / "tiron-candidate-asr-capabilities.lock.json",
            (capability_identity,),
        )
        build_plan.assert_called_once()
        self.assertIs(build_plan.call_args.kwargs["authority"], authority)
        self.assertEqual(
            build_plan.call_args.kwargs["max_inflight_pcm_bytes"],
            MAX_MEETING_PCM_BYTES,
        )
        self.assertEqual(
            build_plan.call_args.kwargs["repository_root"],
            SERVER_ROOT.parent,
        )
        result_adapter = service_type.call_args.kwargs[
            "result_bundle_adapters"
        ].for_route(SimpleNamespace(pool_id=MEETING_TRANSCRIPTION_POOL_ID))
        self.assertIsNotNone(result_adapter)
        self.assertIs(
            result_adapter.authority,
            authority,
        )
        self.assertEqual(
            service_type.call_args.kwargs["route_pcm_byte_limits"],
            {MEETING_TRANSCRIPTION_POOL_ID: MAX_MEETING_PCM_BYTES},
        )


if __name__ == "__main__":
    unittest.main()
