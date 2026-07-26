from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from ipaddress import ip_address
import os
from pathlib import Path
import stat
from typing import Mapping, Sequence

from yap_server.capabilities import load_verified_asr_capability_catalog
from yap_server.config.runtime_environment import (
    ASR_MODEL_DIR_ENV,
    ASR_MODEL_LOCK_ENV,
    ASR_WORKER_TIMEOUT_SECONDS_ENV,
    BATCH_ASR_ENABLED_ENV,
    BATCH_JOB_STORAGE_DIR_ENV,
    NEMOTRON_MODEL_DIR_ENV,
    NEMOTRON_MODEL_LOCK_ENV,
)
from yap_server.jobs.service import RecordingJobService
from yap_server.lid.runtime import (
    LANGUAGE_DETECTION_ENABLED_ENV,
    LanguageDetectionRuntime,
    build_language_detection_runtime,
    publish_language_detection_capabilities,
)
from yap_server.lid.service import LidPreflightService
from yap_server.pools.batch_asr import BatchAsrPool, ProviderBatchWorkerRegistry
from yap_server.pools.batch_contract import (
    BatchWorker,
    WorkerContainmentError,
    validate_asr_catalog_revision,
)
from yap_server.pools.catalog_routing import BatchCatalogRouter
from yap_server.pools.model_lock import ModelPoolLock, load_model_pool_lock
from yap_server.pools.provider_worker_factory import (
    AsrWorkerPlan,
    build_asr_worker_plan,
)
from .contract_values import MAX_JOB_PCM_BYTES


@dataclass(slots=True)
class BatchRuntime:
    service: RecordingJobService
    pool: BatchAsrPool
    storage_lease: StorageRuntimeLease
    asr_capabilities: dict[str, object]
    language_detection_runtime: LanguageDetectionRuntime | None
    _cleanup_failed: bool = field(default=False, init=False, repr=False)

    @property
    def lid_preflight_service(self) -> LidPreflightService | None:
        runtime = self.language_detection_runtime
        return runtime.service if runtime is not None else None

    def close(self) -> None:
        if self._cleanup_failed:
            raise WorkerContainmentError(
                "batch runtime cleanup previously failed; process restart is required"
            )
        self.service.begin_runtime_shutdown()
        cleanup_error: BaseException | None = None
        for cleanup in (
            self.language_detection_runtime.close
            if self.language_detection_runtime is not None
            else None,
            self.pool.shutdown,
        ):
            if cleanup is None:
                continue
            try:
                cleanup()
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None:
            # A worker or callback can still be live. This process must retain
            # the exclusive namespace until fail-stop exit.
            self.storage_lease.retain_until_process_exit()
            self._cleanup_failed = True
            raise cleanup_error
        try:
            self.storage_lease.close()
        except BaseException:
            self._cleanup_failed = True
            raise


