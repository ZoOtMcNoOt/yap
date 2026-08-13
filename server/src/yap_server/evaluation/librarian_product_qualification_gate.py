"""Qualify the authenticated Librarian HTTP product boundary at one exact head."""

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
    AgentAdmissionTicket,
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
    UnixAgentAdmissionTransport,
)
from yap_server.agents.librarian import (
    LibrarianEvidenceItem,
    LibrarianEvidencePack,
    LibrarianRequest,
)
from yap_server.agents.librarian_runtime import (
    LIBRARIAN_ADMISSION_SOCKET,
    LIBRARIAN_KNOWLEDGE_DSN_FILE,
    LIBRARIAN_RUNTIME,
    LibrarianRuntime,
    build_librarian_runtime,
)
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
from yap_server.evaluation.librarian_qualification import (
    LibrarianBoundQualificationCorpus,
    LibrarianQualificationInvocation,
    LibrarianExpectedView,
    LibrarianQualificationObservation,
    LibrarianQualificationResult,
    build_librarian_qualification_invocations,
    load_librarian_qualification_corpus,
)
from yap_server.evaluation.librarian_qualification_gate import (
    _InitializedKnowledge,
    _CURATOR_ID,
    _SOURCE_PATH,
    _cancel_capacity_ticket,
    _expected_audit_rows,
    _initialize_librarian_knowledge,
    _probe_server_io_capacity,
    _restart_database,
    _require_exact_teardown,
    _sorted_rows,
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
from yap_server.private_artifact import read_json_object_with_identity
from yap_server.pools.agent_vllm_service_profile import (
    load_complex_agent_vllm_service_profile,
    load_rapid_agent_vllm_service_profile,
)


_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_REASONS = {
    "evidence-unavailable": frozenset({"empty-result", "evidence-unavailable"}),
    "failed": frozenset(
        {
            "stale-generation",
            "unauthorized",
            "admission-failed",
            "capacity-unavailable",
            "storage-timeout",
            "storage-unavailable",
            "service-unavailable",
        }
    ),
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
}
_PRODUCT_REQUEST_ID = re.compile(r"^librarian-query-[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_ACCEPTANCE_BYTES = 16 * 1024
_HTTP_TIMEOUT_SECONDS = 25.0
_POLL_INTERVAL_SECONDS = 0.02
_NORMAL_WAVE_TIMEOUT_SECONDS = 90.0
_WORKER_CONTAINMENT_SECONDS = 23.0
_PRIVATE_OBSERVATION_TEXT_LIMIT = 2_000
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
        "uniqueProductRequestIdCount",
        "maximumNormalP95Milliseconds",
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "hiddenOnlyIndistinguishable",
        "serverDerivedEvidenceExact",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    }
)


@dataclass(frozen=True, slots=True)
class LibrarianProductAcceptance:
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
    unique_product_request_id_count: int
    maximum_normal_p95_milliseconds: int
    normal_p95_within_bound: bool
    authenticated_http_exact: bool
    owner_isolation_exact: bool
    hidden_only_indistinguishable: bool
    server_derived_evidence_exact: bool
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
            "uniqueProductRequestIdCount": self.unique_product_request_id_count,
            "maximumNormalP95Milliseconds": self.maximum_normal_p95_milliseconds,
            "normalP95WithinBound": self.normal_p95_within_bound,
            "authenticatedHttpExact": self.authenticated_http_exact,
            "ownerIsolationExact": self.owner_isolation_exact,
            "hiddenOnlyIndistinguishable": self.hidden_only_indistinguishable,
            "serverDerivedEvidenceExact": self.server_derived_evidence_exact,
            "httpCancellationFailedClosed": self.http_cancellation_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class LibrarianProductView:
    request_id: str
    status: str
    evidence: LibrarianEvidencePack | None
    reason: str | None

    def terminal_shape(self) -> tuple[str, str | None]:
        return self.status, self.reason


@dataclass(frozen=True, slots=True)
class LibrarianProductObservation:
    invocation: LibrarianQualificationInvocation
    product_request_id: str | None
    internal_request_id: str | None
    expected: LibrarianExpectedView
    observed: LibrarianProductView | None
    duration_milliseconds: int
    exact_match: bool
    authentication_header_exact: bool
    owner_isolation_exact: bool
    failure_kind: str | None


class _QualificationAuthenticator:
    authentication_required = True
    principal_access_enforced = True

    def __init__(
        self,
        *,
        tenant_id: str,
        tokens: Mapping[str, str],
    ) -> None:
        self._tenant_id = tenant_id
        self._tokens = dict(tokens)
        self._lock = threading.Lock()
        self._observed_headers: list[str | None] = []

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal:
        with self._lock:
            self._observed_headers.append(authorization)
        if authorization is None:
            raise AuthenticationFailure.missing()
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise AuthenticationFailure.invalid()
        token = authorization[len(prefix) :]
        owner_id = self._tokens.get(token)
        if owner_id is None:
            raise AuthenticationFailure.invalid()
        return AuthenticatedPrincipal(
            tenant_id=self._tenant_id,
            subject_id=owner_id,
            client_id="librarian-product-qualification",
            scopes=frozenset({"knowledge.read"}),
        )

    def observed_header_count(self, authorization: str) -> int:
        with self._lock:
            return self._observed_headers.count(authorization)


