"""Qualify the authenticated Archivist product vertical at one exact head."""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
from http import HTTPStatus
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import tempfile
import threading
import time
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
import yaml

from yap_server.agents.admission_client import AgentAdmissionClient
from yap_server.agents.admission_protocol import (
    AgentAdmission,
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
    UnixAgentAdmissionTransport,
)
from yap_server.agents.archivist import PostgresArchivistProcessor
from yap_server.agents.archivist_ingestion_runner import (
    PostgresArchivistIngestionRunner,
)
from yap_server.agents.archivist_ingestion_service import ArchivistIngestionService
from yap_server.agents.archivist_runtime import ArchivistRuntime
from yap_server.agents.archivist_service import ArchivistService
from yap_server.api.app import create_server
from yap_server.auth import (
    AuthenticatedPrincipal,
    AuthenticationFailure,
)
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.evaluation.agent_admission_broker_observation import (
    build_checked_admission_broker,
    observe_admission_broker,
)
from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.librarian_qualification_gate import (
    _probe_server_io_capacity,
    _require_exact_teardown,
    _restart_database,
    _write_new_private_text,
)
from yap_server.evaluation.owned_postgres_knowledge_runtime import (
    OwnedPostgresKnowledgeRuntime,
    StartedKnowledgeDatabase,
    load_knowledge_database_runtime_lock,
)
from yap_server.evaluation.private_json_evidence import (
    write_new_private_json_evidence,
)
from yap_server.jobs.service import RecordingJobService
from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.reviewed_capture_ledger import (
    install_reviewed_capture_schema,
)
from yap_server.knowledge.reviewed_meeting_knowledge import result_revision_sha256
from yap_server.pools.agent_vllm_service_profile import (
    load_complex_agent_vllm_service_profile,
    load_rapid_agent_vllm_service_profile,
)
from yap_server.pools.batch_contract import AsrRouteDecision, BatchJobFactory
from yap_server.private_artifact import read_json_object_with_identity
from yap_server.private_postgres_connection import private_postgres_connection_factory


