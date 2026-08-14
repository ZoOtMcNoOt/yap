"""Qualify the authenticated Coordinator proposal-bundle product boundary."""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
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

from yap_server.agents.admission_client import AgentAdmissionClient
from yap_server.agents.admission_protocol import (
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
    UnixAgentAdmissionTransport,
)
from yap_server.agents.coordinator import (
    CoordinatorEvidencePack,
    CoordinatorRequest,
    coordinator_request_sha256,
    coordinator_work_sha256,
)
from yap_server.agents.coordinator_bundle_service import CoordinatorBundleService
from yap_server.agents.coordinator_product_runtime import (
    CoordinatorProductRuntime,
    build_coordinator_product_runtime,
)
from yap_server.agents.coordinator_result_audit import (
    CoordinatorRuntimeAuditIdentity,
    PostgresCoordinatorResultAuditor,
)
from yap_server.agents.coordinator_runtime import (
    COORDINATOR_ADMISSION_SOCKET,
    COORDINATOR_CANDIDATE_LOCK,
    COORDINATOR_KNOWLEDGE_DSN_FILE,
    COORDINATOR_PROFILE,
    COORDINATOR_RUNTIME,
    load_coordinator_service_profile,
)
from yap_server.agents.coordinator_service import CoordinatorService
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
)
from yap_server.api.app import create_server
from yap_server.auth import AuthenticatedPrincipal, AuthenticationFailure
from yap_server.config import ServerAuthenticationSettings, ServerSettings
from yap_server.evaluation.agent_admission_broker_observation import (
    build_checked_admission_broker,
    observe_admission_broker,
    probe_agent_admission_broker_capacity,
)
from yap_server.evaluation.agent_service_lifecycle_observation import (
    probe_exact_service,
    read_service_state,
    validate_state_identity,
)
from yap_server.evaluation.checked_candidate import (
    admit_checked_candidate,
    bind_checked_candidate_evidence,
)
from yap_server.evaluation.owned_postgres_knowledge_runtime import (
    OwnedPostgresKnowledgeRuntime,
    StartedKnowledgeDatabase,
    load_knowledge_database_runtime_lock,
)
from yap_server.evaluation.private_json_evidence import write_new_private_json_evidence
from yap_server.knowledge.knowledge_proposals import PostgresCoordinatorEvidenceReader
from yap_server.knowledge.knowledge_tool_contract import KnowledgeToolCancelled
from yap_server.pools.agent_vllm_service_profile import (
    RAPID_AUTOMATION_PROFILE_SHA256,
    AgentVllmServiceProfile,
)
from yap_server.private_artifact import read_json_object_with_identity
from yap_server.private_postgres_connection import private_postgres_connection_factory

from .coordinator_qualification import (
    CoordinatorBoundQualificationCorpus,
    CoordinatorExpectedView,
    CoordinatorQualificationInvocation,
    bind_coordinator_curator_lineage,
    build_coordinator_qualification_invocations,
    load_coordinator_qualification_acceptance,
    load_coordinator_qualification_corpus,
    _authorization_hash,
    _permission_hash,
)
from .coordinator_qualification_gate import (
    _InitializedKnowledge,
    _initialize_coordinator_knowledge,
    _provider_generation,
    _publish_curator_proposals,
    _coordinator_result_rows,
    _curator_result_rows,
    _expected_curator_rows,
    _expected_proposal_rows,
    _proposal_rows,
    _require_exact_teardown,
    _require_full_complex_profile,
    _restart_database,
    _sorted_rows,
    _tool_audit_rows,
    _verify_initialized_knowledge,
    _write_new_private_text,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "cancelled", "failed"}
)
_TERMINAL_REASONS = {
    "evidence-unavailable": frozenset(
        {"empty-result", "model-evidence-unavailable", "stale-generation"}
    ),
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
    "failed": frozenset(
        {
            "admission-failed",
            "capacity-unavailable",
            "invalid-output",
            "provider-unavailable",
            "runtime-unavailable",
            "service-unavailable",
            "storage-timeout",
            "storage-unavailable",
            "unauthorized",
        }
    ),
}
_PRODUCT_REQUEST_ID = re.compile(r"^coordinator-bundle-[0-9a-f]{32}$")
_INTERNAL_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_ACCEPTANCE_BYTES = 16 * 1024
_MAXIMUM_HTTP_RESPONSE_BYTES = 1_048_576
_HTTP_TIMEOUT_SECONDS = 25.0
_POLL_INTERVAL_SECONDS = 0.02
_NORMAL_WAVE_TIMEOUT_SECONDS = 100.0
_WORKER_CONTAINMENT_SECONDS = 5.0
_BROKER_ACTIVE_CAPACITY = 8
_MAXIMUM_OUTPUT_TOKENS = 512
_MAXIMUM_INPUT_TOKENS = 7_680
_CROSS_OWNER_ID = "coordinator-product-cross-owner"
_ACCEPTANCE_FIELDS = frozenset(
    {
        "schemaVersion",
        "qualificationScope",
        "qualified",
        "caseCount",
        "ownerCount",
        "queryCount",
        "synchronizedOwnerCount",
        "completeCount",
        "unavailableCount",
        "failedCount",
        "cancelledCount",
        "exactTerminalCount",
        "exactBundleCount",
        "uniqueProductRequestIdCount",
        "maximumNormalP95Milliseconds",
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "serverDerivedBundleExact",
        "serverOwnedCitationsExact",
        "hiddenOnlyIndistinguishable",
        "unavailableBundleAbsent",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    }
)