class _ActiveProductRequests:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[str, tuple[str, str]] = {}

    def add(self, invocation_id: str, request_id: str, token: str) -> None:
        with self._lock:
            if invocation_id in self._requests:
                raise RuntimeError("Librarian product active request was duplicated")
            self._requests[invocation_id] = (request_id, token)

    def remove(self, invocation_id: str) -> None:
        with self._lock:
            self._requests.pop(invocation_id, None)

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(self._requests.values())


def load_librarian_product_acceptance(path: Path) -> LibrarianProductAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Librarian product acceptance",
    )
    if set(value) != _ACCEPTANCE_FIELDS:
        raise ValueError("Librarian product acceptance fields differ")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"]
        != "librarian-authenticated-product-server-boundary"
        or value["qualified"] is not True
    ):
        raise ValueError("Librarian product acceptance identity differs")
    integer_fields = {
        "caseCount": 8,
        "ownerCount": 8,
        "queryCount": 10,
        "synchronizedOwnerCount": 8,
        "completeCount": 4,
        "unavailableCount": 3,
        "failedCount": 1,
        "cancelledCount": 2,
        "exactTerminalCount": 10,
        "uniqueProductRequestIdCount": 10,
        "maximumNormalP95Milliseconds": 16_000,
    }
    if any(
        type(value[name]) is not int or value[name] != expected
        for name, expected in integer_fields.items()
    ):
        raise ValueError("Librarian product acceptance counts differ")
    boolean_fields = (
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "hiddenOnlyIndistinguishable",
        "serverDerivedEvidenceExact",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    )
    if any(value[name] is not True for name in boolean_fields):
        raise ValueError("Librarian product acceptance flags differ")
    return LibrarianProductAcceptance(
        identity,
        *(value[name] for name in integer_fields),
        *(value[name] for name in boolean_fields),
    )


def _parse_product_view(value: object) -> LibrarianProductView:
    if not isinstance(value, dict):
        raise ValueError("Librarian product view is invalid")
    status = value.get("status")
    if status in _ACTIVE_STATUSES:
        expected_fields = {"schemaVersion", "requestId", "status"}
    elif status == "complete":
        expected_fields = {"schemaVersion", "requestId", "status", "evidencePack"}
    elif status in _TERMINAL_REASONS:
        expected_fields = {"schemaVersion", "requestId", "status", "reason"}
    else:
        raise ValueError("Librarian product status is invalid")
    if set(value) != expected_fields:
        raise ValueError("Librarian product view fields differ")
    request_id = value["requestId"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(request_id, str)
        or _PRODUCT_REQUEST_ID.fullmatch(request_id) is None
    ):
        raise ValueError("Librarian product view identity is invalid")
    if status == "complete":
        evidence = _parse_evidence_pack(value["evidencePack"])
        if not evidence.items:
            raise ValueError("Librarian product complete view is invalid")
        return LibrarianProductView(request_id, status, evidence, None)
    if status in _ACTIVE_STATUSES:
        return LibrarianProductView(request_id, status, None, None)
    reason = value["reason"]
    if not isinstance(reason, str) or reason not in _TERMINAL_REASONS[status]:
        raise ValueError("Librarian product terminal reason is invalid")
    return LibrarianProductView(request_id, status, None, reason)


def _parse_evidence_pack(value: object) -> LibrarianEvidencePack:
    if not isinstance(value, dict) or set(value) != {
        "operation",
        "generationSha256",
        "permissionHash",
        "authorizationHash",
        "evidenceSha256",
        "items",
        "outputBudgetExhausted",
    }:
        raise ValueError("Librarian product evidence fields differ")
    if value["operation"] != "search" or not isinstance(value["items"], list):
        raise ValueError("Librarian product evidence shape differs")
    hashes = (
        value["generationSha256"],
        value["permissionHash"],
        value["authorizationHash"],
        value["evidenceSha256"],
    )
    if any(
        not isinstance(item, str) or _SHA256.fullmatch(item) is None for item in hashes
    ):
        raise ValueError("Librarian product evidence identity is invalid")
    if not isinstance(value["outputBudgetExhausted"], bool):
        raise ValueError("Librarian product evidence budget is invalid")
    items = tuple(_parse_evidence_item(item) for item in value["items"])
    pack = LibrarianEvidencePack.create(
        generation_sha256=value["generationSha256"],
        permission_hash=value["permissionHash"],
        authorization_hash=value["authorizationHash"],
        items=items,
        output_budget_exhausted=value["outputBudgetExhausted"],
    )
    if pack.evidence_sha256 != value["evidenceSha256"]:
        raise ValueError("Librarian product evidence digest differs")
    return pack


def _parse_evidence_item(value: object) -> LibrarianEvidenceItem:
    if not isinstance(value, dict) or set(value) != {
        "conceptId",
        "sourceRevision",
        "contentSha256",
        "charStart",
        "charEnd",
        "text",
    }:
        raise ValueError("Librarian product citation fields differ")
    return LibrarianEvidenceItem(
        concept_id=value["conceptId"],
        source_revision=value["sourceRevision"],
        content_sha256=value["contentSha256"],
        char_start=value["charStart"],
        char_end=value["charEnd"],
        text=value["text"],
    )