_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_REASONS = {
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
    "failed": frozenset(
        {
            "invalid-reviewed-source",
            "source-changed",
            "storage-unavailable",
            "service-unavailable",
        }
    ),
}
_PRODUCT_REQUEST_ID = re.compile(r"^archivist-ingestion-[0-9a-f]{32}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_ACCEPTANCE_BYTES = 16 * 1024
_MAXIMUM_HTTP_BYTES = 64 * 1024
_HTTP_TIMEOUT_SECONDS = 25.0
_POLL_INTERVAL_SECONDS = 0.02
_NORMAL_WAVE_TIMEOUT_SECONDS = 90.0
_WORKER_CONTAINMENT_SECONDS = 67.0
_ASR_CATALOG_REVISION = "6" * 64
_ASR_MODEL_REVISION = "7" * 40
_ARCHIVIST_WORK = AgentWorkSpec(
    role=AgentRole.ARCHIVIST,
    purpose=AgentPurpose.KNOWLEDGE_INGEST,
    route=ExecutionRoute.SERVER_IO,
    scheduling_class=SchedulingClass.BACKGROUND_IO,
)
_ACCEPTANCE_FIELDS = frozenset(
    {
        "schemaVersion",
        "qualificationScope",
        "qualified",
        "caseCount",
        "ownerCount",
        "requestCount",
        "synchronizedOwnerCount",
        "stagedCount",
        "cancelledCount",
        "exactTerminalCount",
        "uniqueProductRequestIdCount",
        "reviewedCaptureCount",
        "sourceAdmissionCount",
        "stagedGenerationCount",
        "activeGenerationCount",
        "maximumNormalP95Milliseconds",
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "sourceDriftFailedClosed",
        "exactReplayReused",
        "serverDerivedReviewExact",
        "noActivationExact",
        "httpCancellationFailedClosed",
        "singleLeasePerRequestExact",
        "brokerIdentityUnchanged",
        "workerContainmentMet",
    }
)


@dataclass(frozen=True, slots=True)
class ArchivistProductAcceptance:
    plan_sha256: str
    case_count: int
    owner_count: int
    request_count: int
    synchronized_owner_count: int
    staged_count: int
    cancelled_count: int
    exact_terminal_count: int
    unique_product_request_id_count: int
    reviewed_capture_count: int
    source_admission_count: int
    staged_generation_count: int
    active_generation_count: int
    maximum_normal_p95_milliseconds: int
    normal_p95_within_bound: bool
    authenticated_http_exact: bool
    owner_isolation_exact: bool
    source_drift_failed_closed: bool
    exact_replay_reused: bool
    server_derived_review_exact: bool
    no_activation_exact: bool
    http_cancellation_failed_closed: bool
    single_lease_per_request_exact: bool
    broker_identity_unchanged: bool
    worker_containment_met: bool

    def expected_public_evidence(self) -> dict[str, int | bool]:
        return {
            "qualified": True,
            "caseCount": self.case_count,
            "ownerCount": self.owner_count,
            "requestCount": self.request_count,
            "synchronizedOwnerCount": self.synchronized_owner_count,
            "stagedCount": self.staged_count,
            "cancelledCount": self.cancelled_count,
            "exactTerminalCount": self.exact_terminal_count,
            "uniqueProductRequestIdCount": self.unique_product_request_id_count,
            "reviewedCaptureCount": self.reviewed_capture_count,
            "sourceAdmissionCount": self.source_admission_count,
            "stagedGenerationCount": self.staged_generation_count,
            "activeGenerationCount": self.active_generation_count,
            "maximumNormalP95Milliseconds": (self.maximum_normal_p95_milliseconds),
            "normalP95WithinBound": self.normal_p95_within_bound,
            "authenticatedHttpExact": self.authenticated_http_exact,
            "ownerIsolationExact": self.owner_isolation_exact,
            "sourceDriftFailedClosed": self.source_drift_failed_closed,
            "exactReplayReused": self.exact_replay_reused,
            "serverDerivedReviewExact": self.server_derived_review_exact,
            "noActivationExact": self.no_activation_exact,
            "httpCancellationFailedClosed": self.http_cancellation_failed_closed,
            "singleLeasePerRequestExact": self.single_lease_per_request_exact,
            "brokerIdentityUnchanged": self.broker_identity_unchanged,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class ArchivistProductView:
    request_id: str
    status: str
    job_id: str
    result_sha256: str
    capture_sha256: str | None = None
    source_admission_sha256: str | None = None
    generation_sha256: str | None = None
    concept_count: int | None = None
    permission_count: int | None = None
    reason: str | None = None

    def terminal_shape(self) -> tuple[str, str | None]:
        return self.status, self.reason

    def staged_identity(self) -> tuple[object, ...]:
        return (
            self.job_id,
            self.result_sha256,
            self.capture_sha256,
            self.source_admission_sha256,
            self.generation_sha256,
            self.concept_count,
            self.permission_count,
        )

    def to_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "status": self.status,
            "jobId": self.job_id,
            "resultSha256": self.result_sha256,
        }
        for key, item in (
            ("captureSha256", self.capture_sha256),
            ("sourceAdmissionSha256", self.source_admission_sha256),
            ("generationSha256", self.generation_sha256),
            ("conceptCount", self.concept_count),
            ("permissionCount", self.permission_count),
            ("reason", self.reason),
        ):
            if item is not None:
                value[key] = item
        return value


@dataclass(frozen=True, slots=True)
class ArchivistProductObservation:
    label: str
    owner_id: str
    job_id: str
    product_request_id: str | None
    observed: ArchivistProductView | None
    expected_status: str
    duration_milliseconds: int
    exact_match: bool
    failure_kind: str | None


@dataclass(frozen=True, slots=True)
class _SeededRecording:
    owner_id: str
    principal: AuthenticatedPrincipal
    token: str
    job_id: str
    result_sha256: str
    title: str
    transcript: str


@dataclass(slots=True)
class _SeededJobs:
    jobs: RecordingJobService
    storage_root: Path
    processor: _QualificationJobProcessor
    seeds: tuple[_SeededRecording, ...]
    tokens_by_owner: Mapping[str, str]


class _QualificationAuthenticator:
    authentication_required = True
    principal_access_enforced = True

    def __init__(self, *, tenant_id: str, tokens: Mapping[str, str]) -> None:
        self._tenant_id = tenant_id
        self._tokens = dict(tokens)
        self._lock = threading.Lock()
        self._headers: list[str | None] = []

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        with self._lock:
            self._headers.append(authorization)
        if authorization is None:
            raise AuthenticationFailure.missing()
        if not authorization.startswith("Bearer "):
            raise AuthenticationFailure.invalid()
        owner_id = self._tokens.get(authorization[7:])
        if owner_id is None:
            raise AuthenticationFailure.invalid()
        return AuthenticatedPrincipal(
            tenant_id=self._tenant_id,
            subject_id=owner_id,
            client_id="archivist-product-qualification",
            scopes=frozenset({"knowledge.ingest"}),
        )


class _ObservedAdmission:
    def __init__(self, delegate: AgentAdmissionClient) -> None:
        self._delegate = delegate
        self._condition = threading.Condition()
        self._new_tickets: list[str] = []
        self._submits: list[tuple[str, str, AgentWorkSpec, str, str]] = []
        self._completes: list[tuple[str, str]] = []
        self._cancels: list[tuple[str, str]] = []
        self._acknowledgements: list[tuple[str, str]] = []

    def new_ticket(self) -> AgentAdmissionTicket:
        ticket = self._delegate.new_ticket()
        with self._condition:
            self._new_tickets.append(ticket.request_id)
            self._condition.notify_all()
        return ticket

    def submit(self, ticket: AgentAdmissionTicket, **kwargs: object) -> AgentAdmission:
        work = kwargs.get("work")
        source_sha256 = kwargs.get("source_sha256")
        principal = kwargs.get("principal")
        if (
            not isinstance(work, AgentWorkSpec)
            or not isinstance(source_sha256, str)
            or not isinstance(principal, AuthenticatedPrincipal)
        ):
            raise TypeError("observed Archivist admission submission is invalid")
        admission = self._delegate.submit(ticket, **kwargs)
        with self._condition:
            self._submits.append(
                (
                    ticket.request_id,
                    principal.subject_id,
                    work,
                    source_sha256,
                    admission.outcome,
                )
            )
            self._condition.notify_all()
        return admission

    def status(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        return self._delegate.status(ticket)

    def cancel(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        admission = self._delegate.cancel(ticket)
        with self._condition:
            self._cancels.append((ticket.request_id, admission.outcome))
            self._condition.notify_all()
        return admission

    def complete(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        admission = self._delegate.complete(ticket)
        with self._condition:
            self._completes.append((ticket.request_id, admission.outcome))
            self._condition.notify_all()
        return admission

    def acknowledge_cancellation(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        admission = self._delegate.acknowledge_cancellation(ticket)
        with self._condition:
            self._acknowledgements.append((ticket.request_id, admission.outcome))
            self._condition.notify_all()
        return admission

    def wait_for_submit_count(self, count: int, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while len(self._submits) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    raise TimeoutError(
                        "Archivist admission submission was not observed"
                    )

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            tickets = tuple(self._new_tickets)
            submits = tuple(self._submits)
            completes = tuple(self._completes)
            cancels = tuple(self._cancels)
            acknowledgements = tuple(self._acknowledgements)
        terminal_ids = {request_id for request_id, _ in completes} | {
            request_id for request_id, _ in acknowledgements
        }
        return {
            "newTicketCount": len(tickets),
            "submitCount": len(submits),
            "completeCount": len(completes),
            "cancelCount": len(cancels),
            "acknowledgeCount": len(acknowledgements),
            "allWorkIdentityExact": all(
                work == _ARCHIVIST_WORK
                and _SHA256.fullmatch(source_sha256) is not None
                and outcome in {"queued", "admitted"}
                for _, _, work, source_sha256, outcome in submits
            ),
            "ownerSourceBindings": tuple(
                sorted(
                    (owner_id, source_sha256)
                    for _, owner_id, _, source_sha256, _ in submits
                )
            ),
            "allTerminalExact": (
                len(set(tickets)) == len(tickets)
                and {request_id for request_id, *_ in submits} == set(tickets)
                and terminal_ids == set(tickets)
                and all(outcome == "completed" for _, outcome in completes)
                and all(
                    outcome in {"cancelled", "cancellation-requested"}
                    for _, outcome in cancels
                )
                and all(outcome == "cancelled" for _, outcome in acknowledgements)
            ),
        }


@dataclass(slots=True)
class _ProductRuntime:
    service: ArchivistIngestionService
    admission: _ObservedAdmission

    def close(self) -> None:
        self.service.close()


class _QualificationReservation:
    def __init__(self, processor: _QualificationJobProcessor, job_id: str) -> None:
        self._processor = processor
        self._job_id = job_id
        self._aborted = False

    def start(self, factory: BatchJobFactory) -> Future[dict[str, object]]:
        if self._aborted:
            raise RuntimeError("qualification reservation was aborted")
        job = factory(threading.Event())
        if job.job_id != self._job_id:
            raise RuntimeError("qualification ASR identity changed")
        result = self._processor.result_for(job.job_id)
        future: Future[dict[str, object]] = Future()
        future.set_result(result)
        return future

    def abort(self) -> None:
        self._aborted = True


class _QualificationJobProcessor:
    def __init__(self) -> None:
        self._results: dict[str, dict[str, object]] = {}

    @property
    def asr_catalog_revision(self) -> str:
        return _ASR_CATALOG_REVISION

    def resolve_route(self, catalog_language_bcp47: str) -> AsrRouteDecision:
        return AsrRouteDecision(
            provider_id="qualification",
            pool_id="qualification-batch",
            execution_mode="fixedBatch",
            model_revision=_ASR_MODEL_REVISION,
            provider_language=catalog_language_bcp47.split("-", 1)[0].lower(),
        )

    def reserve(
        self, job_id: str, *, pcm_byte_length: int
    ) -> _QualificationReservation:
        if pcm_byte_length < 1 or job_id not in self._results:
            raise RuntimeError("qualification result was not planned")
        return _QualificationReservation(self, job_id)

    def cancel(self, job_id: str) -> bool:
        return job_id in self._results

    def plan(self, job_id: str, result: Mapping[str, object]) -> None:
        if job_id in self._results:
            raise RuntimeError("qualification result identity was reused")
        self._results[job_id] = dict(result)

    def result_for(self, job_id: str) -> dict[str, object]:
        return dict(self._results[job_id])


def load_archivist_product_acceptance(path: Path) -> ArchivistProductAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Archivist product acceptance",
    )
    if set(value) != _ACCEPTANCE_FIELDS:
        raise ValueError("Archivist product acceptance fields differ")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"] != "archivist-authenticated-product-vertical"
        or value["qualified"] is not True
    ):
        raise ValueError("Archivist product acceptance identity differs")
    integer_fields = {
        "caseCount": 9,
        "ownerCount": 8,
        "requestCount": 10,
        "synchronizedOwnerCount": 8,
        "stagedCount": 9,
        "cancelledCount": 1,
        "exactTerminalCount": 10,
        "uniqueProductRequestIdCount": 10,
        "reviewedCaptureCount": 9,
        "sourceAdmissionCount": 8,
        "stagedGenerationCount": 8,
        "activeGenerationCount": 0,
        "maximumNormalP95Milliseconds": 60_000,
    }
    if any(
        type(value[name]) is not int or value[name] != expected
        for name, expected in integer_fields.items()
    ):
        raise ValueError("Archivist product acceptance counts differ")
    boolean_fields = (
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "sourceDriftFailedClosed",
        "exactReplayReused",
        "serverDerivedReviewExact",
        "noActivationExact",
        "httpCancellationFailedClosed",
        "singleLeasePerRequestExact",
        "brokerIdentityUnchanged",
        "workerContainmentMet",
    )
    if any(value[name] is not True for name in boolean_fields):
        raise ValueError("Archivist product acceptance flags differ")
    return ArchivistProductAcceptance(
        identity,
        *(value[name] for name in integer_fields),
        *(value[name] for name in boolean_fields),
    )


def _parse_product_view(value: object) -> ArchivistProductView:
    if not isinstance(value, dict):
        raise ValueError("Archivist product view is invalid")
    status = value.get("status")
    base = {"schemaVersion", "requestId", "status", "jobId", "resultSha256"}
    if status in _ACTIVE_STATUSES:
        expected = base
    elif status == "staged":
        expected = base | {
            "captureSha256",
            "sourceAdmissionSha256",
            "generationSha256",
            "conceptCount",
            "permissionCount",
        }
    elif status in _TERMINAL_REASONS:
        expected = base | {"reason"}
    else:
        raise ValueError("Archivist product status is invalid")
    if set(value) != expected:
        raise ValueError("Archivist product view fields differ")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("Archivist product view schema differs")
    request_id = value["requestId"]
    job_id = value["jobId"]
    result_sha256 = value["resultSha256"]
    if (
        not isinstance(request_id, str)
        or _PRODUCT_REQUEST_ID.fullmatch(request_id) is None
    ):
        raise ValueError("Archivist product request identity is invalid")
    if not isinstance(job_id, str) or _OPAQUE_ID.fullmatch(job_id) is None:
        raise ValueError("Archivist product job identity is invalid")
    if not isinstance(result_sha256, str) or _SHA256.fullmatch(result_sha256) is None:
        raise ValueError("Archivist product result identity is invalid")
    if status == "staged":
        hashes = tuple(
            value[name]
            for name in (
                "captureSha256",
                "sourceAdmissionSha256",
                "generationSha256",
            )
        )
        labels = ("capture", "source admission", "generation")
        for item, label in zip(hashes, labels, strict=True):
            if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
                raise ValueError(f"Archivist product {label} identity is invalid")
        counts = (value["conceptCount"], value["permissionCount"])
        if any(type(item) is not int or item < 1 for item in counts):
            raise ValueError("Archivist product staged counts are invalid")
        return ArchivistProductView(
            request_id=request_id,
            status=status,
            job_id=job_id,
            result_sha256=result_sha256,
            capture_sha256=hashes[0],
            source_admission_sha256=hashes[1],
            generation_sha256=hashes[2],
            concept_count=counts[0],
            permission_count=counts[1],
        )
    reason = value.get("reason")
    if status in _TERMINAL_REASONS and reason not in _TERMINAL_REASONS[status]:
        raise ValueError("Archivist product terminal reason is invalid")
    return ArchivistProductView(
        request_id=request_id,
        status=status,
        job_id=job_id,
        result_sha256=result_sha256,
        reason=reason,
    )


def _http_json(
    base_url: str,
    path: str,
    *,
    method: str,
    token: str | None,
    body: Mapping[str, object] | None = None,
) -> tuple[int, Mapping[str, object]]:
    encoded = (
        None
        if body is None
        else json.dumps(dict(body), separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    headers = {"Accept": "application/json"}
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url}{path}",
        data=encoded,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            status = response.status
            payload = response.read(_MAXIMUM_HTTP_BYTES + 1)
    except HTTPError as error:
        status = error.code
        payload = error.read(_MAXIMUM_HTTP_BYTES + 1)
    if len(payload) > _MAXIMUM_HTTP_BYTES:
        raise ValueError("Archivist product HTTP response is too large")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Archivist product HTTP response is invalid")
    return status, value


def _request_body(seed: _SeededRecording, *, result_sha256: str | None = None):
    return {
        "schemaVersion": 1,
        "jobId": seed.job_id,
        "expectedResultSha256": result_sha256 or seed.result_sha256,
    }


def _submit_product_request(
    base_url: str, seed: _SeededRecording
) -> ArchivistProductView:
    status, value = _http_json(
        base_url,
        "/v1/archivist-ingestions",
        method="POST",
        token=seed.token,
        body=_request_body(seed),
    )
    if status != HTTPStatus.ACCEPTED:
        raise RuntimeError("Archivist product submission was not accepted")
    view = _parse_product_view(value)
    if view.job_id != seed.job_id or view.result_sha256 != seed.result_sha256:
        raise ValueError("Archivist product submission source binding differs")
    return view


def _wait_for_terminal(
    base_url: str,
    *,
    request_id: str,
    token: str,
    timeout_seconds: float = _NORMAL_WAVE_TIMEOUT_SECONDS,
) -> ArchivistProductView:
    deadline = time.monotonic() + timeout_seconds
    while True:
        status, value = _http_json(
            base_url,
            f"/v1/archivist-ingestions/{request_id}",
            method="GET",
            token=token,
        )
        if status != HTTPStatus.OK:
            raise RuntimeError("Archivist product request disappeared")
        view = _parse_product_view(value)
        if view.status not in _ACTIVE_STATUSES:
            return view
        if time.monotonic() >= deadline:
            raise TimeoutError("Archivist product request did not become terminal")
        time.sleep(_POLL_INTERVAL_SECONDS)


def _run_normal_request(
    *,
    base_url: str,
    seed: _SeededRecording,
    label: str,
    barrier: threading.Barrier | None = None,
) -> ArchivistProductObservation:
    started = time.monotonic()
    try:
        if barrier is not None:
            barrier.wait(timeout=10)
        initial = _submit_product_request(base_url, seed)
        observed = _wait_for_terminal(
            base_url,
            request_id=initial.request_id,
            token=seed.token,
        )
        exact = (
            observed.status == "staged"
            and observed.job_id == seed.job_id
            and observed.result_sha256 == seed.result_sha256
            and observed.concept_count == 1
            and observed.permission_count == 1
        )
        return ArchivistProductObservation(
            label=label,
            owner_id=seed.owner_id,
            job_id=seed.job_id,
            product_request_id=observed.request_id,
            observed=observed,
            expected_status="staged",
            duration_milliseconds=max(0, int((time.monotonic() - started) * 1_000)),
            exact_match=exact,
            failure_kind=None if exact else "terminal-mismatch",
        )
    except BaseException as error:
        return ArchivistProductObservation(
            label=label,
            owner_id=seed.owner_id,
            job_id=seed.job_id,
            product_request_id=None,
            observed=None,
            expected_status="staged",
            duration_milliseconds=max(0, int((time.monotonic() - started) * 1_000)),
            exact_match=False,
            failure_kind=type(error).__name__,
        )


def _run_normal_wave(
    base_url: str,
    seeds: Sequence[_SeededRecording],
) -> tuple[ArchivistProductObservation, ...]:
    if len(seeds) != 8 or len({seed.owner_id for seed in seeds}) != 8:
        raise ValueError("Archivist normal wave requires eight distinct owners")
    barrier = threading.Barrier(8)
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="archivist-product")
    futures = [
        executor.submit(
            _run_normal_request,
            base_url=base_url,
            seed=seed,
            label=f"normal-{index}",
            barrier=barrier,
        )
        for index, seed in enumerate(seeds)
    ]
    done, uncontained = wait(futures, timeout=_NORMAL_WAVE_TIMEOUT_SECONDS)
    if uncontained:
        for future in uncontained:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError("Archivist product wave workers were not contained")
    executor.shutdown(wait=True, cancel_futures=True)
    return tuple(future.result() for future in futures if future in done)


def _probe_http_and_source_authority(
    base_url: str,
    seeds: Sequence[_SeededRecording],
) -> dict[str, bool]:
    first, foreign = seeds[0], seeds[1]
    fake_request = "archivist-ingestion-" + "0" * 32
    health_status, health = _http_json(base_url, "/v1/health", method="GET", token=None)
    checks = {
        "healthCapabilityExact": (
            health_status == HTTPStatus.OK
            and health.get("auth") == "required"
            and isinstance(health.get("capabilities"), dict)
            and health["capabilities"].get("archivistIngestions") is True
        )
    }
    for method, path, body, label in (
        ("POST", "/v1/archivist-ingestions", _request_body(first), "Post"),
        ("GET", f"/v1/archivist-ingestions/{fake_request}", None, "Get"),
        ("DELETE", f"/v1/archivist-ingestions/{fake_request}", None, "Delete"),
    ):
        missing_status, missing = _http_json(
            base_url, path, method=method, token=None, body=body
        )
        invalid_status, invalid = _http_json(
            base_url, path, method=method, token="invalid-token", body=body
        )
        checks[f"missing{label}BearerRejected"] = (
            missing_status == HTTPStatus.UNAUTHORIZED
            and missing.get("code") == "AUTHENTICATION_REQUIRED"
        )
        checks[f"invalid{label}BearerRejected"] = (
            invalid_status == HTTPStatus.UNAUTHORIZED
            and invalid.get("code") == "INVALID_ACCESS_TOKEN"
        )
    foreign_status, foreign_body = _http_json(
        base_url,
        "/v1/archivist-ingestions",
        method="POST",
        token=foreign.token,
        body=_request_body(first),
    )
    changed_status, changed = _http_json(
        base_url,
        "/v1/archivist-ingestions",
        method="POST",
        token=first.token,
        body=_request_body(first, result_sha256="f" * 64),
    )
    missing_source_status, missing_source = _http_json(
        base_url,
        "/v1/archivist-ingestions",
        method="POST",
        token=first.token,
        body={
            "schemaVersion": 1,
            "jobId": "missing-source",
            "expectedResultSha256": first.result_sha256,
        },
    )
    checks.update(
        {
            "authenticatedHttpExact": all(checks.values()),
            "ownerIsolationExact": (
                foreign_status == HTTPStatus.NOT_FOUND
                and foreign_body.get("code") == "ARCHIVIST_SOURCE_NOT_FOUND"
            ),
            "sourceDriftFailedClosed": (
                changed_status == HTTPStatus.CONFLICT
                and changed.get("code") == "ARCHIVIST_SOURCE_CHANGED"
                and missing_source_status == HTTPStatus.NOT_FOUND
                and missing_source.get("code") == "ARCHIVIST_SOURCE_NOT_FOUND"
            ),
        }
    )
    return checks


def _hold_server_io(
    client: AgentAdmissionClient,
    *,
    tenant_id: str,
) -> AgentAdmissionTicket:
    ticket = client.new_ticket()
    admitted = client.submit(
        ticket,
        principal=AuthenticatedPrincipal(
            tenant_id=tenant_id,
            subject_id="qualification-capacity-holder",
            client_id="archivist-product-qualification",
            scopes=frozenset(),
        ),
        work=_ARCHIVIST_WORK,
        source_sha256="8" * 64,
        remaining_deadline_ms=120_000,
    )
    if (
        admitted.outcome != "admitted"
        or admitted.route != ExecutionRoute.SERVER_IO
        or admitted.provider_generation is not None
    ):
        raise RuntimeError("Archivist cancellation capacity hold was not admitted")
    return ticket


def _run_cancelled_request(
    *,
    base_url: str,
    seed: _SeededRecording,
    admission: _ObservedAdmission,
    raw_admission: AgentAdmissionClient,
    tenant_id: str,
) -> ArchivistProductObservation:
    hold = _hold_server_io(raw_admission, tenant_id=tenant_id)
    started = time.monotonic()
    try:
        initial = _submit_product_request(base_url, seed)
        admission.wait_for_submit_count(10, timeout_seconds=10)
        status, value = _http_json(
            base_url,
            f"/v1/archivist-ingestions/{initial.request_id}",
            method="DELETE",
            token=seed.token,
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Archivist product cancellation was not accepted")
        _parse_product_view(value)
        observed = _wait_for_terminal(
            base_url,
            request_id=initial.request_id,
            token=seed.token,
        )
        exact = observed.terminal_shape() == ("cancelled", "client-cancelled")
        return ArchivistProductObservation(
            label="cancelled",
            owner_id=seed.owner_id,
            job_id=seed.job_id,
            product_request_id=observed.request_id,
            observed=observed,
            expected_status="cancelled",
            duration_milliseconds=max(0, int((time.monotonic() - started) * 1_000)),
            exact_match=exact,
            failure_kind=None if exact else "terminal-mismatch",
        )
    finally:
        completed = raw_admission.complete(hold)
        if completed.outcome != "completed":
            raise RuntimeError("Archivist cancellation capacity hold was not contained")


def _foreign_request_isolation(
    base_url: str,
    *,
    request_id: str,
    foreign_token: str,
) -> bool:
    get_status, get_body = _http_json(
        base_url,
        f"/v1/archivist-ingestions/{request_id}",
        method="GET",
        token=foreign_token,
    )
    delete_status, delete_body = _http_json(
        base_url,
        f"/v1/archivist-ingestions/{request_id}",
        method="DELETE",
        token=foreign_token,
    )
    return (
        get_status == HTTPStatus.NOT_FOUND
        and get_body.get("code") == "ARCHIVIST_INGESTION_NOT_FOUND"
        and delete_status == HTTPStatus.NOT_FOUND
        and delete_body.get("code") == "ARCHIVIST_INGESTION_NOT_FOUND"
    )


def _run_product_workload(
    *,
    base_url: str,
    seeded: _SeededJobs,
    runtime: _ProductRuntime,
    admission_socket_path: Path,
    tenant_id: str,
) -> tuple[
    tuple[ArchivistProductObservation, ...],
    tuple[ArchivistProductObservation, ...],
    Mapping[str, bool],
]:
    probes = _probe_http_and_source_authority(base_url, seeded.seeds)
    normal = _run_normal_wave(base_url, seeded.seeds[:8])
    if len(normal) != 8:
        raise RuntimeError("Archivist product normal wave cardinality differs")
    first = normal[0]
    if first.observed is None or first.product_request_id is None:
        raise RuntimeError("Archivist product first normal observation is absent")
    probes = {
        **probes,
        "ownerIsolationExact": probes["ownerIsolationExact"]
        and _foreign_request_isolation(
            base_url,
            request_id=first.product_request_id,
            foreign_token=seeded.seeds[1].token,
        ),
    }
    replay = _run_normal_request(
        base_url=base_url,
        seed=seeded.seeds[0],
        label="replay",
    )
    if replay.observed is not None:
        replay = replace(
            replay,
            exact_match=(
                replay.exact_match
                and replay.observed.staged_identity()
                == first.observed.staged_identity()
            ),
        )
    raw_admission = AgentAdmissionClient(
        UnixAgentAdmissionTransport(admission_socket_path)
    )
    cancelled = _run_cancelled_request(
        base_url=base_url,
        seed=seeded.seeds[8],
        admission=runtime.admission,
        raw_admission=raw_admission,
        tenant_id=tenant_id,
    )
    return (*normal, replay, cancelled), normal, probes


def _evaluate_product_observations(
    observations: Sequence[ArchivistProductObservation],
    *,
    normal_observations: Sequence[ArchivistProductObservation],
    acceptance: ArchivistProductAcceptance,
    probes: Mapping[str, bool],
    admission: Mapping[str, object],
    database_state: Mapping[str, int | bool],
    worker_containment_met: bool,
) -> dict[str, int | bool]:
    staged = sum(
        item.observed is not None and item.observed.status == "staged"
        for item in observations
    )
    cancelled = sum(
        item.observed is not None and item.observed.status == "cancelled"
        for item in observations
    )
    exact = sum(item.exact_match for item in observations)
    request_ids = {
        item.product_request_id
        for item in observations
        if item.product_request_id is not None
    }
    normal_durations = sorted(
        item.duration_milliseconds for item in normal_observations
    )
    p95 = (
        normal_durations[max(0, math.ceil(len(normal_durations) * 0.95) - 1)]
        if normal_durations
        else acceptance.maximum_normal_p95_milliseconds + 1
    )
    single_lease = (
        admission.get("newTicketCount") == acceptance.request_count
        and admission.get("submitCount") == acceptance.request_count
        and admission.get("completeCount") == acceptance.staged_count
        and admission.get("cancelCount") == acceptance.cancelled_count
        and admission.get("acknowledgeCount") == acceptance.cancelled_count
        and admission.get("allWorkIdentityExact") is True
        and admission.get("allTerminalExact") is True
        and database_state.get("admissionSourceBindingExact") is True
    )
    public: dict[str, int | bool] = {
        "caseCount": len({item.job_id for item in observations}),
        "ownerCount": len({item.owner_id for item in normal_observations}),
        "requestCount": len(observations),
        "synchronizedOwnerCount": len(
            {item.owner_id for item in normal_observations if item.exact_match}
        ),
        "stagedCount": staged,
        "cancelledCount": cancelled,
        "exactTerminalCount": exact,
        "uniqueProductRequestIdCount": len(request_ids),
        "reviewedCaptureCount": int(database_state["reviewedCaptureCount"]),
        "sourceAdmissionCount": int(database_state["sourceAdmissionCount"]),
        "stagedGenerationCount": int(database_state["stagedGenerationCount"]),
        "activeGenerationCount": int(database_state["activeGenerationCount"]),
        "maximumNormalP95Milliseconds": acceptance.maximum_normal_p95_milliseconds,
        "normalP95WithinBound": p95 <= acceptance.maximum_normal_p95_milliseconds,
        "authenticatedHttpExact": probes.get("authenticatedHttpExact") is True,
        "ownerIsolationExact": probes.get("ownerIsolationExact") is True,
        "sourceDriftFailedClosed": probes.get("sourceDriftFailedClosed") is True,
        "exactReplayReused": database_state.get("exactReplayReused") is True,
        "serverDerivedReviewExact": (
            database_state.get("serverDerivedReviewExact") is True
        ),
        "noActivationExact": database_state.get("noActivationExact") is True,
        "httpCancellationFailedClosed": (
            cancelled == 1 and database_state.get("cancelledGenerationAbsent") is True
        ),
        "singleLeasePerRequestExact": single_lease,
        "brokerIdentityUnchanged": probes.get("brokerIdentityUnchanged") is True,
        "workerContainmentMet": worker_containment_met,
    }
    expected = acceptance.expected_public_evidence()
    expected.pop("qualified")
    public["qualified"] = all(
        public.get(key) == value for key, value in expected.items()
    )
    return public


def _install_and_preflight_database(dsn: str, *, tenant_id: str) -> None:
    with psycopg.connect(dsn) as connection:
        install_reviewed_capture_schema(connection)
        install_knowledge_schema(connection)
        counts = connection.execute(
            """SELECT
                (SELECT count(*) FROM yap_knowledge_reviewed_captures WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_source_admissions WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_builds WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_active_builds WHERE tenant_id = %s)""",
            (tenant_id, tenant_id, tenant_id, tenant_id),
        ).fetchone()
    if counts != (0, 0, 0, 0):
        raise RuntimeError("Archivist product qualification tenant is not fresh")


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    return parsed


def _reviewed_source_contract_exact(
    *,
    tenant_id: str,
    seed: _SeededRecording,
    capture_sha256: object,
    review_sha256: object,
    normalized_okf_sha256: object,
    normalized_okf: object,
    result_payload: object,
) -> bool:
    if (
        not isinstance(capture_sha256, str)
        or _SHA256.fullmatch(capture_sha256) is None
        or not isinstance(review_sha256, str)
        or _SHA256.fullmatch(review_sha256) is None
        or not isinstance(normalized_okf_sha256, str)
        or _SHA256.fullmatch(normalized_okf_sha256) is None
        or not isinstance(normalized_okf, str)
        or not isinstance(result_payload, dict)
        or result_revision_sha256(result_payload) != seed.result_sha256
    ):
        return False
    if not normalized_okf.startswith("---\n") or "\n---\n" not in normalized_okf[4:]:
        return False
    encoded_frontmatter, _body = normalized_okf[4:].split("\n---\n", 1)
    try:
        frontmatter = yaml.safe_load(encoded_frontmatter)
    except yaml.YAMLError:
        return False
    if not isinstance(frontmatter, dict):
        return False
    reviewed_at = frontmatter.get("timestamp")
    reviewed_at_utc = _parse_utc_timestamp(reviewed_at)
    result_created_at = _parse_utc_timestamp(result_payload.get("createdAtUtc"))
    session_id = result_payload.get("sessionId")
    if (
        reviewed_at_utc is None
        or result_created_at is None
        or reviewed_at_utc < result_created_at
        or reviewed_at_utc > datetime.now(timezone.utc) + timedelta(seconds=5)
        or not isinstance(session_id, str)
        or _OPAQUE_ID.fullmatch(session_id) is None
    ):
        return False
    expected_review_sha256 = _canonical_json_sha256(
        {
            "schemaVersion": 2,
            "reviewer": {
                "tenantId": tenant_id,
                "subjectId": seed.owner_id,
            },
            "reviewedAtUtc": reviewed_at,
            "jobId": seed.job_id,
            "title": seed.title,
            "resultRevisionSha256": seed.result_sha256,
            "decision": "accepted",
        }
    )
    expected_frontmatter = {
        "type": "Meeting",
        "title": seed.title,
        "resource": f"yap://tenant/{tenant_id}/meeting/{seed.job_id}",
        "timestamp": reviewed_at,
        "yap_schema": 1,
        "provenance": {
            "source": "server-authoritative-meeting-result",
            "source_revision": seed.result_sha256,
            "result_sha256": seed.result_sha256,
            "review_sha256": expected_review_sha256,
            "job_id": seed.job_id,
            "session_id": session_id,
            "owner": {
                "tenant_id": tenant_id,
                "subject_id": seed.owner_id,
            },
            "reviewer": {
                "tenant_id": tenant_id,
                "subject_id": seed.owner_id,
            },
        },
    }
    canonical_frontmatter = yaml.safe_dump(
        expected_frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    expected_okf = (
        f"---\n{canonical_frontmatter}\n---\n# Transcript\n\n{seed.transcript}\n"
    )
    expected_normalized_sha256 = hashlib.sha256(
        expected_okf.encode("utf-8")
    ).hexdigest()
    expected_capture_sha256 = hashlib.sha256(
        "\0".join(
            (
                tenant_id,
                seed.owner_id,
                seed.job_id,
                seed.result_sha256,
                expected_review_sha256,
                expected_normalized_sha256,
            )
        ).encode("utf-8")
    ).hexdigest()
    return (
        review_sha256 == expected_review_sha256
        and normalized_okf == expected_okf
        and normalized_okf_sha256 == expected_normalized_sha256
        and capture_sha256 == expected_capture_sha256
    )


def _qualification_request(index: int, *, now: datetime) -> dict[str, object]:
    body = bytes(320)
    chunk_sha256 = hashlib.sha256(body).hexdigest()
    session_id = f"archivist-q-session-{index}"
    capture_sha256 = hashlib.sha256(f"capture-{index}".encode()).hexdigest()
    started = (
        (now - timedelta(minutes=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    retention = (
        (now + timedelta(days=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    return {
        "displayName": f"Archivist qualification review {index}",
        "metadata": {
            "sessionId": session_id,
            "mode": "meeting",
            "origin": "imported_file",
            "triggerMode": "toggle",
            "startedAtUtc": started,
            "utcOffsetMinutesAtStart": 0,
            "localeHintBcp47": "en-US",
            "countryCodeHint": "US",
            "preferredLanguagesBcp47": ["en-US"],
            "appVersion": "0.1.0",
            "platform": "windows",
            "privacyPolicyVersion": "qualification-private",
            "retentionExpiresAtUtc": retention,
        },
        "languageDecision": {
            "mode": "fixed",
            "languageBcp47": "en-US",
            "disposition": "primary",
        },
        "asrCatalogRevision": _ASR_CATALOG_REVISION,
        "tracks": [
            {
                "trackId": "track-1",
                "source": {"kind": "imported", "provenance": "unknown"},
                "deviceId": None,
                "originalSampleRateHz": 16000,
                "originalChannels": 1,
            }
        ],
        "route": "server_batch",
        "captureManifest": {
            "schemaVersion": 2,
            "sessionId": session_id,
            "sha256": capture_sha256,
            "byteLength": 4096,
        },
        "preprocessingEvidence": {
            "schemaVersion": 2,
            "normalization": {
                "status": "complete",
                "componentId": "yap-imported-audio-normalizer",
                "componentRevision": "canonical-pcm16-normalization-v1",
                "method": "canonical_pcm16_identity",
                "inputSourceSha256": chunk_sha256,
                "sourcePcmSha256": chunk_sha256,
                "outputPcmSha256": chunk_sha256,
                "audioCodec": "pcm_s16le",
                "sampleRateHz": 16000,
                "channels": 1,
                "sourceSampleCount": 160,
                "outputSampleCount": 160,
                "paddingSamples": 0,
                "gainAppliedMilliDb": 0,
                "samplesModified": 0,
                "sourceTimePreserved": True,
            },
            "vad": {
                "status": "complete",
                "component": {
                    "id": "sherpa-onnx-silero-vad",
                    "revision": "sherpa-onnx-1.13.4",
                    "modelId": "k2-fsa/silero_vad.onnx",
                    "modelRevision": "github-release-asset-271935959",
                    "artifactSha256": (
                        "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
                    ),
                },
                "sourceSampleCount": 160,
                "intervals": [
                    {
                        "startSample": 0,
                        "endSampleExclusive": 160,
                        "startMs": 0,
                        "endMs": 10,
                    }
                ],
            },
        },
        "chunks": [
            {
                "replayKey": {
                    "schemaVersion": 1,
                    "sessionId": session_id,
                    "trackId": "track-1",
                    "sequenceStart": 0,
                    "sequenceEnd": 159,
                },
                "contentIdentity": {"sha256": chunk_sha256, "byteLength": 320},
                "audioCodec": "pcm_s16le",
                "sampleRateHz": 16000,
                "channels": 1,
                "startMs": 0,
                "durationMs": 10,
            }
        ],
    }


def _qualification_result(*, transcript: str) -> dict[str, object]:
    return {
        "transcript": {
            "text": transcript,
        },
        "model": {
            "id": "qualification-private-asr",
            "revision": _ASR_MODEL_REVISION,
        },
    }


def _seed_recording_jobs(root: Path, *, tenant_id: str) -> _SeededJobs:
    processor = _QualificationJobProcessor()
    service = RecordingJobService(
        root,
        processor=processor,
        supported_languages=("en-US",),
        now=_now_utc,
        startup_worker_cleanup_verified=True,
        development_principal=None,
    )
    seeds = []
    tokens: dict[str, str] = {}
    now = datetime.now(timezone.utc)
    for index in range(9):
        owner_id = f"archivist-owner-{index % 8}"
        principal = AuthenticatedPrincipal(
            tenant_id=tenant_id,
            subject_id=owner_id,
            client_id="archivist-product-qualification",
            scopes=frozenset({"knowledge.ingest"}),
        )
        token = tokens.setdefault(owner_id, f"archivist-{secrets.token_hex(24)}")
        owned = service.for_principal(principal)
        request = _qualification_request(index, now=now)
        created = owned.create(request, idempotency_key=f"archivist-q-create-{index}")
        job_id = created["jobId"]
        if not isinstance(job_id, str):
            raise RuntimeError("qualification recording job identity is invalid")
        transcript = f"Reviewed qualification decision {index}."
        result = _qualification_result(transcript=transcript)
        processor.plan(job_id, result)
        chunk = request["chunks"][0]
        assert isinstance(chunk, dict)
        replay_key = chunk["replayKey"]
        content = chunk["contentIdentity"]
        assert isinstance(replay_key, dict) and isinstance(content, dict)
        chunk_replay_key = (
            f"{replay_key['schemaVersion']}/{replay_key['sessionId']}/"
            f"{replay_key['trackId']}/{replay_key['sequenceStart']}/"
            f"{replay_key['sequenceEnd']}"
        )
        plan = owned.prepare_chunk_upload(
            job_id,
            track_id=str(replay_key["trackId"]),
            sequence_start=int(replay_key["sequenceStart"]),
            sequence_end=int(replay_key["sequenceEnd"]),
            idempotency_key=chunk_replay_key,
            content_sha256=str(content["sha256"]),
            audio_codec=str(chunk["audioCodec"]),
            sample_rate_hz=int(chunk["sampleRateHz"]),
            channels=int(chunk["channels"]),
            content_length=int(content["byteLength"]),
        )
        owned.accept_chunk(plan, bytes(320))
        owned.commit(
            job_id,
            {"captureManifest": request["captureManifest"], "chunkCount": 1},
        )
        deadline = time.monotonic() + 5
        while True:
            projection = owned.get(job_id)
            if projection["status"] in {"complete", "partial"}:
                break
            if projection["status"] in {"failed", "cancelled"}:
                raise RuntimeError(
                    "qualification recording job failed: "
                    f"{projection.get('error', {}).get('code', projection['status'])}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError("qualification recording job did not complete")
            time.sleep(0.01)
        durable_result = owned.get_result(job_id)
        result_sha256 = result_revision_sha256(durable_result)
        seeds.append(
            _SeededRecording(
                owner_id=owner_id,
                principal=principal,
                token=token,
                job_id=job_id,
                result_sha256=result_sha256,
                title=str(created["displayName"]),
                transcript=transcript,
            )
        )
    service.begin_runtime_shutdown()
    restarted = RecordingJobService(
        root,
        processor=processor,
        supported_languages=("en-US",),
        now=_now_utc,
        startup_worker_cleanup_verified=True,
        development_principal=None,
    )
    return _SeededJobs(
        jobs=restarted,
        storage_root=root,
        processor=processor,
        seeds=tuple(seeds),
        tokens_by_owner=tokens,
    )


def _build_product_runtime(
    *,
    jobs: RecordingJobService,
    dsn_path: Path,
    admission_socket_path: Path,
) -> _ProductRuntime:
    admission = _ObservedAdmission(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    )
    connection_factory = private_postgres_connection_factory(dsn_path)
    core = ArchivistService(
        admission=admission,
        processor=PostgresArchivistProcessor(connection_factory),
    )
    runner = PostgresArchivistIngestionRunner(
        jobs=jobs,
        connection_factory=connection_factory,
        archivist=core,
    )
    return _ProductRuntime(
        service=ArchivistIngestionService(runner=runner),
        admission=admission,
    )


def _start_http_server(
    runtime: _ProductRuntime,
    authenticator: _QualificationAuthenticator,
    jobs: RecordingJobService,
):
    settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id="11111111-1111-4111-8111-111111111111",
            audience="22222222-2222-4222-8222-222222222222",
            required_scope="knowledge.ingest",
            allowed_client_ids=("33333333-3333-4333-8333-333333333333",),
            identity_storage_dir=Path("qualification-private-identity"),
        ),
    )
    server = create_server(
        settings,
        request_authenticator=authenticator,
        job_service=jobs,
        archivist_ingestion_service=runtime.service,
    )
    host, port = server.server_address[:2]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        name="archivist-product-http",
        daemon=False,
    )
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_http_server(server, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("Archivist product HTTP worker was not contained")


def _verify_database_state(
    dsn: str,
    *,
    tenant_id: str,
    seeds: Sequence[_SeededRecording],
    observations: Sequence[ArchivistProductObservation],
    admission: Mapping[str, object],
) -> dict[str, int | bool]:
    with psycopg.connect(dsn) as connection:
        captures = connection.execute(
            """SELECT owner_id, job_id, capture_sha256, result_sha256,
                      review_sha256, normalized_okf_sha256, normalized_okf,
                      result_payload
               FROM yap_knowledge_reviewed_captures
               WHERE tenant_id = %s ORDER BY owner_id, job_id""",
            (tenant_id,),
        ).fetchall()
        admissions = connection.execute(
            """SELECT source_identity_sha256, admission_sha256, generation_sha256
               FROM yap_knowledge_source_admissions
               WHERE tenant_id = %s ORDER BY source_identity_sha256""",
            (tenant_id,),
        ).fetchall()
        builds = connection.execute(
            """SELECT generation_sha256, source_admission_sha256, concept_count,
                      permission_count
               FROM yap_knowledge_builds
               WHERE tenant_id = %s ORDER BY generation_sha256""",
            (tenant_id,),
        ).fetchall()
        active_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_active_builds WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()[0]
        activation_history_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_activation_history WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()[0]
    capture_by_job = {str(row[1]): row for row in captures}
    server_derived = len(capture_by_job) == len(seeds)
    for seed in seeds:
        row = capture_by_job.get(seed.job_id)
        if row is None:
            server_derived = False
            continue
        (
            owner_id,
            job_id,
            capture_sha256,
            stored_result_sha256,
            review_sha256,
            normalized_okf_sha256,
            normalized_okf,
            result_payload,
        ) = row
        server_derived = server_derived and (
            owner_id == seed.owner_id
            and job_id == seed.job_id
            and stored_result_sha256 == seed.result_sha256
            and _reviewed_source_contract_exact(
                tenant_id=tenant_id,
                seed=seed,
                capture_sha256=capture_sha256,
                review_sha256=review_sha256,
                normalized_okf_sha256=normalized_okf_sha256,
                normalized_okf=normalized_okf,
                result_payload=result_payload,
            )
        )
    staged = [
        item.observed
        for item in observations
        if item.observed is not None and item.observed.status == "staged"
    ]
    unique_staged = {item.staged_identity() for item in staged}
    replay_exact = len(staged) == 9 and len(unique_staged) == 8
    view_admissions = {
        (item.capture_sha256, item.source_admission_sha256, item.generation_sha256)
        for item in staged
    }
    durable_admissions = {(str(row[0]), str(row[1]), str(row[2])) for row in admissions}
    build_identity = {(str(row[1]), str(row[0])) for row in builds}
    staged_bindings_exact = (
        len(view_admissions) == 8
        and view_admissions == durable_admissions
        and all(
            (admission, generation) in build_identity
            for _, admission, generation in view_admissions
        )
        and all(int(row[2]) == 1 and int(row[3]) == 1 for row in builds)
    )
    cancelled_capture = capture_by_job.get(seeds[8].job_id)
    cancelled_generation_absent = cancelled_capture is not None and str(
        cancelled_capture[2]
    ) not in {str(row[0]) for row in admissions}
    expected_owner_sources = [
        (item.owner_id, str(item.observed.capture_sha256))
        for item in observations
        if item.observed is not None and item.observed.status == "staged"
    ]
    if cancelled_capture is not None:
        expected_owner_sources.append((seeds[8].owner_id, str(cancelled_capture[2])))
    admission_source_binding_exact = admission.get("ownerSourceBindings") == tuple(
        sorted(expected_owner_sources)
    )
    return {
        "reviewedCaptureCount": len(captures),
        "sourceAdmissionCount": len(admissions),
        "stagedGenerationCount": len(builds),
        "activeGenerationCount": int(active_count),
        "serverDerivedReviewExact": server_derived and staged_bindings_exact,
        "noActivationExact": active_count == 0 and activation_history_count == 0,
        "exactReplayReused": replay_exact,
        "cancelledGenerationAbsent": cancelled_generation_absent,
        "admissionSourceBindingExact": admission_source_binding_exact,
    }


def _verify_recording_restart(seeded: _SeededJobs) -> bool:
    seeded.jobs.begin_runtime_shutdown()
    restarted = RecordingJobService(
        seeded.storage_root,
        processor=seeded.processor,
        supported_languages=("en-US",),
        now=_now_utc,
        startup_worker_cleanup_verified=True,
        development_principal=None,
    )
    try:
        return all(
            result_revision_sha256(
                restarted.for_principal(seed.principal).get_result(seed.job_id)
            )
            == seed.result_sha256
            for seed in seeded.seeds
        )
    finally:
        restarted.begin_runtime_shutdown()


def _private_observations(
    observations: Sequence[ArchivistProductObservation],
) -> list[dict[str, object]]:
    return [
        {
            "label": item.label,
            "ownerId": item.owner_id,
            "jobId": item.job_id,
            "productRequestId": item.product_request_id,
            "expectedStatus": item.expected_status,
            "observedStatus": None if item.observed is None else item.observed.status,
            "durationMilliseconds": item.duration_milliseconds,
            "exactMatch": item.exact_match,
            "failureKind": item.failure_kind,
        }
        for item in observations
    ]


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    root = repository_root
    fixed = (
        root / ".github/workflows/ci.yml",
        root / "server/archivist-product-acceptance.json",
        root / "server/agent-reasoning-candidates.lock.json",
        root / "server/agent-service-profiles/rapid-automation.json",
        root / "server/agent-service-profiles/complex-orchestration.json",
        root / "server/runtime/knowledge/postgres-pgvector.lock.json",
        root / "server/pyproject.toml",
        root / "server/uv.lock",
        root / "server/orchestrator/Cargo.toml",
        root / "server/orchestrator/Cargo.lock",
        root / "server/openapi/openapi.json",
        root / "desktop/package.json",
        root / "desktop/pnpm-lock.yaml",
        root / "desktop/pnpm-workspace.yaml",
        root / "desktop/index.html",
        root / "desktop/components.json",
        root / "desktop/src-tauri/Cargo.toml",
        root / "desktop/src-tauri/Cargo.lock",
        root / "desktop/src-tauri/build.rs",
        root / "desktop/src-tauri/rust-toolchain.toml",
        root / "desktop/src-tauri/tauri.conf.json",
        root / "desktop/src-tauri/tauri.wdio.conf.json",
        root / "desktop/tsconfig.json",
        root / "desktop/vite.config.ts",
        root / "desktop/tests/wdio.conf.ts",
        root / "desktop/tests/wdio.required.conf.ts",
        root / "desktop/tests/wdio/smoke.spec.js",
        root / "verification/run-hosted-windows-runtime-check.mjs",
    )
    recursive = tuple(
        sorted(
            (
                path
                for path in (
                    *root.glob("server/src/yap_server/**/*.py"),
                    *root.glob("server/tests/**/*.py"),
                    *root.glob("server/orchestrator/src/**/*.rs"),
                    *root.glob("server/orchestrator/tests/**/*.rs"),
                    *root.glob("desktop/src/**/*.ts"),
                    *root.glob("desktop/src/**/*.tsx"),
                    *root.glob("desktop/src/**/*.css"),
                    *root.glob("desktop/src-tauri/src/**/*.rs"),
                    *root.glob("desktop/src-tauri/tests/**/*.rs"),
                    *root.glob("desktop/src-tauri/capabilities/**/*.json"),
                    *root.glob("desktop/src-tauri/migrations/**/*.*"),
                    *root.glob("desktop/public/**/*.*"),
                    *root.glob("desktop/tests/e2e/**/*.*"),
                    *root.glob("desktop/tests/fixtures/**/*.*"),
                    *root.glob("desktop/tests/unit/**/*.*"),
                    *root.glob("desktop/tests/scripts/**/*.*"),
                    *root.glob("desktop/tests/wdio/**/*.js"),
                )
                if path.is_file()
            ),
            key=lambda path: path.as_posix(),
        )
    )
    paths = tuple(dict.fromkeys((*fixed, *recursive)))
    if any(not path.is_file() for path in paths):
        raise ValueError("Archivist product candidate inputs are incomplete")
    return paths


def _new_private_evidence_destination(path: Path, *, repository_root: Path) -> Path:
    requested = Path(path)
    absolute = Path(os.path.abspath(requested))
    if (
        not requested.is_absolute()
        or requested != absolute
        or requested.exists()
        or requested.is_symlink()
        or requested == repository_root
        or repository_root in requested.parents
    ):
        raise ValueError(
            "Archivist product evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing == existing.parent:
            raise ValueError(
                "Archivist product evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Archivist product evidence destination must be new and outside the repository"
        )
    return requested


def run_archivist_product_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Mapping[str, object]:
    root = repository_root.resolve(strict=True)
    private_destination = _new_private_evidence_destination(
        evidence_destination, repository_root=root
    )
    candidate = admit_checked_candidate(
        repository_root=root,
        checked_head=checked_head,
        input_paths=_candidate_input_paths(root),
        runner=runner,
    )
    _require_private_arm64_host()
    acceptance = load_archivist_product_acceptance(
        root / "server/archivist-product-acceptance.json"
    )
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    rapid_profile = load_rapid_agent_vllm_service_profile(
        root / "server/agent-service-profiles/rapid-automation.json",
        candidate_lock_path,
    )
    complex_profile = load_complex_agent_vllm_service_profile(
        root / "server/agent-service-profiles/complex-orchestration.json",
        candidate_lock_path,
    )
    if rapid_profile.candidate_lock_sha256 != complex_profile.candidate_lock_sha256:
        raise ValueError("Archivist product broker candidate lock identity differs")
    broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"archivist-product-q-{secrets.token_hex(8)}"
    run_id = f"run-{secrets.token_hex(8)}"

    def observe_admission() -> dict[str, object]:
        return observe_admission_broker(
            admission_socket_path,
            expected_binary_sha256=broker_sha256,
            expected_candidate_lock_sha256=rapid_profile.candidate_lock_sha256,
            expected_rapid_profile_sha256=rapid_profile.profile_sha256,
            expected_rapid_state_path=rapid_state_path,
            expected_complex_profile_sha256=complex_profile.profile_sha256,
            expected_complex_state_path=complex_state_path,
        )

    capacity = _probe_server_io_capacity(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        tenant_id=tenant_id,
        run_scope=run_id,
        observe_broker_state=observe_admission,
    )
    database_lock = load_knowledge_database_runtime_lock(root)
    database = OwnedPostgresKnowledgeRuntime(
        checked_head=checked_head,
        runtime_lock=database_lock,
        runner=runner,
    )
    started: StartedKnowledgeDatabase | None = None
    runtime: _ProductRuntime | ArchivistRuntime | None = None
    server = None
    server_thread: threading.Thread | None = None
    seeded: _SeededJobs | None = None
    observations: tuple[ArchivistProductObservation, ...] | None = None
    normal: tuple[ArchivistProductObservation, ...] | None = None
    probes: Mapping[str, bool] | None = None
    admission: Mapping[str, object] | None = None
    database_state: Mapping[str, int | bool] | None = None
    teardown: Mapping[str, bool] | None = None
    worker_containment_met = False
    recording_restart_exact = False
    try:
        started = database.start(timeout_seconds=120)
        _install_and_preflight_database(started.dsn, tenant_id=tenant_id)
        with tempfile.TemporaryDirectory(
            prefix="yap-archivist-product-qualification-"
        ) as value:
            private_root = Path(value)
            if os.name == "posix":
                private_root.chmod(0o700)
            seeded = _seed_recording_jobs(
                private_root / "recording-jobs", tenant_id=tenant_id
            )
            restarted = _restart_database(database, started)
            started = restarted
            dsn_path = private_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, restarted.dsn)
            runtime = _build_product_runtime(
                jobs=seeded.jobs,
                dsn_path=dsn_path,
                admission_socket_path=admission_socket_path,
            )
            authenticator = _QualificationAuthenticator(
                tenant_id=tenant_id,
                tokens={
                    token: owner for owner, token in seeded.tokens_by_owner.items()
                },
            )
            server, server_thread, base_url = _start_http_server(
                runtime, authenticator, seeded.jobs
            )
            workload_broker_before = observe_admission()
            observations, normal, probes = _run_product_workload(
                base_url=base_url,
                seeded=seeded,
                runtime=runtime,
                admission_socket_path=admission_socket_path,
                tenant_id=tenant_id,
            )
            workload_broker_after = observe_admission()
            probes = {
                **probes,
                "brokerIdentityUnchanged": (
                    workload_broker_before == workload_broker_after
                ),
            }
            admission = runtime.admission.snapshot()
            _stop_http_server(server, server_thread)
            server = None
            server_thread = None
            runtime.close()
            runtime = None
            worker_containment_met = True
            recording_restart_exact = _verify_recording_restart(seeded)
            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            database_state = _verify_database_state(
                result_restarted.dsn,
                tenant_id=tenant_id,
                seeds=seeded.seeds,
                observations=observations,
                admission=admission,
            )
        teardown = database.stop(timeout_seconds=15)
        _require_exact_teardown(teardown)
        started = None
    except BaseException as error:
        cleanup_error: BaseException | None = None
        if server is not None and server_thread is not None:
            try:
                _stop_http_server(server, server_thread)
            except BaseException as close_error:
                cleanup_error = close_error
        if runtime is not None:
            try:
                runtime.close()
            except BaseException as close_error:
                cleanup_error = cleanup_error or close_error
        if started is not None:
            try:
                database.contain_failed_run()
            except BaseException as database_error:
                cleanup_error = cleanup_error or database_error
        if cleanup_error is not None:
            raise cleanup_error from error
        raise
    if any(
        value is None
        for value in (
            seeded,
            observations,
            normal,
            probes,
            admission,
            database_state,
            teardown,
        )
    ):
        raise RuntimeError("Archivist product qualification evidence is incomplete")
    assert observations is not None
    assert normal is not None
    assert probes is not None
    assert admission is not None
    assert database_state is not None
    assert teardown is not None
    public = _evaluate_product_observations(
        observations,
        normal_observations=normal,
        acceptance=acceptance,
        probes=probes,
        admission=admission,
        database_state=database_state,
        worker_containment_met=worker_containment_met,
    )
    if public["qualified"] is not True or not recording_restart_exact:
        raise RuntimeError("Archivist product qualification did not meet acceptance")
    candidate.verify_unchanged(runner=runner)
    semantic: dict[str, object] = dict(public)
    semantic.update(
        {
            "schemaVersion": 1,
            "qualificationScope": "archivist-authenticated-product-vertical",
            "outcome": "archivist-authenticated-product-vertical-qualified",
            "acceptancePlanSha256": acceptance.plan_sha256,
            "qualificationTenantSha256": hashlib.sha256(
                tenant_id.encode("utf-8")
            ).hexdigest(),
            "qualificationRunSha256": hashlib.sha256(
                run_id.encode("utf-8")
            ).hexdigest(),
            "workload": {
                "route": "server-io",
                "schedulingClass": "background-io",
                "synchronizedAuthenticatedClientCallCount": 8,
                "brokerActiveCapacity": capacity["admittedOwnerCount"],
                "brokerExpectedCapacityObserved": capacity["expectedCapacityObserved"],
                "overflowOwnerQueued": capacity["overflowOwnerQueued"],
                "capacityProbeContained": capacity["contained"],
                "capacityProbeBrokerIdentityUnchanged": capacity[
                    "brokerIdentityUnchanged"
                ],
                "observedProductModelRouteLeaseRequestsAbsent": public[
                    "singleLeasePerRequestExact"
                ],
            },
            "knowledge": {
                **database_state,
                "recordingJobRestartReadbackExact": recording_restart_exact,
                "runtimeLockSha256": database_lock.lock_sha256,
                "teardown": dict(teardown),
            },
            "product": {
                "rendererLocalRecordingIdentityContractBound": True,
                "nativeServerJobAndResultResolutionContractBound": True,
                "stagedGenerationActivationAbsent": True,
            },
            "closure": {
                "nativeRustExactHeadRequired": True,
                "nativeWdioExactHeadRequired": True,
                "rendererBuildAndUnitExactHeadRequired": True,
                "hostedReviewAndMergeRequired": True,
            },
        }
    )
    receipt = bind_checked_candidate_evidence(semantic, candidate)
    write_new_private_json_evidence(
        private_destination,
        {
            "schemaVersion": 1,
            "privacyScope": "private-archivist-product-qualification",
            "tenantId": tenant_id,
            "qualificationRunId": run_id,
            "publicEvidence": receipt,
            "qualification": {
                "acceptancePlanSha256": acceptance.plan_sha256,
                "observations": _private_observations(observations),
            },
        },
    )
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify the authenticated Archivist product vertical"
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--evidence-destination", type=Path, required=True)
    parser.add_argument("--admission-socket", type=Path, required=True)
    parser.add_argument("--rapid-state", type=Path, required=True)
    parser.add_argument("--complex-state", type=Path, required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    receipt = run_archivist_product_qualification_gate(
        repository_root=options.repository_root,
        checked_head=options.checked_head,
        evidence_destination=options.evidence_destination,
        admission_socket_path=options.admission_socket,
        rapid_state_path=options.rapid_state,
        complex_state_path=options.complex_state,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True), flush=True)
    return (
        0
        if receipt["outcome"] == "archivist-authenticated-product-vertical-qualified"
        else 1
    )


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError(
            "Archivist product qualification requires the private ARM64 host"
        )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ArchivistProductAcceptance",
    "ArchivistProductObservation",
    "ArchivistProductView",
    "load_archivist_product_acceptance",
    "main",
    "run_archivist_product_qualification_gate",
]