@dataclass(frozen=True, slots=True)
class CoordinatorProductAcceptance:
    plan_sha256: str
    case_count: int
    owner_count: int
    query_count: int
    synchronized_owner_count: int
    complete_count: int
    unavailable_count: int
    failed_count: int
    cancelled_count: int
    exact_terminal_count: int
    exact_bundle_count: int
    unique_product_request_id_count: int
    maximum_normal_p95_milliseconds: int
    normal_p95_within_bound: bool
    authenticated_http_exact: bool
    owner_isolation_exact: bool
    server_derived_bundle_exact: bool
    server_owned_citations_exact: bool
    hidden_only_indistinguishable: bool
    unavailable_bundle_absent: bool
    http_cancellation_failed_closed: bool
    worker_containment_met: bool

    def expected_public_evidence(self) -> dict[str, int | bool]:
        return {
            "qualified": True,
            "caseCount": self.case_count,
            "ownerCount": self.owner_count,
            "queryCount": self.query_count,
            "synchronizedOwnerCount": self.synchronized_owner_count,
            "completeCount": self.complete_count,
            "unavailableCount": self.unavailable_count,
            "failedCount": self.failed_count,
            "cancelledCount": self.cancelled_count,
            "exactTerminalCount": self.exact_terminal_count,
            "exactBundleCount": self.exact_bundle_count,
            "uniqueProductRequestIdCount": self.unique_product_request_id_count,
            "normalP95WithinBound": self.normal_p95_within_bound,
            "authenticatedHttpExact": self.authenticated_http_exact,
            "ownerIsolationExact": self.owner_isolation_exact,
            "serverDerivedBundleExact": self.server_derived_bundle_exact,
            "serverOwnedCitationsExact": self.server_owned_citations_exact,
            "hiddenOnlyIndistinguishable": self.hidden_only_indistinguishable,
            "unavailableBundleAbsent": self.unavailable_bundle_absent,
            "httpCancellationFailedClosed": self.http_cancellation_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class CoordinatorProductView:
    request_id: str
    status: str
    bundle: CoordinatorProductBundle | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class CoordinatorProductBundle:
    canonical_json: str
    bundle_sha256: str
    citation_sha256: str

    def to_wire(self) -> dict[str, object]:
        value = json.loads(self.canonical_json)
        if not isinstance(value, dict):
            raise ValueError("Coordinator product bundle is invalid")
        return value


@dataclass(frozen=True, slots=True)
class CoordinatorProductObservation:
    label: str
    owner_id: str
    request: CoordinatorRequest
    expected: CoordinatorExpectedView
    product_request_id: str | None
    internal_request_id: str | None
    observed: CoordinatorProductView | None
    duration_milliseconds: int
    exact_match: bool
    authentication_header_exact: bool
    owner_isolation_exact: bool
    normal: bool
    failure_kind: str | None


class _QualificationAuthenticator:
    authentication_required = True
    principal_access_enforced = True

    def __init__(self, *, tenant_id: str, tokens: Mapping[str, str]) -> None:
        self._tenant_id = tenant_id
        self._tokens = dict(tokens)
        self._lock = threading.Lock()
        self._observed_headers: list[str | None] = []

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        with self._lock:
            self._observed_headers.append(authorization)
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
            client_id="coordinator-product-qualification",
            scopes=frozenset({"knowledge.read", "knowledge.bundle"}),
        )

    def observed_header_count(self, authorization: str) -> int:
        with self._lock:
            return self._observed_headers.count(authorization)


class _ActiveProductRequests:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[str, str] = {}

    def add(self, request_id: str, token: str) -> None:
        with self._lock:
            self._requests[request_id] = token

    def remove(self, request_id: str) -> None:
        with self._lock:
            self._requests.pop(request_id, None)

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(self._requests.items())


class _CancellationModel:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def select(self, request, evidence, *, cancellation):
        del request, evidence
        self.started.set()
        if not cancellation.wait(5.0):
            raise RuntimeError("Coordinator product cancellation was not forwarded")
        self.cancelled.set()
        raise KnowledgeToolCancelled("Coordinator product HTTP cancellation")


def load_coordinator_product_acceptance(path: Path) -> CoordinatorProductAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Coordinator product acceptance",
    )
    if set(value) != _ACCEPTANCE_FIELDS:
        raise ValueError("Coordinator product acceptance fields differ")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"]
        != "coordinator-authenticated-product-server-boundary"
        or value["qualified"] is not True
    ):
        raise ValueError("Coordinator product acceptance identity differs")
    integers = {
        "caseCount": 8,
        "ownerCount": 8,
        "queryCount": 10,
        "synchronizedOwnerCount": 8,
        "completeCount": 5,
        "unavailableCount": 4,
        "failedCount": 0,
        "cancelledCount": 1,
        "exactTerminalCount": 10,
        "exactBundleCount": 5,
        "uniqueProductRequestIdCount": 10,
        "maximumNormalP95Milliseconds": 85_000,
    }
    if any(
        type(value[name]) is not int or value[name] != expected
        for name, expected in integers.items()
    ):
        raise ValueError("Coordinator product acceptance counts differ")
    booleans = (
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "serverDerivedBundleExact",
        "serverOwnedCitationsExact",
        "hiddenOnlyIndistinguishable",
        "unavailableBundleAbsent",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    )
    if any(value[name] is not True for name in booleans):
        raise ValueError("Coordinator product acceptance flags differ")
    return CoordinatorProductAcceptance(
        identity,
        *(value[name] for name in integers),
        *(value[name] for name in booleans),
    )


def _parse_product_view(value: object) -> CoordinatorProductView:
    if not isinstance(value, dict):
        raise ValueError("Coordinator product view is invalid")
    status = value.get("status")
    fields = {"schemaVersion", "requestId", "status"}
    if status == "complete":
        fields.add("proposalBundle")
    elif status in _TERMINAL_STATUSES - {"complete"}:
        fields.add("reason")
    elif status not in _ACTIVE_STATUSES:
        raise ValueError("Coordinator product status is invalid")
    if set(value) != fields:
        raise ValueError("Coordinator product view fields differ")
    request_id = value["requestId"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(request_id, str)
        or _PRODUCT_REQUEST_ID.fullmatch(request_id) is None
    ):
        raise ValueError("Coordinator product identity is invalid")
    bundle = _parse_bundle(value["proposalBundle"]) if status == "complete" else None
    reason = value.get("reason")
    if status in _ACTIVE_STATUSES and (bundle is not None or reason is not None):
        raise ValueError("Coordinator product active view is invalid")
    if status == "complete" and (bundle is None or reason is not None):
        raise ValueError("Coordinator product complete view is invalid")
    if status in _TERMINAL_REASONS and reason not in _TERMINAL_REASONS[status]:
        raise ValueError("Coordinator product terminal reason differs")
    return CoordinatorProductView(request_id, str(status), bundle, reason)


def _view_matches_expected(
    observed: CoordinatorProductView,
    expected: CoordinatorExpectedView,
) -> bool:
    expected_bundle = (
        _parse_bundle(expected.bundle.to_wire())
        if expected.bundle is not None
        else None
    )
    return (
        observed.status == expected.status
        and observed.reason == expected.reason
        and observed.bundle == expected_bundle
    )