def _expected_product_view(
    expected: LibrarianExpectedView,
    *,
    request_id: str,
) -> LibrarianProductView:
    if expected.status == "complete":
        evidence = LibrarianEvidencePack.create(
            generation_sha256=_required_sha(
                expected.generation_sha256,
                "expected generation digest",
            ),
            permission_hash=_required_sha(
                expected.permission_hash,
                "expected permission digest",
            ),
            authorization_hash=_required_sha(
                expected.authorization_hash,
                "expected authorization digest",
            ),
            items=tuple(
                LibrarianEvidenceItem(
                    concept_id=item.concept_id,
                    source_revision=item.source_revision,
                    content_sha256=item.content_sha256,
                    char_start=item.char_start,
                    char_end=item.char_end,
                    text=item.text,
                )
                for item in expected.items
            ),
            output_budget_exhausted=expected.output_budget_exhausted,
        )
        if evidence.evidence_sha256 != expected.evidence_sha256:
            raise ValueError("Librarian product expected evidence digest differs")
        return LibrarianProductView(request_id, "complete", evidence, None)
    return LibrarianProductView(
        request_id,
        expected.status,
        None,
        expected.reason,
    )


def _required_sha(value: str | None, field: str) -> str:
    if value is None or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Librarian product {field} is invalid")
    return value


