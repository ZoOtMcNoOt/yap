"""Qualify the authenticated Curator product boundary at one exact head."""

from __future__ import annotations

import argparse
import copy
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
from yap_server.agents.curator import CuratorRequest
from yap_server.agents.curator_product_runtime import (
    CuratorProductRuntime,
    build_curator_product_runtime,
)
from yap_server.agents.curator_runtime import (
    CURATOR_ADMISSION_SOCKET,
    CURATOR_CANDIDATE_LOCK,
    CURATOR_KNOWLEDGE_DSN_FILE,
    CURATOR_PROFILE,
    CURATOR_RUNTIME,
    load_curator_service_profile,
)
from yap_server.agents.curator_service import CuratorJobView
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
from yap_server.evaluation.curator_qualification import (
    CuratorExpectedEvidencePack,
    CuratorQualificationResult,
    evaluate_curator_qualification,
    load_curator_qualification_acceptance,
    load_curator_qualification_corpus,
)
from yap_server.evaluation.curator_qualification_gate import (
    _CROSS_OWNER_ID,
    _curator_persistence_snapshot,
    _expected_curator_evidence,
    _initialize_curator_knowledge,
    _read_back_compiled_evidence,
    _require_exact_teardown,
    _require_full_complex_profile,
    _restart_database,
    _verify_curator_database_state,
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
from yap_server.knowledge.okf_compiler import CompiledKnowledgeGeneration
from yap_server.pools.agent_vllm_service_profile import (
    RAPID_AUTOMATION_PROFILE_SHA256,
)
from yap_server.private_artifact import read_json_object_with_identity


Runner = Callable[..., subprocess.CompletedProcess[str]]
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset({"proposed", "rejected", "cancelled", "failed"})
_TERMINAL_REASONS = {
    "rejected": frozenset({"model-rejected"}),
    "cancelled": frozenset({"client-cancelled", "deadline-exceeded"}),
    "failed": frozenset(
        {
            "admission-failed",
            "capacity-unavailable",
            "deadline-exceeded",
            "evidence-unavailable",
            "invalid-output",
            "provider-unavailable",
            "runtime-unavailable",
            "service-unavailable",
            "stale-or-invalid-generation",
            "storage-timeout",
            "storage-unavailable",
            "submission-conflict",
        }
    ),
}
_PRODUCT_REQUEST_ID = re.compile(r"^curator-proposal-[0-9a-f]{32}$")
_INTERNAL_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_ACCEPTANCE_BYTES = 16 * 1024
_HTTP_TIMEOUT_SECONDS = 25.0
_POLL_INTERVAL_SECONDS = 0.02
_NORMAL_WAVE_TIMEOUT_SECONDS = 70.0
_MAXIMUM_OUTPUT_TOKENS = 512
_MAXIMUM_INPUT_TOKENS = 7_680
_BROKER_ACTIVE_CAPACITY = 8
_ACCEPTANCE_FIELDS = frozenset(
    {
        "schemaVersion",
        "qualificationScope",
        "qualified",
        "caseCount",
        "ownerCount",
        "queryCount",
        "synchronizedOwnerCount",
        "proposedCount",
        "rejectedCount",
        "failedCount",
        "cancelledCount",
        "exactTerminalCount",
        "uniqueProductRequestIdCount",
        "maximumNormalP95Milliseconds",
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "serverDerivedProposalExact",
        "noncanonicalProposalExact",
        "sourceTruthUnchanged",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    }
)


@dataclass(frozen=True, slots=True)
class CuratorProductAcceptance:
    plan_sha256: str
    case_count: int
    owner_count: int
    query_count: int
    synchronized_owner_count: int
    proposed_count: int
    rejected_count: int
    failed_count: int
    cancelled_count: int
    exact_terminal_count: int
    unique_product_request_id_count: int
    maximum_normal_p95_milliseconds: int
    normal_p95_within_bound: bool
    authenticated_http_exact: bool
    owner_isolation_exact: bool
    server_derived_proposal_exact: bool
    noncanonical_proposal_exact: bool
    source_truth_unchanged: bool
    http_cancellation_failed_closed: bool
    worker_containment_met: bool

    def expected_public_evidence(self) -> dict[str, int | bool]:
        return {
            "qualified": True,
            "caseCount": self.case_count,
            "ownerCount": self.owner_count,
            "queryCount": self.query_count,
            "synchronizedOwnerCount": self.synchronized_owner_count,
            "proposedCount": self.proposed_count,
            "rejectedCount": self.rejected_count,
            "failedCount": self.failed_count,
            "cancelledCount": self.cancelled_count,
            "exactTerminalCount": self.exact_terminal_count,
            "uniqueProductRequestIdCount": self.unique_product_request_id_count,
            "maximumNormalP95Milliseconds": self.maximum_normal_p95_milliseconds,
            "normalP95WithinBound": self.normal_p95_within_bound,
            "authenticatedHttpExact": self.authenticated_http_exact,
            "ownerIsolationExact": self.owner_isolation_exact,
            "serverDerivedProposalExact": self.server_derived_proposal_exact,
            "noncanonicalProposalExact": self.noncanonical_proposal_exact,
            "sourceTruthUnchanged": self.source_truth_unchanged,
            "httpCancellationFailedClosed": self.http_cancellation_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class CuratorProductView:
    request_id: str
    submission_id: str
    status: str
    generation_sha256: str
    evidence_sha256: str | None = None
    proposal_id: str | None = None
    reason: str | None = None

    def to_job_view(self) -> CuratorJobView:
        return CuratorJobView(
            request_id=self.request_id,
            submission_id=self.submission_id,
            status=self.status,
            generation_sha256=self.generation_sha256,
            evidence_sha256=self.evidence_sha256,
            proposal_id=self.proposal_id,
            reason=self.reason,
        )


@dataclass(frozen=True, slots=True)
class CuratorProductObservation:
    label: str
    owner_id: str
    request: CuratorRequest
    product_request_id: str | None
    internal_request_id: str | None
    observed: CuratorProductView | None
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
            client_id="curator-product-qualification",
            scopes=frozenset({"knowledge.read", "knowledge.propose"}),
        )

    def observed_header_count(self, authorization: str) -> int:
        with self._lock:
            return self._observed_headers.count(authorization)


def load_curator_product_acceptance(path: Path) -> CuratorProductAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Curator product acceptance",
    )
    if set(value) != _ACCEPTANCE_FIELDS:
        raise ValueError("Curator product acceptance fields differ")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"]
        != "curator-authenticated-product-server-boundary"
        or value["qualified"] is not True
    ):
        raise ValueError("Curator product acceptance identity differs")
    integer_fields = {
        "caseCount": 8,
        "ownerCount": 8,
        "queryCount": 10,
        "synchronizedOwnerCount": 8,
        "proposedCount": 4,
        "rejectedCount": 4,
        "failedCount": 1,
        "cancelledCount": 1,
        "exactTerminalCount": 10,
        "uniqueProductRequestIdCount": 10,
        "maximumNormalP95Milliseconds": 60_000,
    }
    if any(
        type(value[name]) is not int or value[name] != expected
        for name, expected in integer_fields.items()
    ):
        raise ValueError("Curator product acceptance counts differ")
    boolean_fields = (
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "serverDerivedProposalExact",
        "noncanonicalProposalExact",
        "sourceTruthUnchanged",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    )
    if any(value[name] is not True for name in boolean_fields):
        raise ValueError("Curator product acceptance flags differ")
    return CuratorProductAcceptance(
        identity,
        *(value[name] for name in integer_fields),
        *(value[name] for name in boolean_fields),
    )