def _parse_bundle(value: object) -> CoordinatorProductBundle:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "generationSha256",
        "evidenceSha256",
        "items",
        "bundleSha256",
        "citationSha256",
        "canonical",
        "requiresReview",
    }:
        raise ValueError("Coordinator product bundle fields differ")
    items = value["items"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["canonical"] is not False
        or value["requiresReview"] is not True
        or not isinstance(items, list)
        or not 1 <= len(items) <= 5
        or not all(
            isinstance(value[name], str) and _SHA256.fullmatch(value[name]) is not None
            for name in (
                "generationSha256",
                "evidenceSha256",
                "bundleSha256",
                "citationSha256",
            )
        )
    ):
        raise ValueError("Coordinator product bundle identity differs")
    normalized_items = [_parse_bundle_item(item) for item in items]
    if len({item["proposalId"] for item in normalized_items}) != len(normalized_items):
        raise ValueError("Coordinator product proposal identity is duplicated")
    expected_citation_sha256 = _canonical_sha256(
        [
            {"proposalId": item["proposalId"], "citations": item["citations"]}
            for item in normalized_items
        ]
    )
    bundle_value = {
        "schemaVersion": 1,
        "generationSha256": value["generationSha256"],
        "evidenceSha256": value["evidenceSha256"],
        "items": normalized_items,
        "citationSha256": value["citationSha256"],
        "canonical": False,
        "requiresReview": True,
    }
    if value["citationSha256"] != expected_citation_sha256 or value[
        "bundleSha256"
    ] != _canonical_sha256(bundle_value):
        raise ValueError("Coordinator product bundle hash differs")
    normalized = {**bundle_value, "bundleSha256": value["bundleSha256"]}
    return CoordinatorProductBundle(
        _canonical_json(normalized),
        value["bundleSha256"],
        value["citationSha256"],
    )


def _parse_bundle_item(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "proposalId",
        "proposalType",
        "proposedContent",
        "citations",
        "citationSha256",
        "candidateSha256",
    }:
        raise ValueError("Coordinator product bundle item fields differ")
    citations = value["citations"]
    proposed_content = value["proposedContent"]
    if (
        not isinstance(value["proposalId"], str)
        or _SHA256.fullmatch(value["proposalId"]) is None
        or value["proposalType"] != "summary"
        or not isinstance(proposed_content, str)
        or not proposed_content.strip()
        or len(proposed_content) > 4_096
        or not isinstance(citations, list)
        or not 1 <= len(citations) <= 8
        or not isinstance(value["citationSha256"], str)
        or _SHA256.fullmatch(value["citationSha256"]) is None
        or not isinstance(value["candidateSha256"], str)
        or _SHA256.fullmatch(value["candidateSha256"]) is None
    ):
        raise ValueError("Coordinator product bundle item identity differs")
    normalized_citations = [_parse_citation(item).to_wire() for item in citations]
    if value["citationSha256"] != _canonical_sha256(normalized_citations):
        raise ValueError("Coordinator product item citation hash differs")
    return {
        "proposalId": value["proposalId"],
        "proposalType": "summary",
        "proposedContent": proposed_content,
        "citations": normalized_citations,
        "citationSha256": value["citationSha256"],
        "candidateSha256": value["candidateSha256"],
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_citation(value: object) -> LibrarianEvidenceItem:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "contentSha256",
        "charStart",
        "charEnd",
        "text",
    }:
        raise ValueError("Coordinator product citation fields differ")
    return LibrarianEvidenceItem(
        concept_id=value["conceptId"],
        source_revision=value["sourceRevision"],
        content_sha256=value["contentSha256"],
        char_start=value["charStart"],
        char_end=value["charEnd"],
        text=value["text"],
    )


def _http_json(
    base_url: str,
    path: str,
    *,
    method: str,
    token: str | None,
    body: Mapping[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    encoded = None
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url}{path}",
        data=encoded,
        headers=headers,
        method=method,
    )
    try:
        response = urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS)
    except HTTPError as error:
        response = error
    with response:
        payload = response.read(_MAXIMUM_HTTP_RESPONSE_BYTES + 1)
        status = response.status
    if len(payload) > _MAXIMUM_HTTP_RESPONSE_BYTES:
        raise ValueError("Coordinator product HTTP response is too large")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Coordinator product HTTP response is invalid")
    return status, value


def _wait_for_terminal(
    base_url: str,
    request_id: str,
    *,
    token: str,
    timeout_seconds: float = 90.0,
) -> CoordinatorProductView:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, value = _http_json(
            base_url,
            f"/v1/coordinator-bundles/{request_id}",
            method="GET",
            token=token,
        )
        if status != HTTPStatus.OK:
            raise RuntimeError("Coordinator product status request failed")
        view = _parse_product_view(value)
        if view.request_id != request_id:
            raise RuntimeError("Coordinator product request identity changed")
        if view.status in _TERMINAL_STATUSES:
            return view
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError("Coordinator product request did not become terminal")


def _foreign_owner_isolation_exact(
    base_url: str,
    request_id: str,
    *,
    foreign_token: str,
) -> bool:
    results = tuple(
        _http_json(
            base_url,
            f"/v1/coordinator-bundles/{request_id}",
            method=method,
            token=foreign_token,
        )
        for method in ("GET", "DELETE")
    )
    return all(
        status == HTTPStatus.NOT_FOUND
        and value.get("code") == "COORDINATOR_BUNDLE_NOT_FOUND"
        for status, value in results
    )


def _probe_http_authentication(
    base_url: str,
    *,
    request: CoordinatorRequest,
) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    status, health = _http_json(
        base_url,
        "/v1/health",
        method="GET",
        token=None,
    )
    checks["healthPublicAndCapabilityExact"] = (
        status == HTTPStatus.OK
        and health.get("auth") == "required"
        and isinstance(health.get("capabilities"), dict)
        and health["capabilities"].get("coordinatorBundles") is True
    )
    probes = (
        ("POST", "/v1/coordinator-bundles", request.to_wire()),
        ("GET", "/v1/coordinator-bundles/coordinator-bundle-" + "1" * 32, None),
        ("DELETE", "/v1/coordinator-bundles/coordinator-bundle-" + "1" * 32, None),
    )
    for method, path, body in probes:
        missing_status, missing = _http_json(
            base_url,
            path,
            method=method,
            token=None,
            body=body,
        )
        invalid_status, invalid = _http_json(
            base_url,
            path,
            method=method,
            token="invalid-product-token",
            body=body,
        )
        checks[f"{method.lower()}AuthenticationRequired"] = (
            missing_status == HTTPStatus.UNAUTHORIZED
            and missing.get("code") == "AUTHENTICATION_REQUIRED"
            and invalid_status == HTTPStatus.UNAUTHORIZED
            and invalid.get("code") == "INVALID_ACCESS_TOKEN"
        )
    return checks


def _normal_invocations(
    corpus: CoordinatorBoundQualificationCorpus,
    acceptance,
) -> tuple[CoordinatorQualificationInvocation, ...]:
    invocations = build_coordinator_qualification_invocations(
        corpus.corpus,
        acceptance,
        tenant_id=corpus.tenant_id,
        generation_sha256s=corpus.generation_sha256s,
    )
    first_wave = acceptance.synchronized_waves[0].wave_id
    normal = tuple(
        item
        for item in invocations
        if item.mode == "normal" and item.wave_id == first_wave
    )
    if len(normal) != 8 or len({item.owner_id for item in normal}) != 8:
        raise ValueError("Coordinator product synchronized workload differs")
    return normal


