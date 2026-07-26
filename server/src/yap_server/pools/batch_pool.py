from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
import threading

from yap_server.pools.batch_contract import (
    AsrRouteDecision,
    AsrRouteResolver,
    BatchAsrJob,
    BatchJobFactory,
    BatchWorker,
    DuplicatePoolJob,
    PoolBackpressure,
    PoolFenced,
    WorkerContainmentError,
    validate_asr_catalog_revision,
    validate_batch_job_id,
)
from yap_server.pools.executor_cleanup import (
    EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS,
    shutdown_executor_or_raise,
)


_EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS = EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS


class BatchPoolReservation:
    """Single-use handle for a slot already counted against pool capacity."""

    def __init__(
        self,
        pool: BatchAsrPool,
        job_id: str,
        cancellation: threading.Event,
    ) -> None:
        self._pool = pool
        self._job_id = job_id
        self._cancellation = cancellation
        self._lock = threading.Lock()
        self._consumed = False

    def start(self, factory: BatchJobFactory) -> Future[dict[str, object]]:
        with self._lock:
            if self._consumed:
                raise RuntimeError("batch reservation is already consumed")
            self._consumed = True
            return self._pool._start_reserved(
                self._job_id,
                self._cancellation,
                factory,
            )

    def abort(self) -> None:
        with self._lock:
            if self._consumed:
                return
            self._consumed = True
            self._pool._abort_reserved(self._job_id, self._cancellation)