def _parse_product_view(
    value: object,
    *,
    expected_request: CuratorRequest | None = None,
    expected_evidence_sha256: str | None = None,
) -> CuratorProductView:
    if not isinstance(value, dict):
        raise ValueError("Curator product view is invalid")
    status = value.get("status")
    base = {
        "schemaVersion",
        "requestId",
        "submissionId",
        "status",
        "generationSha256",
    }
    expected_fields = set(base)
    if status == "proposed":
        expected_fields.update({"evidenceSha256", "proposalId"})
    elif status == "rejected":
        expected_fields.update({"evidenceSha256", "reason"})
    elif status in {"failed", "cancelled"}:
        expected_fields.add("reason")
        if "evidenceSha256" in value:
            expected_fields.add("evidenceSha256")
    elif status not in _ACTIVE_STATUSES:
        raise ValueError("Curator product status is invalid")
    if set(value) != expected_fields:
        raise ValueError("Curator product view fields differ")
    request_id = value["requestId"]
    submission_id = value["submissionId"]
    generation_sha256 = value["generationSha256"]
    evidence_sha256 = value.get("evidenceSha256")
    proposal_id = value.get("proposalId")
    reason = value.get("reason")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(request_id, str)
        or _PRODUCT_REQUEST_ID.fullmatch(request_id) is None
        or not isinstance(submission_id, str)
        or not submission_id
        or len(submission_id) > 128
        or not isinstance(generation_sha256, str)
        or _SHA256.fullmatch(generation_sha256) is None
        or evidence_sha256 is not None
        and (
            not isinstance(evidence_sha256, str)
            or _SHA256.fullmatch(evidence_sha256) is None
        )
        or proposal_id is not None
        and (not isinstance(proposal_id, str) or _SHA256.fullmatch(proposal_id) is None)
    ):
        raise ValueError("Curator product view identity is invalid")
    if expected_request is not None and (
        not isinstance(expected_request, CuratorRequest)
        or submission_id != expected_request.submission_id
        or generation_sha256 != expected_request.expected_generation_sha256
    ):
        raise ValueError("Curator product request identity differs")
    if expected_evidence_sha256 is not None and (
        _SHA256.fullmatch(expected_evidence_sha256) is None
        or evidence_sha256 != expected_evidence_sha256
    ):
        raise ValueError("Curator product evidence identity differs")
    if status in _ACTIVE_STATUSES and (
        evidence_sha256 is not None or proposal_id is not None or reason is not None
    ):
        raise ValueError("Curator product active view is invalid")
    if status in _TERMINAL_STATUSES:
        if status != "proposed" and reason not in _TERMINAL_REASONS[status]:
            raise ValueError("Curator product terminal reason differs")
        if status == "proposed" and (
            evidence_sha256 is None or proposal_id is None or reason is not None
        ):
            raise ValueError("Curator product proposed view is invalid")
        if status == "rejected" and (
            evidence_sha256 is None or proposal_id is not None
        ):
            raise ValueError("Curator product rejected view is invalid")
        if status in {"failed", "cancelled"} and proposal_id is not None:
            raise ValueError("Curator product terminal view is invalid")
    return CuratorProductView(
        request_id,
        submission_id,
        str(status),
        generation_sha256,
        evidence_sha256,
        proposal_id,
        reason,
    )


def _request_wire(request: CuratorRequest) -> dict[str, object]:
    if not isinstance(request, CuratorRequest):
        raise TypeError("Curator product request type is invalid")
    value: dict[str, object] = {
        "schemaVersion": 1,
        "submissionId": request.submission_id,
        "trigger": request.trigger,
        "expectedGenerationSha256": request.expected_generation_sha256,
        "reviewedContent": request.reviewed_content,
    }
    if request.student_question is not None:
        value["studentQuestion"] = request.student_question.to_wire()
    else:
        value["sourceCitations"] = [
            {
                "conceptId": citation.concept_id,
                "sourceRevision": citation.source_revision,
                "contentSha256": citation.content_sha256,
                "charStart": citation.char_start,
                "charEnd": citation.char_end,
            }
            for citation in request.source_citations
        ]
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
        payload = json.loads(response.read())
        if not isinstance(payload, dict):
            raise ValueError("Curator product HTTP response is invalid")
        return int(response.status), payload