def _http_json(
    base_url: str,
    path: str,
    *,
    method: str,
    token: str | None,
    body: Mapping[str, object] | None = None,
) -> tuple[int, Mapping[str, object]]:
    encoded = None
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        encoded = json.dumps(
            body,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
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
        payload = json.loads(response.read())
        if not isinstance(payload, dict):
            raise ValueError("Librarian product HTTP response is invalid")
        return int(response.status), payload


def _wait_for_terminal(
    base_url: str,
    request_id: str,
    *,
    token: str,
    deadline: float,
) -> LibrarianProductView:
    path = f"/v1/librarian-queries/{request_id}"
    while time.monotonic() < deadline:
        status, payload = _http_json(
            base_url,
            path,
            method="GET",
            token=token,
        )
        if status != HTTPStatus.OK:
            raise RuntimeError("Librarian product status request failed")
        view = _parse_product_view(payload)
        if view.request_id != request_id:
            raise ValueError("Librarian product status identity changed")
        if view.status not in _ACTIVE_STATUSES:
            return view
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError("Librarian product request exceeded its terminal deadline")


def _foreign_owner_isolation_exact(
    base_url: str,
    request_id: str,
    *,
    foreign_token: str,
) -> bool:
    for method in ("GET", "DELETE"):
        status, payload = _http_json(
            base_url,
            f"/v1/librarian-queries/{request_id}",
            method=method,
            token=foreign_token,
        )
        if (
            status != HTTPStatus.NOT_FOUND
            or payload.get("code") != "LIBRARIAN_QUERY_NOT_FOUND"
        ):
            return False
    return True


def _submit_product_query(
    base_url: str,
    invocation: LibrarianQualificationInvocation,
    expected: LibrarianExpectedView,
    *,
    token: str,
    foreign_token: str,
    active_requests: _ActiveProductRequests,
    barrier: threading.Barrier | None,
    authenticator: _QualificationAuthenticator,
) -> LibrarianProductObservation:
    started = time.monotonic()
    product_request_id: str | None = None
    internal_request_id: str | None = None
    observed: LibrarianProductView | None = None
    owner_isolation_exact = False
    failure_kind: str | None = None
    header = f"Bearer {token}"
    header_count_before = authenticator.observed_header_count(header)
    try:
        if barrier is not None:
            barrier.wait(timeout=5)
        status, initial_payload = _http_json(
            base_url,
            "/v1/librarian-queries",
            method="POST",
            token=token,
            body=LibrarianRequest(
                search_text=invocation.search_text,
                maximum_results=invocation.maximum_results,
                expected_generation_sha256=invocation.expected_generation_sha256,
            ).to_wire(),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Librarian product submission was not accepted")
        initial = _parse_product_view(initial_payload)
        if initial.status not in _ACTIVE_STATUSES:
            raise ValueError("Librarian product initial status is not active")
        product_request_id = initial.request_id
        active_requests.add(invocation.invocation_id, product_request_id, token)

        owner_isolation_exact = _foreign_owner_isolation_exact(
            base_url,
            product_request_id,
            foreign_token=foreign_token,
        )
        if not owner_isolation_exact:
            raise RuntimeError("Librarian product owner isolation differs")

        observed = _wait_for_terminal(
            base_url,
            product_request_id,
            token=token,
            deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
        )
    except BaseException as error:
        failure_kind = type(error).__name__
    finally:
        active_requests.remove(invocation.invocation_id)
    duration = max(0, round((time.monotonic() - started) * 1_000))
    header_count_after = authenticator.observed_header_count(header)
    authentication_header_exact = header_count_after > header_count_before
    exact = False
    if observed is not None and product_request_id is not None:
        projected = _expected_product_view(expected, request_id=product_request_id)
        exact = (
            observed == projected
            and authentication_header_exact
            and owner_isolation_exact
        )
    return LibrarianProductObservation(
        invocation,
        product_request_id,
        internal_request_id,
        expected,
        observed,
        duration,
        exact,
        authentication_header_exact,
        owner_isolation_exact,
        failure_kind,
    )


def _run_controlled_product_query(
    base_url: str,
    invocation: LibrarianQualificationInvocation,
    expected: LibrarianExpectedView,
    *,
    token: str,
    foreign_token: str,
    admission: AgentAdmissionClient,
    holder_principal: AuthenticatedPrincipal,
    authenticator: _QualificationAuthenticator,
    observe_admission: Callable[[], Mapping[str, object]],
) -> LibrarianProductObservation:
    started = time.monotonic()
    holder: AgentAdmissionTicket | None = None
    observed: LibrarianProductView | None = None
    product_request_id: str | None = None
    owner_isolation_exact = False
    failure_kind: str | None = None
    header = f"Bearer {token}"
    header_count_before = authenticator.observed_header_count(header)
    before = dict(observe_admission())
    try:
        holder = admission.new_ticket()
        holder_response = admission.submit(
            holder,
            principal=holder_principal,
            work=AgentWorkSpec(
                role=AgentRole.LIBRARIAN,
                purpose=AgentPurpose.KNOWLEDGE_READ,
                route=ExecutionRoute.SERVER_IO,
                scheduling_class=SchedulingClass.INTERACTIVE,
            ),
            source_sha256=hashlib.sha256(
                f"{holder_principal.tenant_id}\0{invocation.invocation_id}".encode()
            ).hexdigest(),
            remaining_deadline_ms=60_000,
        )
        if holder_response.outcome != "admitted":
            raise RuntimeError("Librarian product control holder was not admitted")
        status, initial_payload = _http_json(
            base_url,
            "/v1/librarian-queries",
            method="POST",
            token=token,
            body=LibrarianRequest(
                search_text=invocation.search_text,
                maximum_results=invocation.maximum_results,
                expected_generation_sha256=invocation.expected_generation_sha256,
            ).to_wire(),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Librarian product controlled submission failed")
        initial = _parse_product_view(initial_payload)
        product_request_id = initial.request_id
        if initial.status not in _ACTIVE_STATUSES:
            raise ValueError("Librarian product controlled request was not active")

        owner_isolation_exact = _foreign_owner_isolation_exact(
            base_url,
            product_request_id,
            foreign_token=foreign_token,
        )
        if not owner_isolation_exact:
            raise RuntimeError("Librarian product controlled owner isolation differs")

        if invocation.mode == "pre-cancelled":
            cancel_status, cancelled_payload = _http_json(
                base_url,
                f"/v1/librarian-queries/{product_request_id}",
                method="DELETE",
                token=token,
            )
            if cancel_status != HTTPStatus.ACCEPTED:
                raise RuntimeError("Librarian product cancellation was not accepted")
            cancelled = _parse_product_view(cancelled_payload)
            if cancelled.request_id != product_request_id or cancelled.status not in {
                "cancellation-requested",
                "cancelled",
            }:
                raise ValueError("Librarian product cancellation view differs")
        elif invocation.mode != "deadline":
            raise ValueError("Librarian product controlled mode is invalid")

        observed = _wait_for_terminal(
            base_url,
            product_request_id,
            token=token,
            deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
        )
    except BaseException as error:
        failure_kind = type(error).__name__
    finally:
        cleanup_error: BaseException | None = None
        if holder is not None:
            try:
                cancelled, acknowledged = _cancel_capacity_ticket(admission, holder)
                if (
                    cancelled.outcome != "cancellation-requested"
                    or cancelled.cancellation_reason != "client-requested"
                    or not acknowledged
                ):
                    raise RuntimeError(
                        "Librarian product control holder was not contained"
                    )
            except BaseException as error:
                cleanup_error = error
        after = dict(observe_admission())
        if before != after:
            cleanup_error = cleanup_error or RuntimeError(
                "Librarian product control changed broker identity"
            )
        if cleanup_error is not None:
            raise cleanup_error
    duration = max(0, round((time.monotonic() - started) * 1_000))
    authentication_header_exact = (
        authenticator.observed_header_count(header) > header_count_before
    )
    exact = False
    if observed is not None and product_request_id is not None:
        exact = (
            observed == _expected_product_view(expected, request_id=product_request_id)
            and authentication_header_exact
            and owner_isolation_exact
        )
    return LibrarianProductObservation(
        invocation,
        product_request_id,
        None,
        expected,
        observed,
        duration,
        exact,
        authentication_header_exact,
        owner_isolation_exact,
        failure_kind,
    )


def _probe_http_authentication(
    base_url: str,
) -> dict[str, bool]:
    health_status, health = _http_json(
        base_url,
        "/v1/health",
        method="GET",
        token=None,
    )
    request_path = "/v1/librarian-queries/librarian-query-" + "0" * 32
    protected_requests = {
        "missingPostBearerRejected": _http_json(
            base_url,
            "/v1/librarian-queries",
            method="POST",
            token=None,
            body={},
        ),
        "invalidPostBearerRejected": _http_json(
            base_url,
            "/v1/librarian-queries",
            method="POST",
            token="invalid-product-token",
            body={},
        ),
        "missingGetBearerRejected": _http_json(
            base_url,
            request_path,
            method="GET",
            token=None,
        ),
        "invalidGetBearerRejected": _http_json(
            base_url,
            request_path,
            method="GET",
            token="invalid-product-token",
        ),
        "missingDeleteBearerRejected": _http_json(
            base_url,
            request_path,
            method="DELETE",
            token=None,
        ),
        "invalidDeleteBearerRejected": _http_json(
            base_url,
            request_path,
            method="DELETE",
            token="invalid-product-token",
        ),
    }
    checks = {
        "healthCapabilityExact": health_status == HTTPStatus.OK
        and health.get("auth") == "required"
        and isinstance(health.get("capabilities"), dict)
        and health["capabilities"].get("librarianQueries") is True,
    }
    for name, (status, payload) in protected_requests.items():
        expected_code = (
            "AUTHENTICATION_REQUIRED"
            if name.startswith("missing")
            else "INVALID_ACCESS_TOKEN"
        )
        checks[name] = (
            status == HTTPStatus.UNAUTHORIZED and payload.get("code") == expected_code
        )
    if not all(checks.values()):
        raise RuntimeError("Librarian product authentication boundary differs")
    return checks


def _evaluate_product_observations(
    observations: Sequence[LibrarianProductObservation],
    *,
    acceptance: LibrarianProductAcceptance,
    authentication_probe: Mapping[str, bool],
    worker_containment_met: bool,
) -> dict[str, int | bool]:
    normal = tuple(item for item in observations if item.invocation.mode == "normal")
    terminal = tuple(
        item.observed for item in observations if item.observed is not None
    )
    product_ids = tuple(
        item.product_request_id
        for item in observations
        if item.product_request_id is not None
    )
    durations = sorted(item.duration_milliseconds for item in normal)
    p95_index = max(0, math.ceil(len(durations) * 0.95) - 1)
    by_id = {item.invocation.invocation_id: item for item in observations}
    hidden = by_id["hidden-only-unavailable:normal"]
    absent = by_id["absent-unavailable:normal"]
    public: dict[str, int | bool] = {
        "qualified": False,
        "caseCount": 8,
        "ownerCount": len({item.invocation.owner_id for item in normal}),
        "queryCount": len(observations),
        "synchronizedOwnerCount": len(
            {item.invocation.owner_id for item in normal if item.exact_match}
        ),
        "completeCount": sum(item.status == "complete" for item in terminal),
        "unavailableCount": sum(
            item.status == "evidence-unavailable" for item in terminal
        ),
        "failedCount": sum(item.status == "failed" for item in terminal),
        "cancelledCount": sum(item.status == "cancelled" for item in terminal),
        "exactTerminalCount": sum(item.exact_match for item in observations),
        "uniqueProductRequestIdCount": len(set(product_ids)),
        "maximumNormalP95Milliseconds": acceptance.maximum_normal_p95_milliseconds,
        "normalP95WithinBound": bool(durations)
        and durations[p95_index] <= acceptance.maximum_normal_p95_milliseconds,
        "authenticatedHttpExact": all(authentication_probe.values())
        and all(item.authentication_header_exact for item in observations),
        "ownerIsolationExact": all(item.owner_isolation_exact for item in observations),
        "hiddenOnlyIndistinguishable": hidden.exact_match
        and absent.exact_match
        and hidden.observed is not None
        and absent.observed is not None
        and hidden.observed.terminal_shape() == absent.observed.terminal_shape(),
        "serverDerivedEvidenceExact": all(
            item.exact_match
            for item in observations
            if item.observed is not None and item.observed.status == "complete"
        ),
        "httpCancellationFailedClosed": by_id[
            "terminal-cutover:client-cancelled"
        ].exact_match
        and by_id["terminal-cutover:deadline-exceeded"].exact_match,
        "workerContainmentMet": worker_containment_met,
    }
    required = acceptance.expected_public_evidence()
    public["qualified"] = all(
        public.get(key) == expected
        for key, expected in required.items()
        if key != "qualified"
    )
    return public


def _bind_internal_request_ids(
    dsn: str,
    observations: Sequence[LibrarianProductObservation],
    *,
    tenant_id: str,
) -> tuple[
    tuple[LibrarianProductObservation, ...],
    LibrarianQualificationResult,
]:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        rows = connection.execute(
            """SELECT subject_id, request_id, outcome, reason
               FROM yap_librarian_result_audit
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
    by_key: dict[tuple[str, str, str | None], list[str]] = {}
    for subject_id, request_id, outcome, reason in rows:
        by_key.setdefault((subject_id, outcome, reason), []).append(request_id)
    bound_product: list[LibrarianProductObservation] = []
    bound_core: list[LibrarianQualificationObservation] = []
    used_ids: set[str] = set()
    for observation in observations:
        outcome = _expected_result_outcome(observation.expected)
        key = (
            observation.invocation.owner_id,
            outcome,
            observation.expected.reason,
        )
        request_ids = by_key.get(key, [])
        if len(request_ids) != 1 or request_ids[0] in used_ids:
            raise RuntimeError("Librarian product durable request binding differs")
        internal_request_id = request_ids[0]
        if (
            not internal_request_id.startswith("agent-")
            or internal_request_id == observation.product_request_id
        ):
            raise RuntimeError("Librarian product internal request identity differs")
        used_ids.add(internal_request_id)
        bound_product.append(
            replace(observation, internal_request_id=internal_request_id)
        )
        bound_core.append(
            LibrarianQualificationObservation(
                observation.invocation,
                observation.expected,
                observation.expected,
                internal_request_id,
                observation.duration_milliseconds,
                observation.exact_match,
                observation.failure_kind,
            )
        )
    if len(rows) != len(observations) or len(used_ids) != len(observations):
        raise RuntimeError("Librarian product durable result cardinality differs")
    return (
        tuple(bound_product),
        LibrarianQualificationResult({}, tuple(bound_core)),
    )


def _verify_product_database_state(
    dsn: str,
    initialized: _InitializedKnowledge,
    result: LibrarianQualificationResult,
) -> dict[str, bool]:
    bound = initialized.bound
    corpus = bound.corpus
    tenant_id = bound.tenant_id
    predecessor = initialized.compiled["predecessor"]
    successor = initialized.compiled["successor"]
    expected_result_rows, expected_tool_rows = _expected_audit_rows(
        initialized,
        result,
    )
    deadline_tool_row = (
        "owner-terminal",
        "search",
        "cancelled",
        0,
        None,
        None,
        None,
    )
    if expected_tool_rows.count(deadline_tool_row) != 1:
        raise RuntimeError("Librarian product deadline audit oracle differs")
    expected_tool_rows.remove(deadline_tool_row)
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        active = connection.execute(
            "SELECT generation_sha256 FROM yap_knowledge_active_builds "
            "WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall()
        builds = connection.execute(
            """SELECT generation_sha256, source_revision, concept_count,
                      chunk_count, relationship_count, permission_count,
                      embedding_model_id, embedding_model_revision
               FROM yap_knowledge_builds WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        admissions = connection.execute(
            """SELECT generation_sha256, source_revision, source_kind,
                      source_path, reviewer_id
               FROM yap_knowledge_source_admissions WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        activations = connection.execute(
            """SELECT generation_sha256, previous_generation_sha256, reason
               FROM yap_knowledge_activation_history
               WHERE tenant_id = %s ORDER BY activation_id""",
            (tenant_id,),
        ).fetchall()
        proposals = connection.execute(
            "SELECT count(*) FROM yap_knowledge_proposals WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        result_rows = connection.execute(
            """SELECT subject_id, request_id, request_sha256, work_sha256,
                      evidence_sha256, generation_sha256, permission_hash,
                      authorization_hash, agent_role, purpose, route,
                      scheduling_class, outcome, reason, result_count
               FROM yap_librarian_result_audit WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        tool_rows = connection.execute(
            """SELECT subject_id, operation, outcome, result_count,
                      generation_sha256, permission_hash, authorization_hash
               FROM yap_knowledge_tool_audit
               WHERE tenant_id = %s AND agent_id = 'librarian'""",
            (tenant_id,),
        ).fetchall()
    expected_builds = [
        (
            generation.generation_sha256,
            generation.source_revision,
            len(generation.concepts),
            len(generation.chunks),
            len(generation.relationships),
            len(generation.permissions),
            "librarian-qualification",
            corpus.corpus_sha256,
        )
        for generation in (predecessor, successor)
    ]
    expected_admissions = [
        (
            generation.generation_sha256,
            generation.source_revision,
            "curated-repository",
            _SOURCE_PATH,
            _CURATOR_ID,
        )
        for generation in (predecessor, successor)
    ]
    checks = {
        "successorGenerationActive": active == [(successor.generation_sha256,)],
        "twoGenerationsRetainedExact": _sorted_rows(builds)
        == _sorted_rows(expected_builds),
        "twoSourceAdmissionsRetainedExact": _sorted_rows(admissions)
        == _sorted_rows(expected_admissions),
        "successorActivationHistoryExact": activations
        == [
            (predecessor.generation_sha256, None, "publish"),
            (
                successor.generation_sha256,
                predecessor.generation_sha256,
                "publish",
            ),
        ],
        "proposalWritesAbsent": proposals == (0,),
        "librarianResultAuditExact": _sorted_rows(result_rows)
        == _sorted_rows(expected_result_rows),
        "knowledgeToolAuditExact": _sorted_rows(tool_rows)
        == _sorted_rows(expected_tool_rows),
        "queueDeadlineToolInvocationAbsent": len(tool_rows) == 8,
    }
    if not all(checks.values()):
        raise RuntimeError("Librarian product durable state differs")
    return checks


def _expected_result_outcome(expected: LibrarianExpectedView) -> str:
    if expected.status == "complete":
        return "succeeded"
    if expected.status in {"evidence-unavailable", "failed"}:
        return "unavailable"
    if expected.status == "cancelled":
        return "cancelled"
    raise ValueError("Librarian product expected audit outcome differs")


def _private_observations(
    observations: Sequence[LibrarianProductObservation],
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for item in observations:
        if (
            item.product_request_id is None
            or item.internal_request_id is None
            or len(item.invocation.owner_id) > _PRIVATE_OBSERVATION_TEXT_LIMIT
        ):
            raise RuntimeError("Librarian product private observation is incomplete")
        values.append(
            {
                "invocationId": item.invocation.invocation_id,
                "caseId": item.invocation.case_id,
                "runId": item.invocation.run_id,
                "ownerId": item.invocation.owner_id,
                "productRequestId": item.product_request_id,
                "internalRequestId": item.internal_request_id,
                "status": item.observed.status if item.observed is not None else None,
                "reason": item.observed.reason if item.observed is not None else None,
                "durationMilliseconds": item.duration_milliseconds,
                "exactMatch": item.exact_match,
                "authenticationHeaderExact": item.authentication_header_exact,
                "ownerIsolationExact": item.owner_isolation_exact,
                "failureKind": item.failure_kind,
            }
        )
    return values


def _start_http_server(
    runtime: LibrarianRuntime,
    authenticator: _QualificationAuthenticator,
):
    settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id="11111111-1111-4111-8111-111111111111",
            audience="22222222-2222-4222-8222-222222222222",
            required_scope="knowledge.read",
            allowed_client_ids=("33333333-3333-4333-8333-333333333333",),
            identity_storage_dir=Path("qualification-private-identity"),
        ),
    )
    server = create_server(
        settings,
        request_authenticator=authenticator,
        librarian_query_service=runtime.service,
    )
    host, port = server.server_address[:2]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        name="librarian-product-http",
        daemon=False,
    )
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_http_server(server, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("Librarian product HTTP worker was not contained")


def _run_product_workload(
    *,
    base_url: str,
    corpus: LibrarianBoundQualificationCorpus,
    acceptance: LibrarianProductAcceptance,
    tokens_by_owner: Mapping[str, str],
    authenticator: _QualificationAuthenticator,
    admission_socket_path: Path,
    observe_admission: Callable[[], Mapping[str, object]],
) -> tuple[tuple[LibrarianProductObservation, ...], Mapping[str, bool]]:
    invocations = build_librarian_qualification_invocations(
        corpus.corpus,
        tenant_id=corpus.tenant_id,
        generation_sha256s=corpus.generation_sha256s,
    )
    normal = tuple(item for item in invocations if item.mode == "normal")
    controlled = tuple(item for item in invocations if item.mode != "normal")
    if (
        len(normal) != acceptance.synchronized_owner_count
        or len({item.owner_id for item in normal}) != acceptance.owner_count
        or tuple(item.mode for item in controlled) != ("pre-cancelled", "deadline")
    ):
        raise ValueError("Librarian product workload shape differs")
    owners = tuple(item.owner_id for item in normal)
    foreign_by_owner = {
        owner: tokens_by_owner[owners[(index + 1) % len(owners)]]
        for index, owner in enumerate(owners)
    }
    authentication_probe = _probe_http_authentication(base_url)
    barrier = threading.Barrier(len(normal))
    active_requests = _ActiveProductRequests()
    pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
        max_workers=len(normal),
        thread_name_prefix="librarian-product-qualification",
    )
    try:
        futures: list[Future[LibrarianProductObservation]] = [
            pool.submit(
                _submit_product_query,
                base_url,
                invocation,
                corpus.expected_views[invocation.invocation_id],
                token=tokens_by_owner[invocation.owner_id],
                foreign_token=foreign_by_owner[invocation.owner_id],
                active_requests=active_requests,
                barrier=barrier,
                authenticator=authenticator,
            )
            for invocation in normal
        ]
        _, incomplete = wait(futures, timeout=_NORMAL_WAVE_TIMEOUT_SECONDS)
        if incomplete:
            for request_id, token in active_requests.snapshot():
                try:
                    _http_json(
                        base_url,
                        f"/v1/librarian-queries/{request_id}",
                        method="DELETE",
                        token=token,
                    )
                except BaseException:
                    pass
            _, uncontained = wait(incomplete, timeout=_WORKER_CONTAINMENT_SECONDS)
            if uncontained:
                pool.shutdown(wait=False, cancel_futures=True)
                pool = None
                raise RuntimeError("Librarian product wave was not contained")
            raise TimeoutError("Librarian product wave exceeded its deadline")
        observations = [future.result() for future in futures]
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    holder_principal = AuthenticatedPrincipal(
        tenant_id=corpus.tenant_id,
        subject_id="product-control-holder",
        client_id="librarian-product-qualification",
        scopes=frozenset(),
    )
    for invocation in controlled:
        observations.append(
            _run_controlled_product_query(
                base_url,
                invocation,
                corpus.expected_views[invocation.invocation_id],
                token=tokens_by_owner[invocation.owner_id],
                foreign_token=foreign_by_owner[invocation.owner_id],
                admission=admission,
                holder_principal=holder_principal,
                authenticator=authenticator,
                observe_admission=observe_admission,
            )
        )
    if len(observations) != acceptance.query_count:
        raise RuntimeError("Librarian product observation cardinality differs")
    return tuple(observations), authentication_probe


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    root = repository_root
    fixed = (
        root / ".github/workflows/ci.yml",
        root / "server/librarian-product-acceptance.json",
        root / "server/librarian-acceptance.json",
        root / "server/librarian-workload-fixtures.json",
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
                *root.glob("desktop/tests/unit/**/*.*"),
                *root.glob("desktop/tests/scripts/**/*.*"),
                *root.glob("desktop/tests/wdio/**/*.js"),
            ),
            key=lambda path: path.as_posix(),
        )
    )
    paths = tuple(dict.fromkeys((*fixed, *recursive)))
    if any(not path.is_file() for path in paths):
        raise ValueError("Librarian product candidate inputs are incomplete")
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
            "Librarian product evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing == existing.parent:
            raise ValueError(
                "Librarian product evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Librarian product evidence destination must be new and outside the repository"
        )
    return requested


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify the authenticated Librarian product vertical",
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
    receipt = run_librarian_product_qualification_gate(
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
        == "librarian-authenticated-product-server-boundary-qualified"
        else 1
    )


def run_librarian_product_qualification_gate(
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
    private_evidence_destination = _new_private_evidence_destination(
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
    acceptance = load_librarian_product_acceptance(
        root / "server/librarian-product-acceptance.json"
    )
    corpus = load_librarian_qualification_corpus(
        root / "server/librarian-workload-fixtures.json"
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
        raise ValueError("Librarian product broker candidate lock identity differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"librarian-product-q-{secrets.token_hex(8)}"
    qualification_run_id = f"run-{secrets.token_hex(8)}"

    def observe_admission() -> dict[str, object]:
        return observe_admission_broker(
            admission_socket_path,
            expected_binary_sha256=expected_broker_sha256,
            expected_candidate_lock_sha256=rapid_profile.candidate_lock_sha256,
            expected_rapid_profile_sha256=rapid_profile.profile_sha256,
            expected_rapid_state_path=rapid_state_path,
            expected_complex_profile_sha256=complex_profile.profile_sha256,
            expected_complex_state_path=complex_state_path,
        )

    capacity_evidence = _probe_server_io_capacity(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        tenant_id=tenant_id,
        run_scope=qualification_run_id,
        observe_broker_state=observe_admission,
    )
    database_lock = load_knowledge_database_runtime_lock(root)
    database = OwnedPostgresKnowledgeRuntime(
        checked_head=checked_head,
        runtime_lock=database_lock,
        runner=runner,
    )
    started: StartedKnowledgeDatabase | None = None
    runtime: LibrarianRuntime | None = None
    server = None
    server_thread: threading.Thread | None = None
    initialized: _InitializedKnowledge | None = None
    product_observations: tuple[LibrarianProductObservation, ...] | None = None
    authentication_probe: Mapping[str, bool] | None = None
    database_state: dict[str, bool] | None = None
    teardown: Mapping[str, bool] | None = None
    worker_containment_met = False
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(
            prefix="yap-librarian-product-qualification-"
        ) as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            initialized = _initialize_librarian_knowledge(
                started.dsn,
                corpus,
                private_runtime_root / "okf",
                tenant_id=tenant_id,
            )
            restarted = _restart_database(database, started)
            started = restarted
            dsn_path = private_runtime_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, restarted.dsn)

            tokens_by_owner = {
                case.owner_id: f"product-{secrets.token_hex(24)}"
                for case in initialized.bound.corpus.cases
            }
            authenticator = _QualificationAuthenticator(
                tenant_id=tenant_id,
                tokens={token: owner for owner, token in tokens_by_owner.items()},
            )
            runtime = build_librarian_runtime(
                {
                    LIBRARIAN_RUNTIME: "permission_safe_postgres",
                    LIBRARIAN_ADMISSION_SOCKET: str(admission_socket_path),
                    LIBRARIAN_KNOWLEDGE_DSN_FILE: str(dsn_path),
                },
                authenticated_team_mode=True,
            )
            if runtime is None:
                raise RuntimeError("Librarian product runtime is unavailable")
            server, server_thread, base_url = _start_http_server(
                runtime,
                authenticator,
            )
            product_observations, authentication_probe = _run_product_workload(
                base_url=base_url,
                corpus=initialized.bound,
                acceptance=acceptance,
                tokens_by_owner=tokens_by_owner,
                authenticator=authenticator,
                admission_socket_path=admission_socket_path,
                observe_admission=observe_admission,
            )
            _stop_http_server(server, server_thread)
            server = None
            server_thread = None
            runtime.close()
            runtime = None
            worker_containment_met = True

            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            product_observations, core_result = _bind_internal_request_ids(
                result_restarted.dsn,
                product_observations,
                tenant_id=tenant_id,
            )
            database_state = _verify_product_database_state(
                result_restarted.dsn,
                initialized,
                core_result,
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
        or product_observations is None
        or authentication_probe is None
        or database_state is None
        or teardown is None
    ):
        raise RuntimeError("Librarian product qualification evidence is incomplete")
    public = _evaluate_product_observations(
        product_observations,
        acceptance=acceptance,
        authentication_probe=authentication_probe,
        worker_containment_met=worker_containment_met,
    )
    if public["qualified"] is not True:
        raise RuntimeError("Librarian product qualification did not meet acceptance")
    candidate.verify_unchanged(runner=runner)
    semantic: dict[str, object] = dict(public)
    semantic.update(
        {
            "schemaVersion": 1,
            "qualificationScope": ("librarian-authenticated-product-server-boundary"),
            "outcome": ("librarian-authenticated-product-server-boundary-qualified"),
            "acceptancePlanSha256": acceptance.plan_sha256,
            "corpusSha256": corpus.corpus_sha256,
            "qualificationTenantSha256": hashlib.sha256(
                tenant_id.encode("utf-8")
            ).hexdigest(),
            "qualificationRunSha256": hashlib.sha256(
                qualification_run_id.encode("utf-8")
            ).hexdigest(),
            "authentication": dict(authentication_probe),
            "workload": {
                "route": "server-io",
                "schedulingClass": "interactive",
                "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
                "brokerExpectedCapacityObserved": capacity_evidence[
                    "expectedCapacityObserved"
                ],
                "overflowOwnerQueued": capacity_evidence["overflowOwnerQueued"],
                "capacityProbeContained": capacity_evidence["contained"],
                "capacityProbeBrokerIdentityUnchanged": capacity_evidence[
                    "brokerIdentityUnchanged"
                ],
                "librarianModelRouteLeaseRequestsAbsent": True,
            },
            "knowledge": {
                **database_state,
                "runtimeLockSha256": database_lock.lock_sha256,
                "teardown": dict(teardown),
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
        private_evidence_destination,
        {
            "schemaVersion": 1,
            "privacyScope": "private-librarian-product-qualification",
            "tenantId": tenant_id,
            "qualificationRunId": qualification_run_id,
            "publicEvidence": receipt,
            "qualification": {
                "acceptancePlanSha256": acceptance.plan_sha256,
                "corpusSha256": corpus.corpus_sha256,
                "observations": _private_observations(product_observations),
            },
        },
    )
    return receipt


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError(
            "Librarian product qualification requires the private ARM64 host"
        )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LibrarianProductAcceptance",
    "LibrarianProductView",
    "load_librarian_product_acceptance",
    "main",
    "run_librarian_product_qualification_gate",
]
