from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, MagicMock, patch

import yap_server.__main__ as server_main
from yap_server.config import ServerSettings
from yap_server.jobs.runtime import (
    StorageRuntimeLease,
    _build_provider_worker_plans,
    _configured_model_pools,
    build_batch_runtime,
    ensure_development_batch_bind,
)
from yap_server.jobs.contract_values import MAX_JOB_PCM_BYTES
from yap_server.pools.batch_asr import WorkerContainmentError
from yap_server.pools.provider_worker_factory import (
    AsrWorkerPlan,
    build_asr_worker_plan,
    resolve_checked_worker_image,
)

from tests.asr_route_fixtures import TEST_ASR_CATALOG_REVISION
from tests.model_pools.batch_asr_fixtures import test_lock as _test_lock


class _Runtime:
    def __init__(self) -> None:
        self.service = object()
        self.lid_preflight_service = object()
        self.asr_capabilities = {"schemaVersion": 1, "providers": []}
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _ClosableWorker:
    def __init__(self) -> None:
        self.close_calls = 0

    def run(self, _job, _cancellation):
        raise AssertionError("startup cleanup test does not run work")

    def close(self) -> None:
        self.close_calls += 1


class _RetainingTestStorageLease:
    _owned: set[Path] = set()

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root
        self.retained = False
        self.close_calls = 0
        if storage_root in self._owned:
            raise ValueError("private server storage is already owned")
        self._owned.add(storage_root)

    def retain_until_process_exit(self) -> None:
        self.retained = True

    def close(self) -> None:
        self.close_calls += 1
        if not self.retained:
            self._owned.discard(self.storage_root)

    def release_for_test(self) -> None:
        self._owned.discard(self.storage_root)


class BatchRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX storage lease")
    def test_storage_runtime_lease_excludes_a_second_server_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary)
            first = StorageRuntimeLease(storage)
            try:
                with self.assertRaisesRegex(ValueError, "already owned"):
                    StorageRuntimeLease(storage)
            finally:
                first.close()

            replacement = StorageRuntimeLease(storage)
            replacement.close()

    def test_unauthenticated_batch_runtime_is_loopback_only(self) -> None:
        ensure_development_batch_bind("127.0.0.1")
        ensure_development_batch_bind("::1")
        for host in ("localhost", "0.0.0.0", "192.168.50.1", "yap.internal"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(ValueError, "SSH tunnel"):
                    ensure_development_batch_bind(host)

    def test_language_detection_cannot_start_without_the_verified_batch_runtime(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "requires the verified batch"):
            build_batch_runtime(
                {
                    "YAP_BATCH_ASR_ENABLED": "0",
                    "YAP_LANGUAGE_DETECTION_ENABLED": "1",
                }
            )

    def test_runtime_configuration_loads_distinct_model_pools(self) -> None:
        server_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cohere_model = root / "cohere"
            nemotron_model = root / "nemotron"
            cohere_model.mkdir()
            nemotron_model.mkdir()

            configured = _configured_model_pools(
                {
                    "YAP_ASR_MODEL_DIR": str(cohere_model),
                    "YAP_NEMOTRON_MODEL_DIR": str(nemotron_model),
                },
                server_root,
            )

        self.assertEqual(
            [lock.pool_id for lock, _model_dir in configured],
            ["cohere-batch", "nemotron-batch"],
        )

    def test_provider_worker_startup_closes_the_first_worker_if_the_second_fails(
        self,
    ) -> None:
        first_worker = _ClosableWorker()
        first_plan = AsrWorkerPlan(
            worker=first_worker,
            max_workers=1,
            max_queued=2,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
            startup_cleanup_verified=True,
        )
        cohere_lock = _test_lock()
        nemotron_lock = replace(_test_lock(), pool_id="nemotron-batch")
        capabilities = {
            "providers": [
                {"providerId": "cohere", "poolId": "cohere-batch"},
                {"providerId": "nemotron", "poolId": "nemotron-batch"},
            ]
        }

        with patch(
            "yap_server.jobs.runtime.build_asr_worker_plan",
            side_effect=(first_plan, RuntimeError("second provider failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "second provider failed"):
                _build_provider_worker_plans(
                    {},
                    asr_capabilities=capabilities,
                    configured_pools=(
                        (cohere_lock, Path("cohere-model")),
                        (nemotron_lock, Path("nemotron-model")),
                    ),
                    run_as_uid=1000,
                    run_as_gid=1000,
                    storage_namespace="storage-test",
                    timeout_seconds=1800,
                )

        self.assertEqual(first_worker.close_calls, 1)

    def test_runtime_does_not_claim_cleanup_without_every_provider_proof(
        self,
    ) -> None:
        unverified_worker = _ClosableWorker()
        unverified_plan = AsrWorkerPlan(
            worker=unverified_worker,
            max_workers=1,
            max_queued=0,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
            startup_cleanup_verified=False,
        )
        storage_lease = MagicMock()
        route_resolver = MagicMock()
        route_resolver.supported_languages = ("en",)
        posix_runtime_os = SimpleNamespace(
            name="posix",
            environ=os.environ,
            fsencode=os.fsencode,
            getuid=lambda: 1000,
            getgid=lambda: 1000,
        )
        with (
            patch("yap_server.jobs.runtime.os", posix_runtime_os),
            patch(
                "yap_server.jobs.runtime.load_verified_asr_capability_catalog",
                return_value={"catalogRevision": TEST_ASR_CATALOG_REVISION},
            ),
            patch(
                "yap_server.jobs.runtime._configured_model_pools",
                return_value=((_test_lock(), Path("model")),),
            ),
            patch(
                "yap_server.jobs.runtime._private_storage_directory",
                return_value=Path("private-storage"),
            ),
            patch(
                "yap_server.jobs.runtime.StorageRuntimeLease",
                return_value=storage_lease,
            ),
            patch(
                "yap_server.jobs.runtime.BatchCatalogRouter",
                return_value=route_resolver,
            ),
            patch(
                "yap_server.jobs.runtime._build_provider_worker_plans",
                return_value={"cohere": unverified_plan},
            ),
            patch("yap_server.jobs.runtime.RecordingJobService") as service_type,
        ):
            with self.assertRaisesRegex(
                WorkerContainmentError,
                "startup reconciliation",
            ):
                build_batch_runtime(
                    {"YAP_BATCH_ASR_ENABLED": "1"},
                    server_root=Path.cwd(),
                )

        service_type.assert_not_called()
        self.assertEqual(unverified_worker.close_calls, 1)
        storage_lease.retain_until_process_exit.assert_called_once_with()
        storage_lease.close.assert_not_called()

    def test_provider_cleanup_failure_retains_storage_ownership(self) -> None:
        first_worker = MagicMock()
        first_worker.close.side_effect = RuntimeError("worker remained uncontained")
        first_plan = AsrWorkerPlan(
            worker=first_worker,
            max_workers=1,
            max_queued=0,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
            startup_cleanup_verified=True,
        )
        cohere_lock = _test_lock()
        nemotron_lock = replace(_test_lock(), pool_id="nemotron-batch")
        capabilities = {
            "catalogRevision": TEST_ASR_CATALOG_REVISION,
            "providers": [
                {"providerId": "cohere", "poolId": "cohere-batch"},
                {"providerId": "nemotron", "poolId": "nemotron-batch"},
            ],
        }
        storage_root = Path("private-storage-provider-cleanup")
        storage_lease = _RetainingTestStorageLease(storage_root)
        route_resolver = MagicMock()
        posix_runtime_os = SimpleNamespace(
            name="posix",
            environ=os.environ,
            fsencode=os.fsencode,
            getuid=lambda: 1000,
            getgid=lambda: 1000,
        )
        with (
            patch("yap_server.jobs.runtime.os", posix_runtime_os),
            patch(
                "yap_server.jobs.runtime.load_verified_asr_capability_catalog",
                return_value=capabilities,
            ),
            patch(
                "yap_server.jobs.runtime._configured_model_pools",
                return_value=(
                    (cohere_lock, Path("cohere-model")),
                    (nemotron_lock, Path("nemotron-model")),
                ),
            ),
            patch(
                "yap_server.jobs.runtime._private_storage_directory",
                return_value=storage_root,
            ),
            patch(
                "yap_server.jobs.runtime.StorageRuntimeLease",
                return_value=storage_lease,
            ),
            patch(
                "yap_server.jobs.runtime.BatchCatalogRouter",
                return_value=route_resolver,
            ),
            patch(
                "yap_server.jobs.runtime.build_asr_worker_plan",
                side_effect=(first_plan, RuntimeError("second provider failed")),
            ),
        ):
            try:
                with self.assertRaisesRegex(
                    WorkerContainmentError,
                    "provider worker startup cleanup could not be verified",
                ):
                    build_batch_runtime(
                        {"YAP_BATCH_ASR_ENABLED": "1"},
                        server_root=Path.cwd(),
                    )

                first_worker.close.assert_called_once_with()
                self.assertTrue(storage_lease.retained)
                self.assertEqual(storage_lease.close_calls, 0)
                with self.assertRaisesRegex(ValueError, "already owned"):
                    _RetainingTestStorageLease(storage_root)
            finally:
                storage_lease.release_for_test()

    def test_startup_containment_failure_retires_service_and_retains_storage(
        self,
    ) -> None:
        worker = _ClosableWorker()
        worker_plan = AsrWorkerPlan(
            worker=worker,
            max_workers=1,
            max_queued=0,
            max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
            startup_cleanup_verified=True,
        )
        storage_root = Path("private-storage")
        storage_lease = _RetainingTestStorageLease(storage_root)
        pool = MagicMock()
        pool.shutdown.side_effect = WorkerContainmentError(
            "synthetic startup cleanup failure"
        )
        service = MagicMock()
        route_resolver = MagicMock()
        route_resolver.supported_languages = ("en",)
        posix_runtime_os = SimpleNamespace(
            name="posix",
            environ=os.environ,
            fsencode=os.fsencode,
            getuid=lambda: 1000,
            getgid=lambda: 1000,
        )
        with (
            patch("yap_server.jobs.runtime.os", posix_runtime_os),
            patch(
                "yap_server.jobs.runtime.load_verified_asr_capability_catalog",
                return_value={"catalogRevision": TEST_ASR_CATALOG_REVISION},
            ),
            patch(
                "yap_server.jobs.runtime._configured_model_pools",
                return_value=((_test_lock(), Path("model")),),
            ),
            patch(
                "yap_server.jobs.runtime._private_storage_directory",
                return_value=storage_root,
            ),
            patch(
                "yap_server.jobs.runtime.StorageRuntimeLease",
                return_value=storage_lease,
            ),
            patch(
                "yap_server.jobs.runtime.BatchCatalogRouter",
                return_value=route_resolver,
            ),
            patch(
                "yap_server.jobs.runtime._build_provider_worker_plans",
                return_value={"cohere": worker_plan},
            ),
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
                side_effect=RuntimeError("later startup step failed"),
            ),
        ):
            try:
                with self.assertRaisesRegex(
                    WorkerContainmentError,
                    "startup cleanup could not be verified",
                ):
                    build_batch_runtime(
                        {"YAP_BATCH_ASR_ENABLED": "1"},
                        server_root=Path.cwd(),
                    )

                service.begin_runtime_shutdown.assert_called_once_with()
                self.assertIs(service_type.call_args.kwargs["processor"], pool)
                pool.shutdown.assert_called_once_with()
                self.assertTrue(storage_lease.retained)
                self.assertEqual(storage_lease.close_calls, 0)
                with self.assertRaisesRegex(ValueError, "already owned"):
                    _RetainingTestStorageLease(storage_root)
            finally:
                storage_lease.release_for_test()

    def test_runtime_rejects_orphaned_nemotron_lock(self) -> None:
        with self.assertRaisesRegex(ValueError, "NEMOTRON_MODEL_DIR"):
            _configured_model_pools(
                {
                    "YAP_ASR_MODEL_DIR": str(Path.cwd()),
                    "YAP_NEMOTRON_MODEL_LOCK": str(
                        Path(__file__).resolve().parents[2]
                        / "nemotron-model-pool.lock.json"
                    ),
                },
                Path(__file__).resolve().parents[2],
            )

    def test_transient_runtime_uses_the_inspected_checked_head_worker_image(
        self,
    ) -> None:
        checked_head = "a" * 40
        image_id = "sha256:" + "b" * 64
        environ = {
            "YAP_ASR_WORKER_IMAGE": f"yap-batch-asr:checked-{checked_head}",
            "YAP_CHECKED_HEAD": checked_head,
        }

        with patch(
            "yap_server.pools.provider_worker_factory.inspect_worker_image",
            return_value={"id": image_id},
        ) as inspect:
            resolved = resolve_checked_worker_image(
                environ,
                docker_binary="docker-test",
            )

        self.assertEqual(resolved, image_id)
        inspect.assert_called_once_with(
            environ["YAP_ASR_WORKER_IMAGE"],
            checked_head,
            docker_binary="docker-test",
        )

    def test_transient_runtime_requires_image_and_checked_head(self) -> None:
        for environ in (
            {},
            {"YAP_ASR_WORKER_IMAGE": "yap-asr:test"},
            {
                "YAP_ASR_WORKER_IMAGE": "yap-asr:test",
                "YAP_CHECKED_HEAD": "not-a-commit",
            },
        ):
            with self.subTest(environ=environ):
                with self.assertRaises(ValueError):
                    resolve_checked_worker_image(environ, docker_binary="docker")

    def test_cohere_vllm_plan_verifies_artifacts_and_readiness_before_capacity(
        self,
    ) -> None:
        lock = replace(
            _test_lock(),
            engine="vllm",
            runtime_overlay_packages=(("vllm", "0.22.1+test"),),
        )
        endpoint = "http://127.0.0.1:8000"
        with (
            patch(
                "yap_server.pools.provider_worker_factory.verify_model_artifacts"
            ) as verify_artifacts,
            patch(
                "yap_server.pools.provider_worker_factory.VllmTranscriptionClient"
            ) as client_type,
            patch(
                "yap_server.pools.provider_worker_factory.CohereVllmBatchWorker"
            ) as worker_type,
        ):
            plan = build_asr_worker_plan(
                {
                    "YAP_COHERE_ASR_RUNTIME": "vllm",
                    "YAP_COHERE_VLLM_ENDPOINT": endpoint,
                    "YAP_COHERE_VLLM_API_KEY": "private-test-key",
                },
                model_dir=Path("model"),
                lock=lock,
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=1000,
                run_as_gid=1000,
                storage_namespace="storage-test",
                timeout_seconds=1800,
            )

        verify_artifacts.assert_called_once_with(lock, Path("model"))
        client_type.assert_called_once_with(
            endpoint=endpoint,
            api_key="private-test-key",
            timeout_seconds=1800,
        )
        worker_type.assert_called_once_with(
            lock=lock,
            client=client_type.return_value,
        )
        worker_type.return_value.verify_ready.assert_called_once_with()
        worker_type.return_value.verify_startup_idle.assert_called_once_with()
        self.assertTrue(plan.startup_cleanup_verified)
        self.assertIs(plan.worker, worker_type.return_value)
        self.assertEqual(plan.max_workers, 8)
        self.assertEqual(plan.max_queued, 8)
        self.assertEqual(plan.max_inflight_pcm_bytes, MAX_JOB_PCM_BYTES)

    def test_nemotron_keeps_the_transformers_reference_worker(self) -> None:
        lock = replace(_test_lock(), pool_id="nemotron-batch")
        image_id = "sha256:" + "e" * 64
        with (
            patch(
                "yap_server.pools.provider_worker_factory.resolve_checked_worker_image",
                return_value=image_id,
            ),
            patch(
                "yap_server.pools.provider_worker_factory.reconcile_owned_containers"
            ) as reconcile,
            patch(
                "yap_server.pools.provider_worker_factory.ContainerBatchAsrWorker"
            ) as worker_type,
        ):
            plan = build_asr_worker_plan(
                {
                    "YAP_NEMOTRON_ASR_RUNTIME": "transformers-reference",
                    "YAP_CHECKED_HEAD": "a" * 40,
                },
                model_dir=Path("model"),
                lock=lock,
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=1000,
                run_as_gid=1000,
                storage_namespace="storage-test",
                timeout_seconds=1800,
            )

        worker_type.assert_called_once_with(
            image=image_id,
            model_dir=Path("model"),
            lock=lock,
            run_as_uid=1000,
            run_as_gid=1000,
            checked_head="a" * 40,
            storage_namespace="storage-test",
            docker_binary="docker",
            timeout_seconds=1800,
        )
        reconcile.assert_called_once_with(
            "docker",
            storage_namespace="storage-test",
        )
        self.assertIs(plan.worker, worker_type.return_value)
        self.assertEqual(plan.max_workers, 1)
        self.assertEqual(plan.max_queued, 2)

    def test_nemotron_nemo_reference_uses_its_dedicated_checked_image(self) -> None:
        lock = replace(
            _test_lock(),
            pool_id="nemotron-batch",
            engine="nemo",
        )
        image_id = "sha256:" + "f" * 64
        source = {
            "YAP_NEMOTRON_ASR_RUNTIME": "nemo-reference",
            "YAP_NEMOTRON_WORKER_IMAGE": "yap-nemotron-nemo:checked",
            "YAP_CHECKED_HEAD": "a" * 40,
        }
        with (
            patch(
                "yap_server.pools.provider_worker_factory.resolve_checked_worker_image",
                return_value=image_id,
            ) as resolve_image,
            patch(
                "yap_server.pools.provider_worker_factory.reconcile_owned_containers"
            ),
            patch(
                "yap_server.pools.provider_worker_factory.ContainerBatchAsrWorker"
            ) as worker_type,
        ):
            plan = build_asr_worker_plan(
                source,
                model_dir=Path("native-model"),
                lock=lock,
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=1000,
                run_as_gid=1000,
                storage_namespace="storage-test",
                timeout_seconds=1800,
            )

        resolve_image.assert_called_once_with(
            source,
            docker_binary="docker",
            image_env="YAP_NEMOTRON_WORKER_IMAGE",
        )
        worker_type.assert_called_once_with(
            image=image_id,
            model_dir=Path("native-model"),
            lock=lock,
            run_as_uid=1000,
            run_as_gid=1000,
            checked_head="a" * 40,
            storage_namespace="storage-test",
            docker_binary="docker",
            timeout_seconds=1800,
        )
        self.assertIs(plan.worker, worker_type.return_value)
        self.assertEqual(plan.max_workers, 1)
        self.assertEqual(plan.max_queued, 2)

    def test_nemotron_resident_plan_verifies_artifacts_and_readiness(self) -> None:
        lock = replace(
            _test_lock(),
            pool_id="nemotron-batch",
            engine="nemo",
            runtime_overlay_packages=(("nemo_toolkit", "3.1.0+test"),),
        )
        endpoint = "http://127.0.0.1:18001"
        with (
            patch(
                "yap_server.pools.provider_worker_factory.verify_model_artifacts"
            ) as verify_artifacts,
            patch(
                "yap_server.pools.provider_worker_factory.NemotronNemoClient"
            ) as client_type,
            patch(
                "yap_server.pools.provider_worker_factory.NemotronNemoBatchWorker"
            ) as worker_type,
        ):
            plan = build_asr_worker_plan(
                {
                    "YAP_NEMOTRON_ASR_RUNTIME": "nemo-resident",
                    "YAP_NEMOTRON_NEMO_ENDPOINT": endpoint,
                    "YAP_NEMOTRON_NEMO_API_KEY": "private-test-key",
                },
                model_dir=Path("native-model"),
                lock=lock,
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=1000,
                run_as_gid=1000,
                storage_namespace="storage-test",
                timeout_seconds=1800,
            )

        verify_artifacts.assert_called_once_with(lock, Path("native-model"))
        client_type.assert_called_once_with(
            endpoint=endpoint,
            api_key="private-test-key",
            timeout_seconds=1800,
        )
        worker_type.assert_called_once_with(
            lock=lock,
            client=client_type.return_value,
        )
        worker_type.return_value.verify_ready.assert_called_once_with()
        worker_type.return_value.verify_startup_idle.assert_called_once_with()
        self.assertTrue(plan.startup_cleanup_verified)
        self.assertIs(plan.worker, worker_type.return_value)
        self.assertEqual(plan.max_workers, 8)
        self.assertEqual(plan.max_queued, 8)
        self.assertEqual(plan.max_inflight_pcm_bytes, MAX_JOB_PCM_BYTES)

    def test_runtime_and_model_lock_engines_must_agree(self) -> None:
        cases = (
            (
                "cohere vLLM with Transformers lock",
                _test_lock(),
                {"YAP_COHERE_ASR_RUNTIME": "vllm"},
            ),
            (
                "Nemotron NeMo with Transformers lock",
                replace(_test_lock(), pool_id="nemotron-batch"),
                {"YAP_NEMOTRON_ASR_RUNTIME": "nemo-reference"},
            ),
            (
                "Nemotron resident NeMo with Transformers lock",
                replace(_test_lock(), pool_id="nemotron-batch"),
                {"YAP_NEMOTRON_ASR_RUNTIME": "nemo-resident"},
            ),
            (
                "Nemotron Transformers with NeMo lock",
                replace(
                    _test_lock(),
                    pool_id="nemotron-batch",
                    engine="nemo",
                ),
                {"YAP_NEMOTRON_ASR_RUNTIME": "transformers-reference"},
            ),
        )
        for label, lock, source in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "model lock selects"):
                    build_asr_worker_plan(
                        source,
                        model_dir=Path("model"),
                        lock=lock,
                        max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                        run_as_uid=1000,
                        run_as_gid=1000,
                        storage_namespace="storage-test",
                        timeout_seconds=1800,
                    )

    def test_nemotron_cannot_be_silently_sent_to_vllm(self) -> None:
        lock = replace(_test_lock(), pool_id="nemotron-batch")
        with self.assertRaisesRegex(ValueError, "NEMOTRON_ASR_RUNTIME"):
            build_asr_worker_plan(
                {"YAP_NEMOTRON_ASR_RUNTIME": "vllm"},
                model_dir=Path("model"),
                lock=lock,
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=1000,
                run_as_gid=1000,
                storage_namespace="storage-test",
                timeout_seconds=1800,
            )


class ServerMainTests(unittest.TestCase):
    def test_normal_pool_shutdown_fail_stops_before_executor_atexit_join(
        self,
    ) -> None:
        server_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(server_root / "src")
        script = textwrap.dedent(
            """
            import threading
            from unittest.mock import patch

            import yap_server.__main__ as server_main
            import yap_server.pools.batch_pool as batch_pool
            from yap_server.config import ServerSettings
            from yap_server.pools.batch_asr import BatchAsrPool
            from tests.asr_route_fixtures import (
                TEST_ASR_CATALOG_REVISION,
                test_asr_route,
            )


            class Worker:
                def run(self, _job, _cancellation):
                    raise AssertionError("wedged preparation never reaches the worker")

                def close(self):
                    pass


            pool = BatchAsrPool(
                Worker(),
                route_resolver=test_asr_route,
                asr_catalog_revision=TEST_ASR_CATALOG_REVISION,
                max_workers=1,
                max_queued=0,
            )
            started = threading.Event()
            release = threading.Event()


            def wedge_preparation(_cancellation):
                started.set()
                release.wait()
                raise AssertionError("synthetic preparation unexpectedly resumed")


            pool.reserve("job-wedged").start(wedge_preparation)
            if not started.wait(timeout=1):
                raise RuntimeError("synthetic preparation did not start")


            class Runtime:
                service = object()
                lid_preflight_service = object()
                asr_capabilities = {"schemaVersion": 1, "providers": []}

                def close(self):
                    pool.shutdown()


            with (
                patch.object(batch_pool, "_EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS", 0.05, create=True),
                patch.object(server_main, "_RUNTIME_CLEANUP_TIMEOUT_SECONDS", 0.5, create=True),
                patch.object(server_main.signal, "signal"),
                patch.object(
                    server_main.ServerSettings,
                    "from_env",
                    return_value=ServerSettings(),
                ),
                patch.object(server_main, "build_batch_runtime", return_value=Runtime()),
                patch.object(server_main, "serve", side_effect=KeyboardInterrupt),
            ):
                server_main.main()
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=server_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

        self.assertEqual(completed.returncode, 70)
        self.assertIn("fail-stopping the service process", completed.stderr)
        self.assertNotIn("synthetic preparation", completed.stderr)

    def test_cleanup_containment_failure_hard_exits_before_executor_atexit_join(
        self,
    ) -> None:
        server_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(server_root / "src")
        script = textwrap.dedent(
            """
            import threading
            from concurrent.futures import ThreadPoolExecutor
            from unittest.mock import patch

            import yap_server.__main__ as server_main
            from yap_server.config import ServerSettings
            from yap_server.pools.batch_contract import WorkerContainmentError


            class Runtime:
                def __init__(self):
                    self.service = object()
                    self.lid_preflight_service = object()
                    self.asr_capabilities = {"schemaVersion": 1, "providers": []}
                    self._started = threading.Event()
                    self._release = threading.Event()
                    self._executor = ThreadPoolExecutor(max_workers=1)
                    self._executor.submit(self._block)
                    if not self._started.wait(timeout=1):
                        raise RuntimeError("synthetic worker did not start")

                def _block(self):
                    self._started.set()
                    self._release.wait()

                def close(self):
                    self._executor.shutdown(wait=False, cancel_futures=True)
                    raise WorkerContainmentError("sensitive worker detail")


            runtime = Runtime()
            with (
                patch.object(server_main.signal, "signal"),
                patch.object(
                    server_main.ServerSettings,
                    "from_env",
                    return_value=ServerSettings(),
                ),
                patch.object(
                    server_main,
                    "build_batch_runtime",
                    return_value=runtime,
                ),
                patch.object(server_main, "serve", side_effect=KeyboardInterrupt),
            ):
                server_main.main()
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=server_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

        self.assertEqual(completed.returncode, 70)
        self.assertIn("fail-stopping the service process", completed.stderr)
        self.assertNotIn("sensitive worker detail", completed.stderr)

    def test_verified_runtime_capabilities_are_served_with_the_job_service(
        self,
    ) -> None:
        runtime = _Runtime()
        settings = ServerSettings()
        with (
            patch.object(server_main.signal, "signal"),
            patch.object(
                server_main.ServerSettings,
                "from_env",
                return_value=settings,
            ),
            patch.object(
                server_main,
                "build_batch_runtime",
                return_value=runtime,
            ),
            patch.object(server_main, "serve", side_effect=KeyboardInterrupt) as serve,
        ):
            server_main.main()

        serve.assert_called_once_with(
            settings,
            request_authenticator=ANY,
            job_service=runtime.service,
            lid_preflight_service=runtime.lid_preflight_service,
            asr_capabilities=runtime.asr_capabilities,
        )
        self.assertTrue(runtime.closed)

    def test_linux_termination_uses_the_graceful_runtime_cleanup_path(self) -> None:
        with (
            patch.object(server_main.signal, "signal") as install_signal,
            patch.object(
                server_main.ServerSettings,
                "from_env",
                return_value=ServerSettings(),
            ),
            patch.object(server_main, "build_batch_runtime", return_value=None),
            patch.object(server_main, "serve", side_effect=KeyboardInterrupt),
        ):
            server_main.main()

        install_signal.assert_any_call(
            server_main.signal.SIGTERM,
            server_main._raise_keyboard_interrupt,
        )

    def test_startup_storage_failure_does_not_expose_private_paths(self) -> None:
        private_path = "C:/private/recordings/patient-audio.wav"
        with (
            patch.object(server_main.signal, "signal"),
            patch.object(
                server_main.ServerSettings,
                "from_env",
                return_value=ServerSettings(),
            ),
            patch.object(
                server_main,
                "build_batch_runtime",
                side_effect=OSError(private_path),
            ),
        ):
            with self.assertRaises(SystemExit) as stopped:
                server_main.main()

        self.assertEqual(str(stopped.exception), "Yap private server startup failed.")
        self.assertNotIn(private_path, str(stopped.exception))
        self.assertIsNone(stopped.exception.__cause__)
        self.assertTrue(stopped.exception.__suppress_context__)

    def test_build_time_containment_failure_hard_exits_before_executor_atexit_join(
        self,
    ) -> None:
        server_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(server_root / "src")
        script = textwrap.dedent(
            """
            import threading
            from concurrent.futures import ThreadPoolExecutor
            from unittest.mock import patch

            import yap_server.__main__ as server_main
            from yap_server.config import ServerSettings
            from yap_server.pools.batch_contract import WorkerContainmentError


            def fail_during_build(**_options):
                started = threading.Event()
                release = threading.Event()
                executor = ThreadPoolExecutor(max_workers=1)
                executor.submit(lambda: (started.set(), release.wait()))
                if not started.wait(timeout=1):
                    raise RuntimeError("synthetic worker did not start")
                executor.shutdown(wait=False, cancel_futures=True)
                raise WorkerContainmentError("private container detail")


            with (
                patch.object(server_main.signal, "signal"),
                patch.object(
                    server_main.ServerSettings,
                    "from_env",
                    return_value=ServerSettings(),
                ),
                patch.object(
                    server_main,
                    "build_batch_runtime",
                    side_effect=fail_during_build,
                ),
            ):
                server_main.main()
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=server_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

        self.assertEqual(completed.returncode, 70)
        self.assertIn("fail-stopping the service process", completed.stderr)
        self.assertNotIn("private container detail", completed.stderr)

    def test_serving_storage_failure_does_not_expose_private_paths(self) -> None:
        private_path = "/srv/yap/private/patient-audio.wav"
        with (
            patch.object(server_main.signal, "signal"),
            patch.object(
                server_main.ServerSettings,
                "from_env",
                return_value=ServerSettings(),
            ),
            patch.object(server_main, "build_batch_runtime", return_value=None),
            patch.object(server_main, "serve", side_effect=OSError(private_path)),
        ):
            with self.assertRaises(SystemExit) as stopped:
                server_main.main()

        self.assertEqual(
            str(stopped.exception),
            "Yap private server runtime became unavailable.",
        )
        self.assertNotIn(private_path, str(stopped.exception))
        self.assertIsNone(stopped.exception.__cause__)
        self.assertTrue(stopped.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
