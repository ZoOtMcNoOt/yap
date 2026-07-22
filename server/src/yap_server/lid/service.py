from __future__ import annotations

from pathlib import Path
import stat
import threading
import time
from typing import Any

from .component_lock import LidComponentLock
from .errors import (
    LidPreflightCancelled,
    LidPreflightConflict,
    LidPreflightUnavailable,
)
from .materialization import (
    LidMaterializedRequest,
    remove_materialized_lid_request,
)
from .preflight import LidPreflightEngine
from .transport import (
    materialize_lid_transport_request,
    parse_lid_preflight_envelope,
)


class LidPreflightService:
    """Own transient probe lifetime while Rust remains language authority."""

    def __init__(
        self,
        *,
        lock: LidComponentLock,
        engine: LidPreflightEngine,
        work_root: Path,
        catalog_revision: str,
    ) -> None:
        if not isinstance(lock, LidComponentLock):
            raise TypeError("lock must be a validated LidComponentLock")
        root = Path(work_root)
        metadata = root.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise ValueError("LID preflight work root must be a real directory")
        self._lock = lock
        self._engine = engine
        self._work_root = root.resolve(strict=True)
        self._catalog_revision = catalog_revision
        self._lock_guard = threading.Lock()
        self._active: dict[str, threading.Event] = {}
        self._idle = threading.Condition(self._lock_guard)
        self._shutdown = False
        self._fenced_reason: str | None = None

    @property
    def fenced(self) -> bool:
        with self._lock_guard:
            return self._fenced_reason is not None

    def run_envelope(self, body: bytes) -> dict[str, Any]:
        request = parse_lid_preflight_envelope(
            body,
            lock=self._lock,
            expected_catalog_revision=self._catalog_revision,
        )
        cancellation = threading.Event()
        with self._lock_guard:
            if self._shutdown:
                raise LidPreflightUnavailable(
                    "LID preflight service is shutting down"
                )
            if self._fenced_reason is not None:
                raise LidPreflightUnavailable(self._fenced_reason)
            if request.request_id in self._active:
                raise LidPreflightConflict(
                    "LID preflight request is already active"
                )
            self._active[request.request_id] = cancellation
        materialized: LidMaterializedRequest | None = None
        try:
            def ensure_active() -> None:
                if cancellation.is_set():
                    raise LidPreflightCancelled("LID preflight was cancelled")

            materialized = materialize_lid_transport_request(
                request,
                destination=self._work_root / f"lid-{request.request_id}",
                lock=self._lock,
                ensure_active=ensure_active,
            )
            result = self._engine.evaluate(
                materialized,
                cancellation=cancellation,
            )
            return {
                **result,
                "sourcePcmSha256": request.source_pcm_sha256,
                "catalogRevision": request.catalog_revision,
            }
        finally:
            cleanup_error: Exception | None = None
            if materialized is not None:
                try:
                    remove_materialized_lid_request(materialized)
                except Exception as error:
                    cleanup_error = error
            with self._lock_guard:
                self._active.pop(request.request_id, None)
                self._idle.notify_all()
                if cleanup_error is not None:
                    self._fenced_reason = (
                        "LID preflight is fenced because transient probe cleanup "
                        "could not be verified"
                    )
            if cleanup_error is not None:
                raise LidPreflightUnavailable(
                    self._fenced_reason or "LID preflight cleanup failed"
                ) from cleanup_error

    def cancel(self, request_id: str) -> bool:
        with self._lock_guard:
            cancellation = self._active.get(request_id)
            if cancellation is None:
                return False
            cancellation.set()
            return True

    def close(self) -> None:
        with self._lock_guard:
            self._shutdown = True
            active = tuple(self._active.values())
        for cancellation in active:
            cancellation.set()
        self._engine.close()
        deadline = time.monotonic() + 5.0
        with self._lock_guard:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LidPreflightUnavailable(
                        "LID preflight did not drain during shutdown"
                    )
                self._idle.wait(timeout=remaining)
            if self._fenced_reason is not None:
                raise LidPreflightUnavailable(self._fenced_reason)