class StorageRuntimeLease:
    """Exclusive process lease for one private server storage namespace."""

    def __init__(self, storage_dir: Path) -> None:
        import fcntl

        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(storage_dir / ".yap-runtime.lock", flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise ValueError("private server runtime lock is unsafe")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError(
                    "private server storage is already owned by another runtime"
                ) from error
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor: int | None = descriptor
        self._retained_for_fail_stop = False

    def retain_until_process_exit(self) -> None:
        if self._retained_for_fail_stop:
            return
        self._retained_for_fail_stop = True
        _FAIL_STOP_STORAGE_LEASES.append(self)

    def close(self) -> None:
        if self._retained_for_fail_stop:
            return
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


# Fatal cleanup keeps the raw lock descriptor reachable until the process exits.
_FAIL_STOP_STORAGE_LEASES: list[StorageRuntimeLease] = []


def build_batch_runtime(
    environ: Mapping[str, str] | None = None,
    *,
    server_root: Path | None = None,
) -> BatchRuntime | None:
    source = os.environ if environ is None else environ
    enabled = source.get(BATCH_ASR_ENABLED_ENV, "0")
    if enabled == "0":
        lid_enabled = source.get(LANGUAGE_DETECTION_ENABLED_ENV, "0")
        if lid_enabled == "1":
            raise ValueError("language detection requires the verified batch ASR runtime")
        if lid_enabled != "0":
            raise ValueError(f"{LANGUAGE_DETECTION_ENABLED_ENV} must be 0 or 1")
        return None
    if enabled != "1":
        raise ValueError(f"{BATCH_ASR_ENABLED_ENV} must be 0 or 1")
    if os.name != "posix" or not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        raise ValueError("the GPU batch runtime requires the Linux server node")
    run_as_uid = os.getuid()
    run_as_gid = os.getgid()
    if run_as_uid < 1 or run_as_gid < 1:
        raise ValueError("the batch server process must run as a non-root account")

    root = (
        server_root.resolve()
        if server_root is not None
        else Path(__file__).resolve().parents[3]
    )
    capability_lock_path = Path(
        source.get(
            "YAP_ASR_CAPABILITY_LOCK",
            str(root / "asr-capabilities.lock.json"),
        )
    )
    configured_pools = _configured_model_pools(source, root)
    storage_dir = _private_storage_directory(source, BATCH_JOB_STORAGE_DIR_ENV)
    storage_namespace = "storage-" + hashlib.sha256(
        os.fsencode(storage_dir)
    ).hexdigest()[:24]
    timeout_seconds = _positive_float(
        source.get(ASR_WORKER_TIMEOUT_SECONDS_ENV, "1800"),
        ASR_WORKER_TIMEOUT_SECONDS_ENV,
    )
    asr_capabilities = load_verified_asr_capability_catalog(
        capability_lock_path,
        configured_pools,
    )
    route_resolver = BatchCatalogRouter(asr_capabilities)
    catalog_revision = asr_capabilities.get("catalogRevision")
    if not isinstance(catalog_revision, str):
        raise ValueError("verified ASR capabilities omitted the catalog revision")
    validate_asr_catalog_revision(catalog_revision)
    storage_lease = StorageRuntimeLease(storage_dir)
    pool: BatchAsrPool | None = None
    service: RecordingJobService | None = None
    language_detection_runtime: LanguageDetectionRuntime | None = None
    unowned_workers: list[BatchWorker] = []
    try:
        worker_plans = _build_provider_worker_plans(
            source,
            asr_capabilities=asr_capabilities,
            configured_pools=configured_pools,
            run_as_uid=run_as_uid,
            run_as_gid=run_as_gid,
            storage_namespace=storage_namespace,
            timeout_seconds=timeout_seconds,
        )
        unowned_workers.extend(plan.worker for plan in worker_plans.values())
        startup_cleanup_verified = bool(worker_plans) and all(
            plan.startup_cleanup_verified for plan in worker_plans.values()
        )
        if not startup_cleanup_verified:
            raise WorkerContainmentError(
                "provider startup reconciliation could not verify cleanup"
            )
        worker_registry = ProviderBatchWorkerRegistry(
            {
                provider_id: plan.worker
                for provider_id, plan in worker_plans.items()
            }
        )
        max_workers = min(plan.max_workers for plan in worker_plans.values())
        max_queued = min(plan.max_queued for plan in worker_plans.values())
        max_inflight_pcm_bytes = min(
            plan.max_inflight_pcm_bytes for plan in worker_plans.values()
        )
        pool = BatchAsrPool(
            worker_registry,
            route_resolver=route_resolver,
            asr_catalog_revision=catalog_revision,
            max_workers=max_workers,
            max_queued=max_queued,
            max_inflight_pcm_bytes=max_inflight_pcm_bytes,
        )
        unowned_workers.clear()
        service = RecordingJobService(
            storage_dir,
            processor=pool,
            supported_languages=route_resolver.supported_languages,
            now=_utc_now,
            startup_worker_cleanup_verified=startup_cleanup_verified,
        )
        language_detection_runtime = build_language_detection_runtime(
            source,
            repository_root=root.parent,
            storage_dir=storage_dir,
            asr_capabilities=asr_capabilities,
            run_as_uid=run_as_uid,
            run_as_gid=run_as_gid,
            storage_namespace=storage_namespace,
        )
        if language_detection_runtime is not None:
            asr_capabilities = publish_language_detection_capabilities(
                asr_capabilities,
                language_detection_runtime,
            )
        return BatchRuntime(
            service=service,
            pool=pool,
            storage_lease=storage_lease,
            asr_capabilities=asr_capabilities,
            language_detection_runtime=language_detection_runtime,
        )
    except BaseException as startup_error:
        cleanup_error: BaseException | None = None
        for cleanup in (
            service.begin_runtime_shutdown if service is not None else None,
            language_detection_runtime.close
            if language_detection_runtime is not None
            else None,
            pool.shutdown if pool is not None else None,
            (lambda: _close_unowned_workers(unowned_workers))
            if pool is None and unowned_workers
            else None,
        ):
            if cleanup is None:
                continue
            try:
                cleanup()
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None:
            storage_lease.retain_until_process_exit()
            raise WorkerContainmentError(
                "batch runtime startup cleanup could not be verified"
            ) from cleanup_error
        if isinstance(startup_error, WorkerContainmentError):
            storage_lease.retain_until_process_exit()
            raise
        try:
            storage_lease.close()
        except BaseException as cleanup_error:
            raise WorkerContainmentError(
                "batch runtime startup cleanup could not release storage ownership"
            ) from cleanup_error
        raise


def _build_provider_worker_plans(
    source: Mapping[str, str],
    *,
    asr_capabilities: Mapping[str, object],
    configured_pools: Sequence[tuple[ModelPoolLock, Path]],
    run_as_uid: int,
    run_as_gid: int,
    storage_namespace: str,
    timeout_seconds: float,
) -> dict[str, AsrWorkerPlan]:
    plans: dict[str, AsrWorkerPlan] = {}
    try:
        for lock, model_dir in configured_pools:
            provider_id = _provider_id_for_pool(asr_capabilities, lock.pool_id)
            if provider_id in plans:
                raise ValueError("verified ASR capabilities reuse a provider ID")
            plans[provider_id] = build_asr_worker_plan(
                source,
                model_dir=model_dir,
                lock=lock,
                max_inflight_pcm_bytes=MAX_JOB_PCM_BYTES,
                run_as_uid=run_as_uid,
                run_as_gid=run_as_gid,
                storage_namespace=storage_namespace,
                timeout_seconds=timeout_seconds,
            )
        return plans
    except BaseException:
        try:
            _close_unowned_workers([plan.worker for plan in plans.values()])
        except BaseException as cleanup_error:
            raise WorkerContainmentError(
                "provider worker startup cleanup could not be verified"
            ) from cleanup_error
        raise


def _close_unowned_workers(workers: Sequence[BatchWorker]) -> None:
    first_error: BaseException | None = None
    closed: set[int] = set()
    for worker in reversed(workers):
        identity = id(worker)
        if identity in closed:
            continue
        closed.add(identity)
        close_worker = getattr(worker, "close", None)
        if not callable(close_worker):
            continue
        try:
            close_worker()
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def ensure_development_batch_bind(host: str) -> None:
    try:
        if ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(
        "unauthenticated batch audio is development-only and must bind to loopback; "
        "use an SSH tunnel until authentication and certificate policy ship"
    )


def _provider_id_for_pool(catalog: Mapping[str, object], pool_id: str) -> str:
    providers = catalog.get("providers")
    if not isinstance(providers, list):
        raise ValueError("verified ASR capabilities omitted providers")
    matches = [
        provider
        for provider in providers
        if isinstance(provider, dict) and provider.get("poolId") == pool_id
    ]
    if len(matches) != 1:
        raise ValueError("verified ASR capabilities do not identify one pool provider")
    provider_id = matches[0].get("providerId")
    if not isinstance(provider_id, str):
        raise ValueError("verified ASR capabilities contain an invalid provider ID")
    return provider_id


def _configured_model_pools(
    source: Mapping[str, str],
    root: Path,
) -> tuple[tuple[ModelPoolLock, Path], ...]:
    primary_lock_path = Path(
        source.get(ASR_MODEL_LOCK_ENV, str(root / "model-pools.lock.json"))
    ).resolve(strict=True)
    configured = [
        (
            load_model_pool_lock(primary_lock_path),
            _required_existing_directory(source, ASR_MODEL_DIR_ENV),
        )
    ]

    nemotron_model_dir = source.get(NEMOTRON_MODEL_DIR_ENV, "").strip()
    nemotron_lock_value = source.get(NEMOTRON_MODEL_LOCK_ENV, "").strip()
    if nemotron_lock_value and not nemotron_model_dir:
        raise ValueError(
            f"{NEMOTRON_MODEL_DIR_ENV} is required when "
            f"{NEMOTRON_MODEL_LOCK_ENV} is set"
        )
    if nemotron_model_dir:
        lock_path = Path(
            nemotron_lock_value or root / "nemotron-model-pool.lock.json"
        ).resolve(strict=True)
        lock = load_model_pool_lock(lock_path)
        if lock.pool_id != "nemotron-batch":
            raise ValueError("Nemotron configuration uses the wrong model-pool lock")
        configured.append(
            (
                lock,
                _required_existing_directory(source, NEMOTRON_MODEL_DIR_ENV),
            )
        )
    pool_ids = [lock.pool_id for lock, _model_dir in configured]
    if len(pool_ids) != len(set(pool_ids)):
        raise ValueError("configured ASR model pool IDs must be unique")
    return tuple(configured)


def _required_existing_directory(
    environ: Mapping[str, str],
    name: str,
) -> Path:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required when the batch runtime is enabled")
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"{name} must be a directory")
    return path


def _private_storage_directory(
    environ: Mapping[str, str],
    name: str,
) -> Path:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required when the batch runtime is enabled")
    requested = Path(value)
    requested.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = requested.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{name} must be a real directory")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"{name} must not grant group or other permissions")
    return requested.resolve(strict=True)


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
