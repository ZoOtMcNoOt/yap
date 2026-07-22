from __future__ import annotations

from collections.abc import Mapping
import threading
from types import MappingProxyType

from yap_server.pools.batch_contract import (
    BatchAsrJob,
    BatchWorker,
    WorkerExecutionError,
    validate_asr_route_id,
)


_MAX_REGISTERED_PROVIDERS = 8


class ProviderBatchWorkerRegistry:
    """Immutable provider dispatch table used as one batch-pool worker."""

    def __init__(self, workers: Mapping[str, BatchWorker]) -> None:
        copied = dict(workers)
        if not copied or len(copied) > _MAX_REGISTERED_PROVIDERS:
            raise ValueError("provider worker registry size is invalid")
        for provider_id, worker in copied.items():
            validate_asr_route_id(provider_id, "provider worker key")
            if not callable(getattr(worker, "run", None)):
                raise ValueError("registered provider workers must implement run")
        self._workers = MappingProxyType(copied)
        self._closed = threading.Event()

    def run(
        self,
        job: BatchAsrJob,
        cancellation: threading.Event,
    ) -> dict[str, object]:
        if self._closed.is_set():
            raise WorkerExecutionError("provider worker registry is closed")
        try:
            worker = self._workers[job.route.provider_id]
        except KeyError as error:
            raise WorkerExecutionError(
                "no batch worker is registered for the resolved provider"
            ) from error
        return worker.run(job, cancellation)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        first_error: BaseException | None = None
        closed_workers: set[int] = set()
        for worker in self._workers.values():
            identity = id(worker)
            if identity in closed_workers:
                continue
            closed_workers.add(identity)
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