def _submit_product_bundle(
    base_url: str,
    invocation: CoordinatorQualificationInvocation,
    expected: CoordinatorExpectedView,
    *,
    token: str,
    foreign_token: str,
    active_requests: _ActiveProductRequests,
    authenticator: _QualificationAuthenticator,
    barrier: threading.Barrier | None,
    normal: bool,
) -> CoordinatorProductObservation:
    request = CoordinatorRequest(
        objective=invocation.objective,
        maximum_items=invocation.maximum_items,
        expected_generation_sha256=invocation.expected_generation_sha256,
    )
    if barrier is not None:
        try:
            barrier.wait(timeout=_NORMAL_WAVE_TIMEOUT_SECONDS)
        except threading.BrokenBarrierError as error:
            raise RuntimeError("Coordinator product synchronization failed") from error
    started = time.monotonic()
    request_id: str | None = None
    try:
        status, value = _http_json(
            base_url,
            "/v1/coordinator-bundles",
            method="POST",
            token=token,
            body=request.to_wire(),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Coordinator product submission failed")
        accepted = _parse_product_view(value)
        request_id = accepted.request_id
        active_requests.add(request_id, token)
        isolated = _foreign_owner_isolation_exact(
            base_url,
            request_id,
            foreign_token=foreign_token,
        )
        observed = (
            accepted
            if accepted.status in _TERMINAL_STATUSES
            else _wait_for_terminal(base_url, request_id, token=token)
        )
        exact = _view_matches_expected(observed, expected)
        return CoordinatorProductObservation(
            invocation.case_id,
            invocation.owner_id,
            request,
            expected,
            request_id,
            None,
            observed,
            _duration(started),
            exact,
            authenticator.observed_header_count(f"Bearer {token}") >= 1,
            isolated,
            normal,
            None if exact else "view-mismatch",
        )
    except Exception:
        return CoordinatorProductObservation(
            invocation.case_id,
            invocation.owner_id,
            request,
            expected,
            request_id,
            None,
            None,
            _duration(started),
            False,
            False,
            False,
            normal,
            "product-error",
        )
    finally:
        if request_id is not None:
            active_requests.remove(request_id)


def _run_normal_product_wave(
    *,
    base_url: str,
    corpus: CoordinatorBoundQualificationCorpus,
    semantic_acceptance,
    tokens_by_owner: Mapping[str, str],
    foreign_by_owner: Mapping[str, str],
    authenticator: _QualificationAuthenticator,
) -> tuple[CoordinatorProductObservation, ...]:
    invocations = _normal_invocations(corpus, semantic_acceptance)
    barrier = threading.Barrier(len(invocations))
    active = _ActiveProductRequests()
    pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
        max_workers=len(invocations),
        thread_name_prefix="coordinator-product-qualification",
    )
    try:
        futures: list[Future[CoordinatorProductObservation]] = [
            pool.submit(
                _submit_product_bundle,
                base_url,
                invocation,
                corpus.expected_views[invocation.expected_view_id],
                token=tokens_by_owner[invocation.owner_id],
                foreign_token=foreign_by_owner[invocation.owner_id],
                active_requests=active,
                authenticator=authenticator,
                barrier=barrier,
                normal=True,
            )
            for invocation in invocations
        ]
        _, incomplete = wait(futures, timeout=_NORMAL_WAVE_TIMEOUT_SECONDS)
        if incomplete:
            for request_id, token in active.snapshot():
                try:
                    _http_json(
                        base_url,
                        f"/v1/coordinator-bundles/{request_id}",
                        method="DELETE",
                        token=token,
                    )
                except BaseException:
                    pass
            _, uncontained = wait(incomplete, timeout=_WORKER_CONTAINMENT_SECONDS)
            if uncontained:
                pool.shutdown(wait=False, cancel_futures=True)
                pool = None
                raise RuntimeError("Coordinator product wave was not contained")
            raise TimeoutError("Coordinator product wave exceeded its deadline")
        return tuple(future.result() for future in futures)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _run_cross_owner_control(
    *,
    base_url: str,
    invocation: CoordinatorQualificationInvocation,
    token: str,
    foreign_token: str,
    authenticator: _QualificationAuthenticator,
) -> CoordinatorProductObservation:
    cross = replace(invocation, owner_id=_CROSS_OWNER_ID)
    expected = CoordinatorExpectedView("evidence-unavailable", "empty-result", None)
    observation = _submit_product_bundle(
        base_url,
        cross,
        expected,
        token=token,
        foreign_token=foreign_token,
        active_requests=_ActiveProductRequests(),
        authenticator=authenticator,
        barrier=None,
        normal=False,
    )
    return replace(observation, label="cross-owner-hidden")