class BatchAsrPool:
    """A bounded thread-backed pool for isolated batch-ASR workers."""

    def __init__(
        self,
        worker: BatchWorker,
        *,
        route_resolver: AsrRouteResolver,
        asr_catalog_revision: str,
        max_workers: int = 1,
        max_queued: int = 2,
        max_inflight_pcm_bytes: int = 2**63 - 1,
    ) -> None:
        if (
            max_workers < 1
            or max_queued < 0
            or isinstance(max_inflight_pcm_bytes, bool)
            or not isinstance(max_inflight_pcm_bytes, int)
            or max_inflight_pcm_bytes < 1
        ):
            raise ValueError("pool limits are invalid")
        validate_asr_catalog_revision(asr_catalog_revision)
        self._worker = worker
        self._route_resolver = route_resolver
        self._asr_catalog_revision = asr_catalog_revision
        self._slots = threading.BoundedSemaphore(max_workers + max_queued)
        self._max_inflight_pcm_bytes = max_inflight_pcm_bytes
        self._available_pcm_bytes = max_inflight_pcm_bytes
        self._lock = threading.Lock()
        self._outstanding: set[str] = set()
        self._pcm_byte_lengths: dict[str, int] = {}
        self._cancellations: dict[str, threading.Event] = {}
        self._futures: dict[str, Future[dict[str, object]]] = {}
        self._fenced_reason: str | None = None
        self._shutdown = False
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="yap-batch-asr",
        )

    @property
    def outstanding_count(self) -> int:
        with self._lock:
            return len(self._outstanding)

    @property
    def fenced(self) -> bool:
        with self._lock:
            return self._fenced_reason is not None

    def resolve_route(self, catalog_language_bcp47: str) -> AsrRouteDecision:
        route = self._route_resolver(catalog_language_bcp47)
        if not isinstance(route, AsrRouteDecision):
            raise RuntimeError("batch pool route resolver returned an invalid route")
        return route

    @property
    def asr_catalog_revision(self) -> str:
        return self._asr_catalog_revision

    def submit(self, job: BatchAsrJob) -> Future[dict[str, object]]:
        reservation = self.reserve(job.job_id)
        return reservation.start(lambda _cancellation: job)

    def reserve(
        self,
        job_id: str,
        *,
        pcm_byte_length: int = 1,
    ) -> BatchPoolReservation:
        validate_batch_job_id(job_id)
        if (
            isinstance(pcm_byte_length, bool)
            or not isinstance(pcm_byte_length, int)
            or not 1 <= pcm_byte_length <= self._max_inflight_pcm_bytes
        ):
            raise ValueError("batch ASR PCM reservation size is invalid")
        with self._lock:
            if self._shutdown:
                raise PoolFenced("batch ASR pool is shut down")
            if self._fenced_reason is not None:
                raise PoolFenced(self._fenced_reason)
            if job_id in self._outstanding:
                raise DuplicatePoolJob(f"pool job {job_id!r} is already outstanding")
            if not self._slots.acquire(blocking=False):
                raise PoolBackpressure("batch ASR pool is at its bounded capacity")
            if pcm_byte_length > self._available_pcm_bytes:
                self._slots.release()
                raise PoolBackpressure(
                    "batch ASR pool exceeds its aggregate PCM capacity"
                )
            self._available_pcm_bytes -= pcm_byte_length
            self._outstanding.add(job_id)
            self._pcm_byte_lengths[job_id] = pcm_byte_length
            cancellation = threading.Event()
            self._cancellations[job_id] = cancellation
        return BatchPoolReservation(self, job_id, cancellation)

    def _start_reserved(
        self,
        job_id: str,
        cancellation: threading.Event,
        factory: BatchJobFactory,
    ) -> Future[dict[str, object]]:
        with self._lock:
            if self._shutdown:
                self._release_unstarted_locked(job_id, cancellation)
                raise PoolFenced("batch ASR pool is shut down")
            if (
                job_id not in self._outstanding
                or self._cancellations.get(job_id) is not cancellation
                or job_id in self._futures
            ):
                raise RuntimeError("batch reservation is no longer active")
            try:
                future = self._executor.submit(
                    self._run_reserved,
                    job_id,
                    factory,
                    cancellation,
                )
            except BaseException:
                self._outstanding.discard(job_id)
                self._cancellations.pop(job_id, None)
                pcm_byte_length = self._pcm_byte_lengths.pop(job_id)
                self._available_pcm_bytes += pcm_byte_length
                self._slots.release()
                raise
            self._futures[job_id] = future
        future.add_done_callback(lambda _future: self._release(job_id))
        return future

    def _release_unstarted_locked(
        self,
        job_id: str,
        cancellation: threading.Event,
    ) -> None:
        if (
            self._cancellations.get(job_id) is not cancellation
            or job_id in self._futures
        ):
            return
        self._outstanding.discard(job_id)
        self._cancellations.pop(job_id, None)
        pcm_byte_length = self._pcm_byte_lengths.pop(job_id)
        self._available_pcm_bytes += pcm_byte_length
        self._slots.release()

    def _abort_reserved(
        self,
        job_id: str,
        cancellation: threading.Event,
    ) -> None:
        with self._lock:
            if self._cancellations.get(job_id) is not cancellation:
                return
            if job_id in self._futures:
                raise RuntimeError("started batch reservation cannot be aborted")
            self._outstanding.remove(job_id)
            self._cancellations.pop(job_id, None)
            pcm_byte_length = self._pcm_byte_lengths.pop(job_id)
            self._available_pcm_bytes += pcm_byte_length
            self._slots.release()

    def _run_reserved(
        self,
        job_id: str,
        factory: BatchJobFactory,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        try:
            if cancellation.is_set():
                raise CancelledError()
            job = factory(cancellation)
            if job.job_id != job_id:
                raise ValueError("prepared batch job differs from its reservation")
            if cancellation.is_set():
                raise CancelledError()
            return self._worker.run(job, cancellation)
        except WorkerContainmentError:
            with self._lock:
                self._fenced_reason = (
                    "batch ASR pool is fenced because worker containment "
                    "could not be verified"
                )
            raise

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            cancellation = self._cancellations.get(job_id)
            future = self._futures.get(job_id)
            if cancellation is None:
                return False
            cancellation.set()
        if future is not None:
            future.cancel()
        return True

    def _release(self, job_id: str) -> None:
        with self._lock:
            if job_id not in self._outstanding:
                return
            self._outstanding.discard(job_id)
            self._cancellations.pop(job_id, None)
            self._futures.pop(job_id, None)
            pcm_byte_length = self._pcm_byte_lengths.pop(job_id)
            self._available_pcm_bytes += pcm_byte_length
            self._slots.release()

    def shutdown(self) -> None:
        close_worker = getattr(self._worker, "close", None)
        containment_error: WorkerContainmentError | None = None
        try:
            with self._lock:
                self._shutdown = True
                for cancellation in self._cancellations.values():
                    cancellation.set()
                for job_id in tuple(self._outstanding):
                    if job_id not in self._futures:
                        cancellation = self._cancellations[job_id]
                        self._release_unstarted_locked(job_id, cancellation)
            if callable(close_worker):
                close_worker()
        except WorkerContainmentError as error:
            containment_error = error
            with self._lock:
                self._fenced_reason = (
                    "batch ASR pool is fenced because worker containment "
                    "could not be verified"
                )
        finally:
            if containment_error is None:
                try:
                    shutdown_executor_or_raise(
                        self._executor,
                        timeout_seconds=_EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS,
                        component="batch ASR",
                    )
                except WorkerContainmentError as error:
                    containment_error = error
                    with self._lock:
                        self._fenced_reason = (
                            "batch ASR pool is fenced because executor containment "
                            "could not be verified"
                        )
            else:
                # The process boundary must fail-stop immediately once an owned
                # worker reports unverified containment. Waiting here cannot
                # improve that result and can only strand the caller.
                self._executor.shutdown(wait=False, cancel_futures=True)
        if containment_error is not None:
            raise containment_error