def _wait_for_terminal(
    base_url: str,
    request_id: str,
    *,
    token: str,
    request: CuratorRequest,
    deadline: float,
    expected_evidence_sha256: str | None = None,
    cancellation: threading.Event | None = None,
) -> CuratorProductView:
    cancellation_sent = False
    while time.monotonic() < deadline:
        if cancellation is not None and cancellation.is_set() and not cancellation_sent:
            status, payload = _http_json(
                base_url,
                f"/v1/curator-proposals/{request_id}",
                method="DELETE",
                token=token,
            )
            if status not in {HTTPStatus.ACCEPTED, HTTPStatus.NOT_FOUND}:
                raise RuntimeError("Curator product cancellation failed")
            if status == HTTPStatus.ACCEPTED:
                cancelled = _parse_product_view(payload, expected_request=request)
                if cancelled.request_id != request_id or cancelled.status not in {
                    "cancellation-requested",
                    "cancelled",
                }:
                    raise ValueError("Curator product cancellation view differs")
            cancellation_sent = True
        status, payload = _http_json(
            base_url,
            f"/v1/curator-proposals/{request_id}",
            method="GET",
            token=token,
        )
        if status != HTTPStatus.OK:
            raise RuntimeError("Curator product status request failed")
        active = payload.get("status") in _ACTIVE_STATUSES
        view = _parse_product_view(
            payload,
            expected_request=request,
            expected_evidence_sha256=(None if active else expected_evidence_sha256),
        )
        if view.request_id != request_id:
            raise ValueError("Curator product status identity changed")
        if not active:
            return view
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError("Curator product request exceeded its terminal deadline")


def _foreign_owner_isolation_exact(
    base_url: str,
    request_id: str,
    *,
    foreign_token: str,
) -> bool:
    for method in ("GET", "DELETE"):
        status, payload = _http_json(
            base_url,
            f"/v1/curator-proposals/{request_id}",
            method=method,
            token=foreign_token,
        )
        if (
            status != HTTPStatus.NOT_FOUND
            or payload.get("code") != "CURATOR_PROPOSAL_NOT_FOUND"
        ):
            return False
    return True


def _probe_http_authentication(
    base_url: str,
    *,
    request: CuratorRequest,
) -> dict[str, bool]:
    request_id = "curator-proposal-" + "0" * 32
    health_status, health = _http_json(
        base_url,
        "/v1/health",
        method="GET",
        token=None,
    )
    checks = {
        "healthCapabilityExact": health_status == HTTPStatus.OK
        and health.get("auth") == "required"
        and isinstance(health.get("capabilities"), dict)
        and health["capabilities"].get("curatorProposals") is True,
    }
    for label, path, method, body in (
        (
            "Post",
            "/v1/curator-proposals",
            "POST",
            _request_wire(request),
        ),
        ("Get", f"/v1/curator-proposals/{request_id}", "GET", None),
        ("Delete", f"/v1/curator-proposals/{request_id}", "DELETE", None),
    ):
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
        checks[f"missing{label}BearerRejected"] = (
            missing_status == HTTPStatus.UNAUTHORIZED
            and missing.get("code") == "AUTHENTICATION_REQUIRED"
        )
        checks[f"invalid{label}BearerRejected"] = (
            invalid_status == HTTPStatus.UNAUTHORIZED
            and invalid.get("code") == "INVALID_ACCESS_TOKEN"
        )
    if not all(checks.values()):
        raise RuntimeError("Curator product authentication boundary differs")
    return checks


