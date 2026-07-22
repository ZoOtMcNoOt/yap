from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import threading
from typing import Any, Protocol

from .component_lock import LidComponentLock
from .errors import LidPreflightCancelled, LidPreflightConflict
from .materialization import (
    LidMaterializedRequest,
    canonical_lid_source_samples,
    materialize_lid_worker_request,
    remove_materialized_lid_request,
)
from .policy import (
    LidObservation,
    SourceVadInterval,
    map_lid_label_to_enabled_locales,
    resolve_lid_suggestion,
    select_lid_probe_windows_from_lock,
    validate_enabled_fixed_locales,
)
from .worker_contract import LidWorkerRequest, validate_lid_worker_result


class LidPreflightBackpressure(RuntimeError):
    """The bounded assistive-preflight capacity is already occupied."""


class LidPreflightWorker(Protocol):
    def run(
        self,
        request: LidWorkerRequest,
        request_root: Path,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]: ...


class LidPreflightEngine:
    """Bounded inference adapter; it never confirms or mutates a language."""

    def __init__(
        self,
        *,
        lock: LidComponentLock,
        worker: LidPreflightWorker,
        enabled_fixed_locales: Sequence[str],
        maximum_running: int = 1,
        maximum_queued: int = 2,
    ) -> None:
        if not isinstance(lock, LidComponentLock):
            raise TypeError("lock must be a validated LidComponentLock")
        if maximum_running < 1 or maximum_queued < 0:
            raise ValueError("LID preflight capacity is invalid")
        if not enabled_fixed_locales:
            raise ValueError("LID preflight requires at least one enabled fixed locale")
        locales = validate_enabled_fixed_locales(enabled_fixed_locales)
        self._lock = lock
        self._worker = worker
        self._enabled_fixed_locales = locales
        self._capacity = threading.BoundedSemaphore(
            maximum_running + maximum_queued
        )
        self._running = threading.BoundedSemaphore(maximum_running)
        self._active_lock = threading.Lock()
        self._active: set[str] = set()
        self._shutdown = threading.Event()

    def close(self) -> None:
        self._shutdown.set()
        close = getattr(self._worker, "close", None)
        if callable(close):
            close()

    def evaluate(
        self,
        materialized: LidMaterializedRequest,
        *,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        request = materialized.request
        cancelled = cancellation or threading.Event()
        if self._shutdown.is_set() or cancelled.is_set():
            raise LidPreflightCancelled("LID preflight was cancelled")
        if not self._capacity.acquire(blocking=False):
            raise LidPreflightBackpressure("LID preflight capacity is full")
        registered = False
        try:
            with self._active_lock:
                if request.request_id in self._active:
                    raise LidPreflightConflict("LID request is already active")
                self._active.add(request.request_id)
                registered = True
            while not self._running.acquire(timeout=0.1):
                if self._shutdown.is_set() or cancelled.is_set():
                    raise LidPreflightCancelled("LID preflight was cancelled")
            try:
                try:
                    output = self._worker.run(
                        request,
                        materialized.root,
                        cancellation=cancelled,
                    )
                except Exception as error:
                    if self._shutdown.is_set() or cancelled.is_set():
                        raise LidPreflightCancelled(
                            "LID preflight was cancelled"
                        ) from error
                    raise
            finally:
                self._running.release()
            validate_lid_worker_result(output, request=request, lock=self._lock)
            return _decision_result(
                output,
                lock=self._lock,
                enabled_fixed_locales=self._enabled_fixed_locales,
            )
        finally:
            if registered:
                with self._active_lock:
                    self._active.discard(request.request_id)
            self._capacity.release()


def run_source_lid_preflight(
    *,
    engine: LidPreflightEngine,
    lock: LidComponentLock,
    source_wav: Path,
    work_root: Path,
    request_id: str,
    vad_intervals: Sequence[SourceVadInterval],
    cancellation: threading.Event | None = None,
) -> dict[str, Any]:
    """Convenience path for a canonical source; transport remains replaceable."""

    source_samples = canonical_lid_source_samples(source_wav, lock)
    selection = select_lid_probe_windows_from_lock(
        source_samples=source_samples,
        vad_intervals=vad_intervals,
        lock=lock,
    )
    if selection.status != "selected":
        return _manual_result(
            request_id=request_id,
            source_samples=source_samples,
            reason=selection.reason,
            lock=lock,
        )
    def ensure_active() -> None:
        if cancellation is not None and cancellation.is_set():
            raise LidPreflightCancelled("LID preflight was cancelled")

    materialized = materialize_lid_worker_request(
        source_wav=source_wav,
        destination=Path(work_root) / request_id,
        request_id=request_id,
        selection=selection,
        lock=lock,
        ensure_active=ensure_active,
    )
    try:
        return engine.evaluate(materialized, cancellation=cancellation)
    finally:
        remove_materialized_lid_request(materialized)


def _decision_result(
    output: dict[str, Any],
    *,
    lock: LidComponentLock,
    enabled_fixed_locales: Sequence[str],
) -> dict[str, Any]:
    raw_observations = output["observations"]
    observations = tuple(
        LidObservation(
            index=value["index"],
            source_start_sample=value["sourceStartSample"],
            source_end_sample=value["sourceEndSample"],
            raw_label=value["rawLabel"],
            top_score=value["topScore"],
            score_margin=value["scoreMargin"],
        )
        for value in raw_observations
    )
    decision = resolve_lid_suggestion(
        observations,
        enabled_fixed_locales=enabled_fixed_locales,
    )
    evidence = []
    for value in raw_observations:
        candidates = map_lid_label_to_enabled_locales(
            value["rawLabel"],
            enabled_fixed_locales=enabled_fixed_locales,
        )
        evidence.append(
            {
                **value,
                "mappedLocale": candidates[0] if len(candidates) == 1 else None,
            }
        )
    return {
        "schemaVersion": 1,
        "requestId": output["requestId"],
        "status": decision.status,
        "reason": decision.reason,
        "suggestedLocale": decision.suggested_locale,
        "userConfirmationRequired": True,
        "sourceSamples": output["sourceSamples"],
        "component": _component_evidence(lock),
        "observations": evidence,
    }


def _manual_result(
    *,
    request_id: str,
    source_samples: int,
    reason: str,
    lock: LidComponentLock,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "requestId": request_id,
        "status": "manual",
        "reason": reason,
        "suggestedLocale": None,
        "userConfirmationRequired": True,
        "sourceSamples": source_samples,
        "component": _component_evidence(lock),
        "observations": [],
    }


def _component_evidence(lock: LidComponentLock) -> dict[str, Any]:
    return {
        "id": lock.component_id,
        "runtime": {
            "pythonVersion": lock.runtime.python_version,
            "cpuOnly": lock.runtime.cpu_only,
        },
        "model": {
            "id": lock.model.model_id,
            "revision": lock.model.revision,
        },
        "policyRevision": lock.policy.revision,
        "scoreSemantics": lock.policy.score_semantics,
    }