def _run_cancellation_control(
    *,
    base_url: str,
    invocation: CoordinatorQualificationInvocation,
    token: str,
    foreign_token: str,
    authenticator: _QualificationAuthenticator,
    model: _CancellationModel,
) -> CoordinatorProductObservation:
    request = CoordinatorRequest(
        objective=invocation.objective,
        maximum_items=invocation.maximum_items,
        expected_generation_sha256=invocation.expected_generation_sha256,
    )
    expected = CoordinatorExpectedView("cancelled", "client-cancelled", None)
    started = time.monotonic()
    request_id: str | None = None
    try:
        status, value = _http_json(
            base_url,
            "/v1/coordinator-bundles",
            method="POST",
            token=token,
            body=request.to_wire(),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Coordinator product cancellation submission failed")
        accepted = _parse_product_view(value)
        request_id = accepted.request_id
        isolated = _foreign_owner_isolation_exact(
            base_url,
            request_id,
            foreign_token=foreign_token,
        )
        if not model.started.wait(20.0):
            raise RuntimeError(
                "Coordinator product cancellation did not reach the model"
            )
        cancel_status, cancel_value = _http_json(
            base_url,
            f"/v1/coordinator-bundles/{request_id}",
            method="DELETE",
            token=token,
        )
        if cancel_status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Coordinator product cancellation request failed")
        cancelled = _parse_product_view(cancel_value)
        observed = (
            cancelled
            if cancelled.status in _TERMINAL_STATUSES
            else _wait_for_terminal(base_url, request_id, token=token)
        )
        exact = _view_matches_expected(observed, expected) and model.cancelled.is_set()
        return CoordinatorProductObservation(
            "http-cancelled",
            invocation.owner_id,
            request,
            expected,
            request_id,
            None,
            observed,
            _duration(started),
            exact,
            authenticator.observed_header_count(f"Bearer {token}") >= 1,
            isolated,
            False,
            None if exact else "cancellation-mismatch",
        )
    except Exception:
        return CoordinatorProductObservation(
            "http-cancelled",
            invocation.owner_id,
            request,
            expected,
            request_id,
            None,
            None,
            _duration(started),
            False,
            False,
            False,
            False,
            "product-error",
        )


def _evaluate_product_observations(
    observations: Sequence[CoordinatorProductObservation],
    *,
    acceptance: CoordinatorProductAcceptance,
    authentication_probe: Mapping[str, bool],
    database_state_exact: bool,
    worker_containment_met: bool,
) -> dict[str, int | bool]:
    normal = tuple(item for item in observations if item.normal)
    durations = sorted(item.duration_milliseconds for item in normal)
    p95 = durations[max(0, math.ceil(len(durations) * 0.95) - 1)]
    bundles = tuple(item for item in observations if item.expected.bundle is not None)
    unavailable = tuple(
        item for item in observations if item.expected.status == "evidence-unavailable"
    )
    by_label = {item.label: item for item in observations}
    absent = by_label.get("absent-unavailable")
    hidden = by_label.get("hidden-only-unavailable")
    cross_owner = by_label.get("cross-owner-hidden")
    request_ids = [
        item.product_request_id
        for item in observations
        if item.product_request_id is not None
    ]
    public: dict[str, int | bool] = {
        "qualified": False,
        "caseCount": len({item.label for item in normal}),
        "ownerCount": len({item.owner_id for item in normal}),
        "queryCount": len(observations),
        "synchronizedOwnerCount": len({item.owner_id for item in normal}),
        "completeCount": sum(
            item.observed is not None and item.observed.status == "complete"
            for item in observations
        ),
        "unavailableCount": sum(
            item.observed is not None and item.observed.status == "evidence-unavailable"
            for item in observations
        ),
        "failedCount": sum(
            item.observed is not None and item.observed.status == "failed"
            for item in observations
        ),
        "cancelledCount": sum(
            item.observed is not None and item.observed.status == "cancelled"
            for item in observations
        ),
        "exactTerminalCount": sum(item.exact_match for item in observations),
        "exactBundleCount": sum(item.exact_match for item in bundles),
        "uniqueProductRequestIdCount": len(set(request_ids)),
        "normalP95WithinBound": bool(durations)
        and p95 <= acceptance.maximum_normal_p95_milliseconds,
        "authenticatedHttpExact": bool(authentication_probe)
        and all(authentication_probe.values())
        and all(item.authentication_header_exact for item in observations),
        "ownerIsolationExact": all(item.owner_isolation_exact for item in observations),
        "serverDerivedBundleExact": bool(bundles)
        and all(item.exact_match for item in bundles),
        "serverOwnedCitationsExact": bool(bundles)
        and all(
            item.observed is not None
            and item.observed.bundle == _parse_bundle(item.expected.bundle.to_wire())
            for item in bundles
        ),
        "hiddenOnlyIndistinguishable": (
            absent is not None
            and hidden is not None
            and absent.observed is not None
            and hidden.observed is not None
            and absent.observed.status == hidden.observed.status
            and absent.observed.reason == hidden.observed.reason
            and absent.observed.bundle == hidden.observed.bundle
            and cross_owner is not None
            and cross_owner.observed is not None
            and cross_owner.observed.status == absent.observed.status
            and cross_owner.observed.reason == absent.observed.reason
            and cross_owner.observed.bundle == absent.observed.bundle
        ),
        "unavailableBundleAbsent": bool(unavailable)
        and all(
            item.observed is not None and item.observed.bundle is None
            for item in unavailable
        ),
        "httpCancellationFailedClosed": (
            by_label.get("http-cancelled") is not None
            and by_label["http-cancelled"].exact_match
            and by_label["http-cancelled"].observed is not None
            and by_label["http-cancelled"].observed.bundle is None
        ),
        "workerContainmentMet": worker_containment_met,
    }
    required = acceptance.expected_public_evidence()
    public["qualified"] = database_state_exact and all(
        public[key] == value for key, value in required.items() if key != "qualified"
    )
    return public


def _bind_internal_request_ids(
    dsn: str,
    observations: Sequence[CoordinatorProductObservation],
    *,
    tenant_id: str,
) -> tuple[CoordinatorProductObservation, ...]:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        rows = connection.execute(
            """SELECT subject_id, request_id, request_sha256, outcome, reason
               FROM yap_coordinator_result_audit WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
    unused = list(rows)
    bound: list[CoordinatorProductObservation] = []
    for observation in observations:
        outcome = {
            "complete": "succeeded",
            "evidence-unavailable": "unavailable",
            "cancelled": "cancelled",
            "failed": "failed",
        }[observation.expected.status]
        matches = [
            row
            for row in unused
            if row[0] == observation.owner_id
            and row[2] == coordinator_request_sha256(observation.request)
            and row[3] == outcome
            and row[4] == observation.expected.reason
        ]
        if len(matches) != 1:
            raise RuntimeError("Coordinator product internal request identity differs")
        row = matches[0]
        unused.remove(row)
        if (
            not isinstance(row[1], str)
            or _INTERNAL_REQUEST_ID.fullmatch(row[1]) is None
        ):
            raise RuntimeError(
                "Coordinator product internal request identity is invalid"
            )
        bound.append(replace(observation, internal_request_id=row[1]))
    if unused or len(bound) != 10:
        raise RuntimeError("Coordinator product result audit cardinality differs")
    return tuple(bound)


def _verify_product_database_state(
    dsn: str,
    initialized: _InitializedKnowledge,
    bound: CoordinatorBoundQualificationCorpus,
    observations: Sequence[CoordinatorProductObservation],
    *,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
    curator_request_ids: Mapping[str, str],
) -> dict[str, bool]:
    _verify_initialized_knowledge(dsn, initialized)
    tenant_id = bound.tenant_id
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        proposals = _proposal_rows(connection, tenant_id=tenant_id)
        curator_rows = _curator_result_rows(connection, tenant_id=tenant_id)
        result_rows = _coordinator_result_rows(connection, tenant_id=tenant_id)
        tool_rows = _tool_audit_rows(connection, tenant_id=tenant_id)
        activations = connection.execute(
            """SELECT generation_sha256, previous_generation_sha256, reason
               FROM yap_knowledge_activation_history
               WHERE tenant_id = %s ORDER BY activation_id""",
            (tenant_id,),
        ).fetchall()
    result_by_id = {row[1]: row for row in result_rows}
    expected_results: list[tuple[object, ...]] = []
    expected_coordinator_tools: list[tuple[object, ...]] = []
    for observation in observations:
        request_id = observation.internal_request_id
        if request_id not in result_by_id:
            raise RuntimeError("Coordinator product result audit identity is absent")
        evidence = _product_evidence(bound, observation)
        outcome = {
            "complete": "succeeded",
            "evidence-unavailable": "unavailable",
            "cancelled": "cancelled",
            "failed": "failed",
        }[observation.expected.status]
        bundle = observation.expected.bundle
        expected_results.append(
            (
                observation.owner_id,
                request_id,
                coordinator_request_sha256(observation.request),
                coordinator_work_sha256(observation.request, evidence),
                evidence.evidence_sha256,
                bundle.bundle_sha256 if bundle is not None else None,
                bundle.citation_sha256 if bundle is not None else None,
                evidence.generation_sha256,
                evidence.permission_hash,
                evidence.authorization_hash,
                "coordinator",
                "conversation-coordinate",
                "complex-orchestration",
                "background-llm",
                provider_generation,
                profile.candidate_id,
                profile.expected_model,
                profile.model_revision,
                profile.runtime_id,
                profile.profile_sha256,
                profile.candidate_lock_sha256,
                outcome,
                observation.expected.reason,
                len(bundle.items) if bundle is not None else 0,
                True,
            )
        )
        expected_coordinator_tools.append(
            (
                observation.owner_id,
                "coordinator",
                "open-proposal-evidence",
                "succeeded",
                len(evidence.candidates),
                evidence.generation_sha256,
                evidence.permission_hash,
                evidence.authorization_hash,
                True,
            )
        )
    expected_curator_tools = [
        *[
            (
                seed.owner_id,
                "curator",
                "reviewed-source-evidence",
                "succeeded",
                len(seed.evidence.items),
                seed.evidence.generation_sha256,
                seed.evidence.permission_hash,
                seed.evidence.authorization_hash,
                True,
            )
            for seed in bound.proposal_seeds_by_key.values()
        ],
        *[
            (
                seed.owner_id,
                "curator",
                "propose",
                "succeeded",
                1,
                seed.evidence.generation_sha256,
                seed.proposal_permission_hash,
                seed.proposal_authorization_hash,
                True,
            )
            for seed in bound.proposal_seeds_by_key.values()
        ],
    ]
    predecessor = initialized.compiled["predecessor"].generation_sha256
    successor = initialized.compiled["successor"].generation_sha256
    checks = {
        "coordinatorResultAuditExact": _sorted_rows(result_rows)
        == _sorted_rows(expected_results),
        "curatorProposalRowsExact": _sorted_rows(proposals)
        == _sorted_rows(_expected_proposal_rows(bound)),
        "curatorResultAuditExact": _sorted_rows(curator_rows)
        == _sorted_rows(
            _expected_curator_rows(
                bound,
                profile=profile,
                provider_generation=provider_generation,
                curator_request_ids=curator_request_ids,
            )
        ),
        "knowledgeToolAuditExact": _sorted_rows(tool_rows)
        == _sorted_rows([*expected_curator_tools, *expected_coordinator_tools]),
        "auditCardinalityExact": (
            len(proposals) == 8
            and len(curator_rows) == 8
            and len(result_rows) == 10
            and len(tool_rows) == 26
        ),
        "activationHistoryExact": activations
        == [
            (predecessor, None, "publish"),
            (successor, predecessor, "publish"),
        ],
    }
    if not all(checks.values()):
        raise RuntimeError("Coordinator product durable state differs")
    return checks


def _product_evidence(
    corpus: CoordinatorBoundQualificationCorpus,
    observation: CoordinatorProductObservation,
) -> CoordinatorEvidencePack:
    if observation.label == "cross-owner-hidden":
        generation = next(
            item
            for item in corpus.corpus.generations
            if corpus.generation_sha256s[item.generation_id]
            == observation.request.expected_generation_sha256
        )
        permission_hash = _permission_hash(
            corpus.tenant_id,
            observation.owner_id,
            generation,
            observation.request.expected_generation_sha256,
        )
        return CoordinatorEvidencePack.create(
            generation_sha256=observation.request.expected_generation_sha256,
            permission_hash=permission_hash,
            authorization_hash=_authorization_hash(permission_hash, "knowledge.read"),
            candidates=(),
            output_budget_exhausted=False,
        )
    if observation.label == "http-cancelled":
        first_case = corpus.corpus.cases[0].case_id
        return corpus.evidence_by_case[first_case]
    return corpus.evidence_by_case[observation.label]


def _build_cancellation_runtime(
    *,
    admission_socket_path: Path,
    dsn_path: Path,
    profile: AgentVllmServiceProfile,
    model: _CancellationModel,
) -> CoordinatorProductRuntime:
    factory = private_postgres_connection_factory(dsn_path)
    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    core = CoordinatorService(
        admission=admission,
        evidence_reader=PostgresCoordinatorEvidenceReader(factory),
        model=model,
        result_auditor=PostgresCoordinatorResultAuditor(
            factory,
            CoordinatorRuntimeAuditIdentity(
                candidate_id=profile.candidate_id,
                model=profile.expected_model,
                model_revision=profile.model_revision,
                runtime_id=profile.runtime_id,
                profile_sha256=profile.profile_sha256,
                candidate_lock_sha256=profile.candidate_lock_sha256,
            ),
        ),
    )
    return CoordinatorProductRuntime(service=CoordinatorBundleService(coordinator=core))


def _build_product_runtime(
    *,
    admission_socket_path: Path,
    profile_path: Path,
    candidate_lock_path: Path,
    dsn_path: Path,
) -> CoordinatorProductRuntime:
    runtime = build_coordinator_product_runtime(
        {
            COORDINATOR_RUNTIME: "warm_gemma",
            COORDINATOR_ADMISSION_SOCKET: str(admission_socket_path),
            COORDINATOR_PROFILE: str(profile_path),
            COORDINATOR_CANDIDATE_LOCK: str(candidate_lock_path),
            COORDINATOR_KNOWLEDGE_DSN_FILE: str(dsn_path),
        },
        authenticated_team_mode=True,
    )
    if runtime is None:
        raise RuntimeError("Coordinator product runtime is unavailable")
    return runtime


def _start_http_server(
    runtime: CoordinatorProductRuntime,
    authenticator: _QualificationAuthenticator,
):
    settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id="11111111-1111-4111-8111-111111111111",
            audience="22222222-2222-4222-8222-222222222222",
            required_scope="knowledge.bundle",
            allowed_client_ids=("33333333-3333-4333-8333-333333333333",),
            identity_storage_dir=Path("qualification-private-identity"),
        ),
    )
    server = create_server(
        settings,
        request_authenticator=authenticator,
        coordinator_bundle_service=runtime.service,
    )
    host, port = server.server_address[:2]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        name="coordinator-product-http",
        daemon=False,
    )
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_http_server(server, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("Coordinator product HTTP worker was not contained")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    root = repository_root
    fixed = (
        root / ".github/workflows/ci.yml",
        root / "server/coordinator-product-acceptance.json",
        root / "server/coordinator-acceptance.json",
        root / "server/coordinator-workload-fixtures.json",
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
        raise ValueError("Coordinator product candidate inputs are incomplete")
    return paths


def _new_private_evidence_destination(
    path: Path,
    *,
    repository_root: Path,
) -> Path:
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
            "Coordinator product evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing == existing.parent:
            raise ValueError(
                "Coordinator product evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Coordinator product evidence destination must be new and outside the repository"
        )
    return requested


def _private_observations(
    observations: Sequence[CoordinatorProductObservation],
) -> list[dict[str, object]]:
    return [
        {
            "label": item.label,
            "ownerId": item.owner_id,
            "productRequestId": item.product_request_id,
            "internalRequestId": item.internal_request_id,
            "status": item.observed.status if item.observed is not None else None,
            "reason": item.observed.reason if item.observed is not None else None,
            "bundleSha256": (
                item.observed.bundle.bundle_sha256
                if item.observed is not None and item.observed.bundle is not None
                else None
            ),
            "citationSha256": (
                item.observed.bundle.citation_sha256
                if item.observed is not None and item.observed.bundle is not None
                else None
            ),
            "durationMilliseconds": item.duration_milliseconds,
            "exactMatch": item.exact_match,
            "authenticationHeaderExact": item.authentication_header_exact,
            "ownerIsolationExact": item.owner_isolation_exact,
            "normal": item.normal,
            "failureKind": item.failure_kind,
        }
        for item in observations
    ]


def run_coordinator_product_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    root = repository_root.resolve(strict=True)
    private_destination = _new_private_evidence_destination(
        evidence_destination,
        repository_root=root,
    )
    candidate = admit_checked_candidate(
        repository_root=root,
        checked_head=checked_head,
        input_paths=_candidate_input_paths(root),
        runner=runner,
    )
    _require_private_arm64_host()
    acceptance = load_coordinator_product_acceptance(
        root / "server/coordinator-product-acceptance.json"
    )
    semantic_acceptance = load_coordinator_qualification_acceptance(
        root / "server/coordinator-acceptance.json"
    )
    corpus = load_coordinator_qualification_corpus(
        root / "server/coordinator-workload-fixtures.json"
    )
    profile_path = root / "server/agent-service-profiles/complex-orchestration.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_coordinator_service_profile(profile_path, candidate_lock_path)
    _require_full_complex_profile(
        profile.maximum_sequences,
        profile.batch_invariant,
        profile.launch_arguments,
    )
    if (
        acceptance.maximum_normal_p95_milliseconds
        != semantic_acceptance.maximum_normal_p95_milliseconds
        or profile.maximum_sequences != _BROKER_ACTIVE_CAPACITY
        or len(corpus.cases) != acceptance.case_count
    ):
        raise ValueError("Coordinator product qualification contract differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"coordinator-product-q-{secrets.token_hex(8)}"
    qualification_run_id = f"run-{secrets.token_hex(8)}"

    def observe_provider() -> dict[str, object]:
        value = read_service_state(complex_state_path)
        validate_state_identity(value, profile)
        probe_exact_service(profile)
        return value

    def observe_admission() -> dict[str, object]:
        return observe_admission_broker(
            admission_socket_path,
            expected_binary_sha256=expected_broker_sha256,
            expected_candidate_lock_sha256=profile.candidate_lock_sha256,
            expected_rapid_profile_sha256=RAPID_AUTOMATION_PROFILE_SHA256,
            expected_rapid_state_path=rapid_state_path,
            expected_complex_profile_sha256=profile.profile_sha256,
            expected_complex_state_path=complex_state_path,
        )

    capacity = probe_agent_admission_broker_capacity(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        work=AgentWorkSpec(
            role=AgentRole.COORDINATOR,
            purpose=AgentPurpose.CONVERSATION_COORDINATE,
            route=ExecutionRoute.COMPLEX_ORCHESTRATION,
            scheduling_class=SchedulingClass.BACKGROUND_LLM,
        ),
        expected_route=ExecutionRoute.COMPLEX_ORCHESTRATION,
        expected_capacity=_BROKER_ACTIVE_CAPACITY,
        tenant_id=tenant_id,
        run_scope=qualification_run_id,
        observe_provider_state=observe_provider,
        observe_broker_state=observe_admission,
    )
    database_lock = load_knowledge_database_runtime_lock(root)
    database = OwnedPostgresKnowledgeRuntime(
        checked_head=checked_head,
        runtime_lock=database_lock,
        runner=runner,
    )
    started: StartedKnowledgeDatabase | None = None
    runtime: CoordinatorProductRuntime | None = None
    server = None
    server_thread: threading.Thread | None = None
    initialized: _InitializedKnowledge | None = None
    bound: CoordinatorBoundQualificationCorpus | None = None
    curator_request_ids: Mapping[str, str] | None = None
    observations: tuple[CoordinatorProductObservation, ...] | None = None
    authentication_probe: Mapping[str, bool] | None = None
    database_state: dict[str, bool] | None = None
    teardown: Mapping[str, bool] | None = None
    provider_before: Mapping[str, object] | None = None
    worker_containment_met = False
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(
            prefix="yap-coordinator-product-qualification-"
        ) as value:
            private_root = Path(value)
            if os.name == "posix":
                private_root.chmod(0o700)
            initialized = _initialize_coordinator_knowledge(
                started.dsn,
                corpus,
                private_root / "okf",
                tenant_id=tenant_id,
            )
            restarted = _restart_database(database, started)
            started = restarted
            _verify_initialized_knowledge(restarted.dsn, initialized)
            dsn_path = private_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, restarted.dsn)
            provider_before = observe_provider()
            broker_before = observe_admission()
            curator_request_ids = _publish_curator_proposals(
                dsn_path,
                initialized.corpus,
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
            )
            bound = bind_coordinator_curator_lineage(
                initialized.corpus,
                curator_request_ids,
            )
            normal_invocations = _normal_invocations(
                bound,
                semantic_acceptance,
            )
            owners = tuple(item.owner_id for item in normal_invocations)
            all_owners = (*owners, _CROSS_OWNER_ID)
            tokens_by_owner = {
                owner: f"product-{secrets.token_hex(24)}" for owner in all_owners
            }
            foreign_by_owner = {
                owner: tokens_by_owner[owners[(index + 1) % len(owners)]]
                for index, owner in enumerate(owners)
            }
            foreign_by_owner[_CROSS_OWNER_ID] = tokens_by_owner[owners[0]]
            authenticator = _QualificationAuthenticator(
                tenant_id=tenant_id,
                tokens={token: owner for owner, token in tokens_by_owner.items()},
            )
            runtime = _build_product_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=dsn_path,
            )
            server, server_thread, base_url = _start_http_server(
                runtime,
                authenticator,
            )
            authentication_probe = _probe_http_authentication(
                base_url,
                request=CoordinatorRequest(
                    objective=normal_invocations[0].objective,
                    maximum_items=normal_invocations[0].maximum_items,
                    expected_generation_sha256=normal_invocations[
                        0
                    ].expected_generation_sha256,
                ),
            )
            normal = _run_normal_product_wave(
                base_url=base_url,
                corpus=bound,
                semantic_acceptance=semantic_acceptance,
                tokens_by_owner=tokens_by_owner,
                foreign_by_owner=foreign_by_owner,
                authenticator=authenticator,
            )
            cross = _run_cross_owner_control(
                base_url=base_url,
                invocation=normal_invocations[0],
                token=tokens_by_owner[_CROSS_OWNER_ID],
                foreign_token=foreign_by_owner[_CROSS_OWNER_ID],
                authenticator=authenticator,
            )
            _stop_http_server(server, server_thread)
            server = None
            server_thread = None
            runtime.close()
            runtime = None

            cancellation_model = _CancellationModel()
            runtime = _build_cancellation_runtime(
                admission_socket_path=admission_socket_path,
                dsn_path=dsn_path,
                profile=profile,
                model=cancellation_model,
            )
            server, server_thread, base_url = _start_http_server(
                runtime,
                authenticator,
            )
            cancelled = _run_cancellation_control(
                base_url=base_url,
                invocation=normal_invocations[0],
                token=tokens_by_owner[normal_invocations[0].owner_id],
                foreign_token=foreign_by_owner[normal_invocations[0].owner_id],
                authenticator=authenticator,
                model=cancellation_model,
            )
            _stop_http_server(server, server_thread)
            server = None
            server_thread = None
            runtime.close()
            runtime = None
            worker_containment_met = True
            if (
                observe_provider() != provider_before
                or observe_admission() != broker_before
            ):
                raise RuntimeError(
                    "Coordinator product changed provider or broker identity"
                )
            observations = (*normal, cross, cancelled)

            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            observations = _bind_internal_request_ids(
                result_restarted.dsn,
                observations,
                tenant_id=tenant_id,
            )
            database_state = _verify_product_database_state(
                result_restarted.dsn,
                initialized,
                bound,
                observations,
                profile=profile,
                provider_generation=_provider_generation(provider_before),
                curator_request_ids=curator_request_ids,
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
    if (
        initialized is None
        or bound is None
        or curator_request_ids is None
        or observations is None
        or authentication_probe is None
        or database_state is None
        or teardown is None
        or provider_before is None
    ):
        raise RuntimeError("Coordinator product qualification evidence is incomplete")
    public = _evaluate_product_observations(
        observations,
        acceptance=acceptance,
        authentication_probe=authentication_probe,
        database_state_exact=all(database_state.values()),
        worker_containment_met=worker_containment_met,
    )
    if public["qualified"] is not True:
        raise RuntimeError("Coordinator product qualification did not meet acceptance")
    candidate.verify_unchanged(runner=runner)
    semantic: dict[str, object] = dict(public)
    semantic.update(
        {
            "schemaVersion": 1,
            "qualificationScope": "coordinator-authenticated-product-server-boundary",
            "outcome": "coordinator-authenticated-product-server-boundary-qualified",
            "acceptancePlanSha256": acceptance.plan_sha256,
            "semanticAcceptancePlanSha256": semantic_acceptance.plan_sha256,
            "corpusSha256": corpus.corpus_sha256,
            "qualificationTenantSha256": hashlib.sha256(
                tenant_id.encode("utf-8")
            ).hexdigest(),
            "qualificationRunSha256": hashlib.sha256(
                qualification_run_id.encode("utf-8")
            ).hexdigest(),
            "authentication": dict(authentication_probe),
            "workload": {
                "route": "complex-orchestration",
                "schedulingClass": "background-llm",
                "model": profile.expected_model,
                "modelRevision": profile.model_revision,
                "profileSha256": profile.profile_sha256,
                "candidateLockSha256": profile.candidate_lock_sha256,
                "maximumOutputTokens": _MAXIMUM_OUTPUT_TOKENS,
                "maximumInputTokens": _MAXIMUM_INPUT_TOKENS,
                "maximumSequences": profile.maximum_sequences,
                "batchInvariant": profile.batch_invariant,
                "prefixCachingEnabled": False,
                "requestSeed": 0,
                "brokerActiveCapacity": capacity["admittedOwnerCount"],
                "brokerExpectedCapacityObserved": capacity["expectedCapacityObserved"],
                "ninthOwnerQueued": capacity["overflowOwnerQueued"],
                "capacityProbeContained": capacity["contained"],
                "capacityProbeProviderIdentityUnchanged": capacity[
                    "providerIdentityUnchanged"
                ],
                "capacityProbeBrokerIdentityUnchanged": capacity[
                    "brokerIdentityUnchanged"
                ],
                "requestTimeModelLaunchAbsent": True,
                "requestTimeModelSwapAbsent": True,
            },
            "knowledge": {
                "freshTenantStateObserved": True,
                "generationRestartReadBackObserved": True,
                "resultRestartReadBackObserved": True,
                **database_state,
                "runtimeLockSha256": database_lock.lock_sha256,
                "teardown": dict(teardown),
            },
            "productBoundary": {
                "nativeCredentialsAbsent": True,
                "rendererCredentialsAbsent": True,
                "serverDerivedBundleOnly": True,
                "serverOwnedCitationsOnly": True,
                "hiddenAndAbsentIndistinguishable": True,
                "rawHashesHiddenFromRenderer": True,
                "localControlsIndependent": True,
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
            "privacyScope": "private-coordinator-product-qualification",
            "tenantId": tenant_id,
            "qualificationRunId": qualification_run_id,
            "publicEvidence": receipt,
            "qualification": {
                "acceptancePlanSha256": acceptance.plan_sha256,
                "semanticAcceptancePlanSha256": semantic_acceptance.plan_sha256,
                "corpusSha256": corpus.corpus_sha256,
                "observations": _private_observations(observations),
            },
        },
    )
    return receipt


def _duration(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


def _require_private_arm64_host() -> None:
    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        raise RuntimeError(
            "Coordinator product qualification requires private ARM64 Linux"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify the authenticated Coordinator product vertical",
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
    receipt = run_coordinator_product_qualification_gate(
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
        if receipt["outcome"]
        == "coordinator-authenticated-product-server-boundary-qualified"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