class _HttpCuratorService:
    def __init__(
        self,
        *,
        base_url: str,
        tokens_by_owner: Mapping[str, str],
        foreign_tokens_by_owner: Mapping[str, str],
        labels_by_submission: Mapping[str, str],
        expected_evidence_by_submission: Mapping[str, str],
        authenticator: _QualificationAuthenticator,
    ) -> None:
        self._base_url = base_url
        self._tokens_by_owner = dict(tokens_by_owner)
        self._foreign_tokens_by_owner = dict(foreign_tokens_by_owner)
        self._labels_by_submission = dict(labels_by_submission)
        self._expected_evidence_by_submission = dict(expected_evidence_by_submission)
        self._authenticator = authenticator
        self._lock = threading.Lock()
        self._observations: list[CuratorProductObservation] = []

    def propose(
        self,
        request: CuratorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CuratorJobView:
        if cancellation.is_set():
            raise RuntimeError("Curator product normal cancellation was pre-set")
        token = self._tokens_by_owner.get(principal.subject_id)
        foreign_token = self._foreign_tokens_by_owner.get(principal.subject_id)
        label = self._labels_by_submission.get(request.submission_id)
        expected_evidence_sha256 = self._expected_evidence_by_submission.get(
            request.submission_id
        )
        if (
            token is None
            or foreign_token is None
            or label is None
            or expected_evidence_sha256 is None
        ):
            raise RuntimeError("Curator product owner binding differs")
        started = time.monotonic()
        product_request_id: str | None = None
        observed: CuratorProductView | None = None
        owner_isolation_exact = False
        failure_kind: str | None = None
        header = f"Bearer {token}"
        header_count_before = self._authenticator.observed_header_count(header)
        try:
            status, payload = _http_json(
                self._base_url,
                "/v1/curator-proposals",
                method="POST",
                token=token,
                body=_request_wire(request),
            )
            if status != HTTPStatus.ACCEPTED:
                raise RuntimeError("Curator product submission was not accepted")
            initial = _parse_product_view(payload, expected_request=request)
            if initial.status not in _ACTIVE_STATUSES:
                raise ValueError("Curator product initial view differs")
            product_request_id = initial.request_id
            owner_isolation_exact = _foreign_owner_isolation_exact(
                self._base_url,
                product_request_id,
                foreign_token=foreign_token,
            )
            if not owner_isolation_exact:
                raise RuntimeError("Curator product owner isolation differs")
            observed = _wait_for_terminal(
                self._base_url,
                product_request_id,
                token=token,
                request=request,
                deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
                expected_evidence_sha256=expected_evidence_sha256,
                cancellation=cancellation,
            )
            return observed.to_job_view()
        except BaseException as error:
            failure_kind = type(error).__name__
            raise
        finally:
            duration = max(0, round((time.monotonic() - started) * 1_000))
            authentication_header_exact = (
                self._authenticator.observed_header_count(header) > header_count_before
            )
            exact = (
                observed is not None
                and observed.status in {"proposed", "rejected"}
                and authentication_header_exact
                and owner_isolation_exact
                and failure_kind is None
            )
            with self._lock:
                self._observations.append(
                    CuratorProductObservation(
                        label=label,
                        owner_id=principal.subject_id,
                        request=request,
                        product_request_id=product_request_id,
                        internal_request_id=None,
                        observed=observed,
                        duration_milliseconds=duration,
                        exact_match=exact,
                        authentication_header_exact=authentication_header_exact,
                        owner_isolation_exact=owner_isolation_exact,
                        normal=True,
                        failure_kind=failure_kind,
                    )
                )

    def observations(self) -> tuple[CuratorProductObservation, ...]:
        with self._lock:
            return tuple(self._observations)


def _finalize_normal_observations(
    observations: Sequence[CuratorProductObservation],
    result: CuratorQualificationResult,
) -> tuple[CuratorProductObservation, ...]:
    private_cases = result.private_evidence.get("cases")
    if not isinstance(private_cases, list):
        raise RuntimeError("Curator product semantic cases are unavailable")
    exact_by_request: dict[str, bool] = {}
    for item in private_cases:
        if not isinstance(item, dict) or not isinstance(item.get("requestId"), str):
            raise RuntimeError("Curator product semantic case is invalid")
        exact_by_request[item["requestId"]] = (
            item.get("matchedExpectedDecision") is True
        )
    if len(exact_by_request) != len(observations):
        raise RuntimeError("Curator product semantic cardinality differs")
    return tuple(
        replace(
            item,
            exact_match=item.exact_match
            and item.product_request_id is not None
            and exact_by_request.get(item.product_request_id) is True,
        )
        for item in observations
    )


def _run_product_control(
    base_url: str,
    *,
    label: str,
    request: CuratorRequest,
    owner_id: str,
    token: str,
    foreign_token: str,
    authenticator: _QualificationAuthenticator,
    expected_status: str,
    expected_reason: str,
    cancel_after_acceptance: bool,
) -> CuratorProductObservation:
    started = time.monotonic()
    product_request_id: str | None = None
    observed: CuratorProductView | None = None
    owner_isolation_exact = False
    failure_kind: str | None = None
    header = f"Bearer {token}"
    header_count_before = authenticator.observed_header_count(header)
    try:
        status, payload = _http_json(
            base_url,
            "/v1/curator-proposals",
            method="POST",
            token=token,
            body=_request_wire(request),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Curator product control was not accepted")
        initial = _parse_product_view(payload, expected_request=request)
        if initial.status not in _ACTIVE_STATUSES:
            raise ValueError("Curator product control was not active")
        product_request_id = initial.request_id
        owner_isolation_exact = _foreign_owner_isolation_exact(
            base_url,
            product_request_id,
            foreign_token=foreign_token,
        )
        if not owner_isolation_exact:
            raise RuntimeError("Curator product control owner isolation differs")
        if cancel_after_acceptance:
            cancel_status, cancel_payload = _http_json(
                base_url,
                f"/v1/curator-proposals/{product_request_id}",
                method="DELETE",
                token=token,
            )
            if cancel_status != HTTPStatus.ACCEPTED:
                raise RuntimeError("Curator product cancellation was not accepted")
            cancelled = _parse_product_view(
                cancel_payload,
                expected_request=request,
            )
            if cancelled.status not in {"cancellation-requested", "cancelled"}:
                raise ValueError("Curator product cancellation state differs")
        observed = _wait_for_terminal(
            base_url,
            product_request_id,
            token=token,
            request=request,
            deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
        )
    except BaseException as error:
        failure_kind = type(error).__name__
    duration = max(0, round((time.monotonic() - started) * 1_000))
    authentication_header_exact = (
        authenticator.observed_header_count(header) > header_count_before
    )
    exact = (
        observed is not None
        and observed.status == expected_status
        and observed.reason == expected_reason
        and observed.proposal_id is None
        and authentication_header_exact
        and owner_isolation_exact
        and failure_kind is None
    )
    return CuratorProductObservation(
        label=label,
        owner_id=owner_id,
        request=request,
        product_request_id=product_request_id,
        internal_request_id=None,
        observed=observed,
        duration_milliseconds=duration,
        exact_match=exact,
        authentication_header_exact=authentication_header_exact,
        owner_isolation_exact=owner_isolation_exact,
        normal=False,
        failure_kind=failure_kind,
    )


def _evaluate_product_observations(
    observations: Sequence[CuratorProductObservation],
    *,
    acceptance: CuratorProductAcceptance,
    authentication_probe: Mapping[str, bool],
    semantic_qualification_exact: bool,
    database_state_exact: bool,
    replay_conflict_exact: bool,
    worker_containment_met: bool,
) -> dict[str, object]:
    normal = [item for item in observations if item.normal]
    statuses = [
        item.observed.status for item in observations if item.observed is not None
    ]
    product_ids = [
        item.product_request_id
        for item in observations
        if item.product_request_id is not None
    ]
    normal_latencies = sorted(item.duration_milliseconds for item in normal)
    p95_index = max(0, math.ceil(len(normal_latencies) * 0.95) - 1)
    p95 = normal_latencies[p95_index] if normal_latencies else 2**31
    counts: dict[str, int | bool] = {
        "caseCount": len(normal),
        "ownerCount": len({item.owner_id for item in normal}),
        "queryCount": len(observations),
        "synchronizedOwnerCount": len({item.owner_id for item in normal}),
        "proposedCount": statuses.count("proposed"),
        "rejectedCount": statuses.count("rejected"),
        "failedCount": statuses.count("failed"),
        "cancelledCount": statuses.count("cancelled"),
        "exactTerminalCount": sum(item.exact_match for item in observations),
        "uniqueProductRequestIdCount": len(set(product_ids)),
        "maximumNormalP95Milliseconds": acceptance.maximum_normal_p95_milliseconds,
        "normalP95WithinBound": p95 <= acceptance.maximum_normal_p95_milliseconds,
        "authenticatedHttpExact": bool(authentication_probe)
        and all(authentication_probe.values())
        and all(item.authentication_header_exact for item in observations),
        "ownerIsolationExact": all(item.owner_isolation_exact for item in observations),
        "serverDerivedProposalExact": semantic_qualification_exact
        and all(item.exact_match for item in normal),
        "noncanonicalProposalExact": database_state_exact,
        "sourceTruthUnchanged": database_state_exact,
        "httpCancellationFailedClosed": any(
            item.observed is not None
            and item.observed.status == "cancelled"
            and item.observed.proposal_id is None
            for item in observations
        ),
        "workerContainmentMet": worker_containment_met,
    }
    expected = acceptance.expected_public_evidence()
    qualified = replay_conflict_exact and all(
        key == "qualified" or counts.get(key) == value
        for key, value in expected.items()
    )
    return {"qualified": qualified, **counts}


def _bind_internal_request_ids(
    dsn: str,
    *,
    tenant_id: str,
    observations: Sequence[CuratorProductObservation],
    semantic_result: CuratorQualificationResult,
    cross_request: CuratorRequest,
    cross_observation: CuratorProductObservation,
) -> tuple[
    tuple[CuratorProductObservation, ...],
    CuratorQualificationResult,
    CuratorJobView,
]:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        rows = connection.execute(
            """SELECT subject_id, request_id, submission_id, outcome, reason,
                      evidence_sha256, proposal_id
               FROM yap_curator_result_audit
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
    expected_observations = (*observations, cross_observation)
    if len(rows) != len(expected_observations):
        raise RuntimeError("Curator product durable result cardinality differs")
    remaining = list(rows)
    internal_by_submission: dict[str, str] = {}
    bound: list[CuratorProductObservation] = []
    for observation in expected_observations:
        if observation.observed is None or observation.product_request_id is None:
            raise RuntimeError("Curator product terminal observation is incomplete")
        outcome = {
            "proposed": "succeeded",
            "rejected": "rejected",
            "failed": "failed",
        }.get(observation.observed.status)
        matched = [
            row
            for row in remaining
            if row[0] == observation.owner_id
            and row[2] == observation.request.submission_id
            and row[3] == outcome
            and row[4] == observation.observed.reason
            and row[5] == observation.observed.evidence_sha256
            and row[6] == observation.observed.proposal_id
        ]
        if len(matched) != 1:
            raise RuntimeError("Curator product durable request binding differs")
        row = matched[0]
        remaining.remove(row)
        internal_request_id = row[1]
        if (
            not isinstance(internal_request_id, str)
            or _INTERNAL_REQUEST_ID.fullmatch(internal_request_id) is None
            or internal_request_id == observation.product_request_id
        ):
            raise RuntimeError("Curator product internal request identity differs")
        internal_by_submission[observation.request.submission_id] = internal_request_id
        bound.append(replace(observation, internal_request_id=internal_request_id))
    if remaining:
        raise RuntimeError("Curator product durable result cardinality differs")

    private = copy.deepcopy(semantic_result.private_evidence)
    private_cases = private.get("cases")
    if not isinstance(private_cases, list):
        raise RuntimeError("Curator product semantic cases are unavailable")
    for item in private_cases:
        if not isinstance(item, dict) or not isinstance(item.get("caseId"), str):
            raise RuntimeError("Curator product semantic case is invalid")
        matching = [entry for entry in observations if entry.label == item["caseId"]]
        if len(matching) != 1:
            raise RuntimeError("Curator product semantic binding differs")
        item["requestId"] = internal_by_submission[matching[0].request.submission_id]
    rebound = CuratorQualificationResult(
        public_evidence=dict(semantic_result.public_evidence),
        private_evidence=private,
    )
    cross_view = cross_observation.observed
    if cross_view is None:
        raise RuntimeError("Curator product cross-owner view is unavailable")
    internal_cross = CuratorJobView(
        request_id=internal_by_submission[cross_request.submission_id],
        submission_id=cross_view.submission_id,
        status=cross_view.status,
        generation_sha256=cross_view.generation_sha256,
        evidence_sha256=cross_view.evidence_sha256,
        proposal_id=cross_view.proposal_id,
        reason=cross_view.reason,
    )
    return tuple(bound[:-1]), rebound, internal_cross


def _submit_product_and_wait(
    base_url: str,
    *,
    request: CuratorRequest,
    token: str,
    expected_evidence_sha256: str | None = None,
) -> CuratorProductView:
    status, payload = _http_json(
        base_url,
        "/v1/curator-proposals",
        method="POST",
        token=token,
        body=_request_wire(request),
    )
    if status != HTTPStatus.ACCEPTED:
        raise RuntimeError("Curator product replay was not accepted")
    initial = _parse_product_view(payload, expected_request=request)
    if initial.status not in _ACTIVE_STATUSES:
        raise ValueError("Curator product replay was not active")
    return _wait_for_terminal(
        base_url,
        initial.request_id,
        token=token,
        request=request,
        deadline=time.monotonic() + _NORMAL_WAVE_TIMEOUT_SECONDS,
        expected_evidence_sha256=expected_evidence_sha256,
    )


def _verify_product_replay_and_conflict(
    base_url: str,
    *,
    dsn: str,
    tenant_id: str,
    request: CuratorRequest,
    expected: CuratorProductView,
    token: str,
    foreign_token: str,
) -> dict[str, bool]:
    before = _curator_persistence_snapshot(dsn, tenant_id=tenant_id)
    replay = _submit_product_and_wait(
        base_url,
        request=request,
        token=token,
        expected_evidence_sha256=expected.evidence_sha256,
    )
    replay_exact = (
        replay.request_id != expected.request_id
        and replay.submission_id == expected.submission_id
        and replay.status == expected.status
        and replay.generation_sha256 == expected.generation_sha256
        and replay.evidence_sha256 == expected.evidence_sha256
        and replay.proposal_id == expected.proposal_id
        and replay.reason == expected.reason
        and _foreign_owner_isolation_exact(
            base_url,
            replay.request_id,
            foreign_token=foreign_token,
        )
    )
    conflict = replace(
        request,
        reviewed_content=request.reviewed_content + " Conflicting product replay.",
    )
    conflicted = _submit_product_and_wait(
        base_url,
        request=conflict,
        token=token,
    )
    conflict_rejected = (
        conflicted.status == "failed"
        and conflicted.reason == "submission-conflict"
        and conflicted.evidence_sha256 is None
        and conflicted.proposal_id is None
    )
    after = _curator_persistence_snapshot(dsn, tenant_id=tenant_id)
    if not replay_exact or not conflict_rejected or after != before:
        raise RuntimeError("Curator product replay boundary differs")
    return {
        "exactStoredReplayObserved": True,
        "conflictingReplayRejected": True,
        "replayDurableStateUnchanged": True,
    }


def _bind_and_verify_cancellation(
    dsn: str,
    *,
    tenant_id: str,
    observation: CuratorProductObservation,
    proposal_snapshot: tuple[tuple[object, ...], ...],
) -> CuratorProductObservation:
    if observation.observed is None or observation.product_request_id is None:
        raise RuntimeError("Curator product cancellation observation is incomplete")
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        rows = connection.execute(
            """SELECT request_id, outcome, reason, proposal_id, result_count
               FROM yap_curator_result_audit
               WHERE tenant_id = %s AND subject_id = %s AND submission_id = %s""",
            (
                tenant_id,
                observation.owner_id,
                observation.request.submission_id,
            ),
        ).fetchall()
        proposals = connection.execute(
            """SELECT proposer_subject_id, proposal_id, generation_sha256,
                      proposer_agent_id, proposal_type, proposed_content,
                      source_citations, inherited_policy,
                      inherited_permission_sha256, status
               FROM yap_knowledge_proposals
               WHERE tenant_id = %s
               ORDER BY proposer_subject_id, proposal_id""",
            (tenant_id,),
        ).fetchall()
    if (
        len(rows) != 1
        or rows[0][1:] != ("cancelled", "client-cancelled", None, 0)
        or tuple(proposals) != proposal_snapshot
    ):
        raise RuntimeError("Curator product cancellation state differs")
    internal_request_id = rows[0][0]
    if (
        not isinstance(internal_request_id, str)
        or _INTERNAL_REQUEST_ID.fullmatch(internal_request_id) is None
        or internal_request_id == observation.product_request_id
    ):
        raise RuntimeError("Curator product cancellation identity differs")
    return replace(observation, internal_request_id=internal_request_id)


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    root = repository_root
    fixed = (
        root / ".github/workflows/ci.yml",
        root / "server/curator-product-acceptance.json",
        root / "server/curator-acceptance.json",
        root / "server/curator-workload-fixtures.json",
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
        raise ValueError("Curator product candidate inputs are incomplete")
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
            "Curator product evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing == existing.parent:
            raise ValueError(
                "Curator product evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Curator product evidence destination must be new and outside the repository"
        )
    return requested


def _build_product_runtime(
    *,
    admission_socket_path: Path,
    profile_path: Path,
    candidate_lock_path: Path,
    dsn_path: Path,
) -> CuratorProductRuntime:
    runtime = build_curator_product_runtime(
        {
            CURATOR_RUNTIME: "warm_gemma",
            CURATOR_ADMISSION_SOCKET: str(admission_socket_path),
            CURATOR_PROFILE: str(profile_path),
            CURATOR_CANDIDATE_LOCK: str(candidate_lock_path),
            CURATOR_KNOWLEDGE_DSN_FILE: str(dsn_path),
        },
        authenticated_team_mode=True,
    )
    if runtime is None:
        raise RuntimeError("Curator product runtime is unavailable")
    return runtime


def _start_http_server(
    runtime: CuratorProductRuntime,
    authenticator: _QualificationAuthenticator,
):
    settings = ServerSettings(
        host="127.0.0.1",
        port=0,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id="11111111-1111-4111-8111-111111111111",
            audience="22222222-2222-4222-8222-222222222222",
            required_scope="knowledge.propose",
            allowed_client_ids=("33333333-3333-4333-8333-333333333333",),
            identity_storage_dir=Path("qualification-private-identity"),
        ),
    )
    server = create_server(
        settings,
        request_authenticator=authenticator,
        curator_proposal_service=runtime.service,
    )
    host, port = server.server_address[:2]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        name="curator-product-http",
        daemon=False,
    )
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_http_server(server, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("Curator product HTTP worker was not contained")


def _private_observations(
    observations: Sequence[CuratorProductObservation],
) -> list[dict[str, object]]:
    return [
        {
            "label": item.label,
            "ownerId": item.owner_id,
            "submissionId": item.request.submission_id,
            "productRequestId": item.product_request_id,
            "internalRequestId": item.internal_request_id,
            "status": item.observed.status if item.observed is not None else None,
            "reason": item.observed.reason if item.observed is not None else None,
            "evidenceSha256": (
                item.observed.evidence_sha256 if item.observed is not None else None
            ),
            "proposalId": (
                item.observed.proposal_id if item.observed is not None else None
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


def run_curator_product_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Curator's authenticated product API on one already-warm route."""

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
    acceptance = load_curator_product_acceptance(
        root / "server/curator-product-acceptance.json"
    )
    semantic_acceptance = load_curator_qualification_acceptance(
        root / "server/curator-acceptance.json"
    )
    corpus = load_curator_qualification_corpus(
        root / "server/curator-workload-fixtures.json"
    )
    profile_path = root / "server/agent-service-profiles/complex-orchestration.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_curator_service_profile(profile_path, candidate_lock_path)
    _require_full_complex_profile(
        profile.maximum_sequences,
        profile.batch_invariant,
        profile.launch_arguments,
    )
    if (
        semantic_acceptance.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS
        or semantic_acceptance.maximum_input_tokens != _MAXIMUM_INPUT_TOKENS
        or semantic_acceptance.broker_active_capacity != _BROKER_ACTIVE_CAPACITY
        or profile.maximum_sequences != _BROKER_ACTIVE_CAPACITY
        or len(corpus.cases) != acceptance.case_count
    ):
        raise ValueError("Curator product qualification contract differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"curator-product-q-{secrets.token_hex(8)}"
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

    capacity_evidence = probe_agent_admission_broker_capacity(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        work=AgentWorkSpec(
            role=AgentRole.CURATOR,
            purpose=AgentPurpose.KNOWLEDGE_PROPOSE,
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
    runtime: CuratorProductRuntime | None = None
    server = None
    server_thread: threading.Thread | None = None
    generation: CompiledKnowledgeGeneration | None = None
    semantic_result: CuratorQualificationResult | None = None
    observations: tuple[CuratorProductObservation, ...] | None = None
    authentication_probe: Mapping[str, bool] | None = None
    database_state: dict[str, bool] | None = None
    replay_checks: dict[str, bool] | None = None
    teardown: Mapping[str, bool] | None = None
    worker_containment_met = False
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(
            prefix="yap-curator-product-qualification-"
        ) as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            generation = _initialize_curator_knowledge(
                started.dsn,
                corpus,
                private_runtime_root / "okf",
                tenant_id=tenant_id,
            )
            expected_evidence = _expected_curator_evidence(generation, corpus)
            restarted = _restart_database(database, started)
            started = restarted
            first_dsn_path = private_runtime_root / "knowledge-first.dsn"
            _write_new_private_text(first_dsn_path, restarted.dsn)
            requests, expected_packs = _read_back_compiled_evidence(
                restarted.dsn,
                tenant_id=tenant_id,
                generation=generation,
                corpus=corpus,
                qualification_run_id=qualification_run_id,
                expected_evidence=expected_evidence,
            )
            normal_owners = tuple(case.owner_id for case in corpus.cases)
            tokens_by_owner = {
                owner: f"product-{secrets.token_hex(24)}"
                for owner in (*normal_owners, _CROSS_OWNER_ID)
            }
            foreign_by_owner = {
                owner: tokens_by_owner[normal_owners[(index + 1) % len(normal_owners)]]
                for index, owner in enumerate(normal_owners)
            }
            foreign_by_owner[_CROSS_OWNER_ID] = tokens_by_owner[normal_owners[0]]
            authenticator = _QualificationAuthenticator(
                tenant_id=tenant_id,
                tokens={token: owner for owner, token in tokens_by_owner.items()},
            )
            runtime = _build_product_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=first_dsn_path,
            )
            server, server_thread, base_url = _start_http_server(
                runtime,
                authenticator,
            )
            first_request = requests[corpus.cases[0].case_id]
            authentication_probe = _probe_http_authentication(
                base_url,
                request=first_request,
            )
            adapter = _HttpCuratorService(
                base_url=base_url,
                tokens_by_owner=tokens_by_owner,
                foreign_tokens_by_owner=foreign_by_owner,
                labels_by_submission={
                    requests[case.case_id].submission_id: case.case_id
                    for case in corpus.cases
                },
                expected_evidence_by_submission={
                    requests[case.case_id].submission_id: expected_packs[
                        case.case_id
                    ].evidence_sha256
                    for case in corpus.cases
                },
                authenticator=authenticator,
            )
            semantic_result = evaluate_curator_qualification(
                service=adapter,
                corpus=corpus,
                acceptance=semantic_acceptance,
                tenant_id=tenant_id,
                qualification_run_id=qualification_run_id,
                generation_sha256=generation.generation_sha256,
                expected_evidence={
                    case_id: CuratorExpectedEvidencePack(
                        generation_sha256=pack.generation_sha256,
                        permission_hash=pack.permission_hash,
                        authorization_hash=pack.authorization_hash,
                        items=expected_evidence[case_id],
                    )
                    for case_id, pack in expected_packs.items()
                },
                observe_warm_state=observe_provider,
                observe_admission_state=observe_admission,
            )
            normal_observations = _finalize_normal_observations(
                adapter.observations(),
                semantic_result,
            )
            cross_request = replace(
                first_request,
                submission_id=f"{qualification_run_id}-cross-owner",
            )
            cross_observation = _run_product_control(
                base_url,
                label="cross-owner-hidden",
                request=cross_request,
                owner_id=_CROSS_OWNER_ID,
                token=tokens_by_owner[_CROSS_OWNER_ID],
                foreign_token=foreign_by_owner[_CROSS_OWNER_ID],
                authenticator=authenticator,
                expected_status="failed",
                expected_reason="evidence-unavailable",
                cancel_after_acceptance=False,
            )
            if not cross_observation.exact_match:
                raise RuntimeError("Curator product hidden evidence was visible")
            _stop_http_server(server, server_thread)
            server = None
            server_thread = None
            runtime.close()
            runtime = None
            worker_containment_met = True

            normal_observations, semantic_result, cross_internal_view = (
                _bind_internal_request_ids(
                    restarted.dsn,
                    tenant_id=tenant_id,
                    observations=normal_observations,
                    semantic_result=semantic_result,
                    cross_request=cross_request,
                    cross_observation=cross_observation,
                )
            )
            before_restart = _curator_persistence_snapshot(
                restarted.dsn,
                tenant_id=tenant_id,
            )
            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            second_dsn_path = private_runtime_root / "knowledge-results.dsn"
            _write_new_private_text(second_dsn_path, result_restarted.dsn)
            if (
                _curator_persistence_snapshot(
                    result_restarted.dsn,
                    tenant_id=tenant_id,
                )
                != before_restart
            ):
                raise RuntimeError("Curator product persistence changed across restart")
            runtime = _build_product_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=second_dsn_path,
            )
            server, server_thread, base_url = _start_http_server(
                runtime,
                authenticator,
            )
            first_observation = next(
                item
                for item in normal_observations
                if item.label == corpus.cases[0].case_id
            )
            if first_observation.observed is None:
                raise RuntimeError("Curator product replay source is unavailable")
            replay_checks = _verify_product_replay_and_conflict(
                base_url,
                dsn=result_restarted.dsn,
                tenant_id=tenant_id,
                request=first_request,
                expected=first_observation.observed,
                token=tokens_by_owner[corpus.cases[0].owner_id],
                foreign_token=foreign_by_owner[corpus.cases[0].owner_id],
            )
            database_state = _verify_curator_database_state(
                result_restarted.dsn,
                tenant_id=tenant_id,
                corpus=corpus,
                generation_sha256=generation.generation_sha256,
                result=semantic_result,
                cross_request=cross_request,
                cross_owner_view=cross_internal_view,
                profile=profile,
                requests=requests,
                expected_packs=expected_packs,
            )
            proposal_snapshot = before_restart[0]
            cancel_request = replace(
                first_request,
                submission_id=f"{qualification_run_id}-http-cancel",
                reviewed_content=(
                    first_request.reviewed_content
                    + " This cancellation control must never be published."
                ),
            )
            cancel_observation = _run_product_control(
                base_url,
                label="http-cancelled",
                request=cancel_request,
                owner_id=corpus.cases[0].owner_id,
                token=tokens_by_owner[corpus.cases[0].owner_id],
                foreign_token=foreign_by_owner[corpus.cases[0].owner_id],
                authenticator=authenticator,
                expected_status="cancelled",
                expected_reason="client-cancelled",
                cancel_after_acceptance=True,
            )
            if not cancel_observation.exact_match:
                raise RuntimeError("Curator product cancellation differed")
            _stop_http_server(server, server_thread)
            server = None
            server_thread = None
            runtime.close()
            runtime = None
            cancel_observation = _bind_and_verify_cancellation(
                result_restarted.dsn,
                tenant_id=tenant_id,
                observation=cancel_observation,
                proposal_snapshot=proposal_snapshot,
            )
            observations = (
                *normal_observations,
                replace(
                    cross_observation,
                    internal_request_id=cross_internal_view.request_id,
                ),
                cancel_observation,
            )
            final_snapshot = _curator_persistence_snapshot(
                result_restarted.dsn,
                tenant_id=tenant_id,
            )
            final_restarted = _restart_database(database, result_restarted)
            started = final_restarted
            if (
                _curator_persistence_snapshot(
                    final_restarted.dsn,
                    tenant_id=tenant_id,
                )
                != final_snapshot
            ):
                raise RuntimeError(
                    "Curator product terminal persistence changed across restart"
                )
            database_state = {
                **database_state,
                "productCancellationAuditExact": True,
                "productCancellationProposalAbsent": True,
                "productResultRestartReadBackObserved": True,
            }
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
        generation is None
        or semantic_result is None
        or observations is None
        or authentication_probe is None
        or database_state is None
        or replay_checks is None
        or teardown is None
    ):
        raise RuntimeError("Curator product qualification evidence is incomplete")
    semantic_exact = semantic_result.public_evidence.get(
        "outcome"
    ) == "curator-knowledge-proposals-qualified" and all(
        value is True
        for value in semantic_result.public_evidence.get("acceptance", {}).values()
    )
    public = _evaluate_product_observations(
        observations,
        acceptance=acceptance,
        authentication_probe=authentication_probe,
        semantic_qualification_exact=semantic_exact,
        database_state_exact=all(database_state.values()),
        replay_conflict_exact=all(replay_checks.values()),
        worker_containment_met=worker_containment_met,
    )
    if public["qualified"] is not True:
        raise RuntimeError("Curator product qualification did not meet acceptance")
    candidate.verify_unchanged(runner=runner)
    semantic: dict[str, object] = dict(public)
    semantic.update(
        {
            "schemaVersion": 1,
            "qualificationScope": "curator-authenticated-product-server-boundary",
            "outcome": "curator-authenticated-product-server-boundary-qualified",
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
                "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
                "brokerExpectedCapacityObserved": capacity_evidence[
                    "expectedCapacityObserved"
                ],
                "ninthOwnerQueued": capacity_evidence["overflowOwnerQueued"],
                "capacityProbeContained": capacity_evidence["contained"],
                "capacityProbeProviderIdentityUnchanged": capacity_evidence[
                    "providerIdentityUnchanged"
                ],
                "capacityProbeBrokerIdentityUnchanged": capacity_evidence[
                    "brokerIdentityUnchanged"
                ],
                "requestTimeModelLaunchAbsent": True,
                "requestTimeModelSwapAbsent": True,
            },
            "knowledge": {
                "freshTenantStateObserved": True,
                "generationRestartReadBackObserved": True,
                **database_state,
                **replay_checks,
                "runtimeLockSha256": database_lock.lock_sha256,
                "teardown": dict(teardown),
            },
            "productBoundary": {
                "nativeCredentialsAbsent": True,
                "rendererCredentialsAbsent": True,
                "proposalCanonical": False,
                "proposalRequiresReview": True,
                "sourceKnowledgeActivationAbsent": True,
                "rawEvidenceAndHashesHiddenFromRenderer": True,
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
            "privacyScope": "private-curator-product-qualification",
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


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError(
            "Curator product qualification requires the private ARM64 host"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify the authenticated Curator product vertical",
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
    receipt = run_curator_product_qualification_gate(
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
        if receipt.get("outcome")
        == ("curator-authenticated-product-server-boundary-qualified")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CuratorProductAcceptance",
    "CuratorProductObservation",
    "CuratorProductView",
    "load_curator_product_acceptance",
    "main",
    "run_curator_product_qualification_gate",
]
