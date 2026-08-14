"""Qualify the authenticated Student HTTP product boundary at one exact head."""

from __future__ import annotations

import argparse
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
from yap_server.agents.student import (
    StudentEvidence,
    StudentEvidenceItem,
    StudentRequest,
    student_request_sha256,
    student_work_sha256,
)
from yap_server.agents.student_model import StudentQuestion, StudentQuestionSupport
from yap_server.agents.student_product_runtime import (
    StudentProductRuntime,
    build_student_product_runtime,
)
from yap_server.agents.student_result_audit import (
    install_student_result_audit_schema,
)
from yap_server.agents.student_runtime import (
    STUDENT_ADMISSION_SOCKET,
    STUDENT_CANDIDATE_LOCK,
    STUDENT_KNOWLEDGE_DSN_FILE,
    STUDENT_PROFILE,
    STUDENT_RUNTIME,
    load_student_service_profile,
)
from yap_server.agents.student_service import StudentJobView
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
from yap_server.evaluation.student_qualification import (
    StudentExpectedEvidence,
    StudentQualificationAcceptance,
    StudentQualificationCorpus,
    StudentQualificationResult,
    evaluate_student_qualification,
    load_student_qualification_acceptance,
    load_student_qualification_corpus,
)
from yap_server.evaluation.student_qualification_gate import (
    _expected_student_evidence,
    _initialize_student_knowledge,
    _require_full_rapid_profile,
    _write_new_private_text,
)
from yap_server.private_artifact import read_json_object_with_identity
from yap_server.knowledge.generation_ledger import install_knowledge_schema
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.pools.agent_vllm_service_profile import (
    load_complex_agent_vllm_service_profile,
)
from yap_server.knowledge.okf_compiler import CompiledKnowledgeGeneration


_ACTIVE_STATUSES = frozenset({"queued", "running", "cancellation-requested"})
_TERMINAL_STATUSES = frozenset(
    {"complete", "evidence-unavailable", "cancelled", "failed"}
)
_PRODUCT_REQUEST_ID = re.compile(r"^student-question-[0-9a-f]{32}$")
_INTERNAL_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONCEPT_ID = re.compile(r"^meetings/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAXIMUM_ACCEPTANCE_BYTES = 16 * 1024
_HTTP_TIMEOUT_SECONDS = 35.0
_POLL_INTERVAL_SECONDS = 0.02
_NORMAL_WAVE_TIMEOUT_SECONDS = 95.0
_WORKER_CONTAINMENT_SECONDS = 23.0
_BROKER_ACTIVE_CAPACITY = 4
_MAXIMUM_OUTPUT_TOKENS = 512
_CROSS_OWNER = "student-product-cross-owner"
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
        "serverDerivedQuestionsExact",
        "oneSourceCitedQuestionExact",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    }
)


@dataclass(frozen=True, slots=True)
class StudentProductAcceptance:
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
    server_derived_questions_exact: bool
    one_source_cited_question_exact: bool
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
            "serverDerivedQuestionsExact": self.server_derived_questions_exact,
            "oneSourceCitedQuestionExact": self.one_source_cited_question_exact,
            "httpCancellationFailedClosed": self.http_cancellation_failed_closed,
            "workerContainmentMet": self.worker_containment_met,
        }


@dataclass(frozen=True, slots=True)
class StudentProductView:
    request_id: str
    status: str
    conversation_concept_id: str
    generation_sha256: str
    evidence_sha256: str | None
    questions: tuple[StudentQuestion, ...]
    output_budget_exhausted: bool
    reason: str | None

    def public_terminal_shape(self) -> tuple[str, str | None, int, bool]:
        return (
            self.status,
            self.reason,
            len(self.questions),
            self.output_budget_exhausted,
        )

    def to_job_view(self) -> StudentJobView:
        if self.status in _ACTIVE_STATUSES:
            raise ValueError("Student product active view is not terminal")
        return StudentJobView(
            request_id=self.request_id,
            status=self.status,
            conversation_concept_id=self.conversation_concept_id,
            generation_sha256=self.generation_sha256,
            evidence_sha256=self.evidence_sha256,
            questions=self.questions,
            output_budget_exhausted=self.output_budget_exhausted,
            reason=self.reason,
        )


@dataclass(frozen=True, slots=True)
class StudentProductObservation:
    label: str
    owner_id: str
    request: StudentRequest
    product_request_id: str | None
    internal_request_id: str | None
    observed: StudentProductView | None
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
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise AuthenticationFailure.invalid()
        owner_id = self._tokens.get(authorization[len(prefix) :])
        if owner_id is None:
            raise AuthenticationFailure.invalid()
        return AuthenticatedPrincipal(
            tenant_id=self._tenant_id,
            subject_id=owner_id,
            client_id="student-product-qualification",
            scopes=frozenset({"knowledge.read"}),
        )

    def observed_header_count(self, authorization: str) -> int:
        with self._lock:
            return self._observed_headers.count(authorization)


def load_student_product_acceptance(path: Path) -> StudentProductAcceptance:
    value, identity = read_json_object_with_identity(
        path,
        maximum_bytes=_MAXIMUM_ACCEPTANCE_BYTES,
        field="Student product acceptance",
    )
    if set(value) != _ACCEPTANCE_FIELDS:
        raise ValueError("Student product acceptance fields differ")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["qualificationScope"]
        != "student-authenticated-product-server-boundary"
        or value["qualified"] is not True
    ):
        raise ValueError("Student product acceptance identity differs")
    integer_fields = {
        "caseCount": 8,
        "ownerCount": 8,
        "queryCount": 11,
        "synchronizedOwnerCount": 8,
        "completeCount": 8,
        "unavailableCount": 2,
        "failedCount": 0,
        "cancelledCount": 1,
        "exactTerminalCount": 11,
        "uniqueProductRequestIdCount": 11,
        "maximumNormalP95Milliseconds": 31_000,
    }
    if any(
        type(value[name]) is not int or value[name] != expected
        for name, expected in integer_fields.items()
    ):
        raise ValueError("Student product acceptance counts differ")
    boolean_fields = (
        "normalP95WithinBound",
        "authenticatedHttpExact",
        "ownerIsolationExact",
        "hiddenOnlyIndistinguishable",
        "serverDerivedQuestionsExact",
        "oneSourceCitedQuestionExact",
        "httpCancellationFailedClosed",
        "workerContainmentMet",
    )
    if any(value[name] is not True for name in boolean_fields):
        raise ValueError("Student product acceptance flags differ")
    return StudentProductAcceptance(
        identity,
        *(value[name] for name in integer_fields),
        *(value[name] for name in boolean_fields),
    )


def _parse_product_view(
    value: object,
    *,
    expected_evidence: tuple[StudentExpectedEvidence, ...] | None = None,
    expected_evidence_sha256: str | None = None,
) -> StudentProductView:
    base = {
        "schemaVersion",
        "requestId",
        "status",
        "conversationConceptId",
        "generationSha256",
        "questions",
        "outputBudgetExhausted",
    }
    if not isinstance(value, dict):
        raise ValueError("Student product view is invalid")
    status = value.get("status")
    expected_fields = set(base)
    if status == "complete":
        expected_fields.add("evidenceSha256")
    elif status in _TERMINAL_STATUSES - {"complete"}:
        expected_fields.add("reason")
        if "evidenceSha256" in value:
            expected_fields.add("evidenceSha256")
    elif status not in _ACTIVE_STATUSES:
        raise ValueError("Student product status is invalid")
    if set(value) != expected_fields:
        raise ValueError("Student product view fields differ")
    request_id = value["requestId"]
    concept_id = value["conversationConceptId"]
    generation_sha256 = value["generationSha256"]
    evidence_sha256 = value.get("evidenceSha256")
    questions_value = value["questions"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(request_id, str)
        or _PRODUCT_REQUEST_ID.fullmatch(request_id) is None
        or not isinstance(concept_id, str)
        or _CONCEPT_ID.fullmatch(concept_id) is None
        or not isinstance(generation_sha256, str)
        or _SHA256.fullmatch(generation_sha256) is None
        or evidence_sha256 is not None
        and (
            not isinstance(evidence_sha256, str)
            or _SHA256.fullmatch(evidence_sha256) is None
        )
        or not isinstance(questions_value, list)
        or not isinstance(value["outputBudgetExhausted"], bool)
    ):
        raise ValueError("Student product view identity is invalid")
    if expected_evidence_sha256 is not None and (
        _SHA256.fullmatch(expected_evidence_sha256) is None
        or evidence_sha256 != expected_evidence_sha256
    ):
        raise ValueError("Student product evidence identity differs")
    questions = tuple(
        _parse_question(item, expected_evidence=expected_evidence)
        for item in questions_value
    )
    reason = value.get("reason")
    if reason is not None and (
        not isinstance(reason, str)
        or not reason
        or len(reason) > 64
        or not all(character.isalnum() or character in "-_." for character in reason)
    ):
        raise ValueError("Student product terminal reason is invalid")
    if status in _ACTIVE_STATUSES and (
        evidence_sha256 is not None
        or questions
        or value["outputBudgetExhausted"]
        or reason is not None
    ):
        raise ValueError("Student product active view is invalid")
    if status == "complete" and (
        evidence_sha256 is None or len(questions) != 1 or reason is not None
    ):
        raise ValueError("Student product complete view is invalid")
    if status in _TERMINAL_STATUSES - {"complete"} and (questions or reason is None):
        raise ValueError("Student product terminal view is invalid")
    return StudentProductView(
        request_id,
        status,
        concept_id,
        generation_sha256,
        evidence_sha256,
        questions,
        value["outputBudgetExhausted"],
        reason,
    )


def _parse_question(
    value: object,
    *,
    expected_evidence: tuple[StudentExpectedEvidence, ...] | None,
) -> StudentQuestion:
    if expected_evidence is None:
        raise ValueError("Student product expected evidence is required")
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "sourceSubject",
        "question",
        "sourceSupports",
    }:
        raise ValueError("Student product question fields differ")
    supports = value["sourceSupports"]
    if (
        value["schemaVersion"] != 3
        or not isinstance(supports, list)
        or len(supports) != 1
    ):
        raise ValueError("Student product question shape differs")
    support_value = supports[0]
    if not isinstance(support_value, dict) or set(support_value) != {
        "sourceCitation",
        "supportQuote",
        "supportCharStart",
        "supportCharEnd",
    }:
        raise ValueError("Student product support fields differ")
    citation = support_value["sourceCitation"]
    if not isinstance(citation, dict) or set(citation) != {
        "conceptId",
        "sourceRevision",
        "contentSha256",
        "charStart",
        "charEnd",
    }:
        raise ValueError("Student product citation fields differ")
    matched = [
        item
        for item in expected_evidence
        if citation
        == {
            "conceptId": item.concept_id,
            "sourceRevision": item.source_revision,
            "contentSha256": item.content_sha256,
            "charStart": item.char_start,
            "charEnd": item.char_end,
        }
    ]
    if len(matched) != 1:
        raise ValueError("Student product citation identity differs")
    item = matched[0]
    evidence = StudentEvidenceItem(
        concept_id=item.concept_id,
        source_revision=item.source_revision,
        content_sha256=item.content_sha256,
        char_start=item.char_start,
        char_end=item.char_end,
        text=item.text,
    )
    support = StudentQuestionSupport(
        evidence=evidence, quote=support_value["supportQuote"]
    )
    if support.to_wire() != support_value:
        raise ValueError("Student product support span differs")
    question = StudentQuestion(
        source_subject=value["sourceSubject"],
        question=value["question"],
        supports=(support,),
    )
    if question.to_wire() != value:
        raise ValueError("Student product question differs")
    return question


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
            raise ValueError("Student product HTTP response is invalid")
        return int(response.status), payload


def _wait_for_terminal(
    base_url: str,
    request_id: str,
    *,
    token: str,
    deadline: float,
    expected_evidence: tuple[StudentExpectedEvidence, ...] | None,
    expected_evidence_sha256: str,
) -> StudentProductView:
    while time.monotonic() < deadline:
        status, payload = _http_json(
            base_url,
            f"/v1/student-questions/{request_id}",
            method="GET",
            token=token,
        )
        if status != HTTPStatus.OK:
            raise RuntimeError("Student product status request failed")
        active = payload.get("status") in _ACTIVE_STATUSES
        view = (
            _parse_product_view(payload)
            if active
            else _parse_product_view(
                payload,
                expected_evidence=expected_evidence,
                expected_evidence_sha256=expected_evidence_sha256,
            )
        )
        if view.request_id != request_id:
            raise ValueError("Student product status identity changed")
        if not active:
            return view
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError("Student product request exceeded its terminal deadline")


def _foreign_owner_isolation_exact(
    base_url: str,
    request_id: str,
    *,
    foreign_token: str,
) -> bool:
    for method in ("GET", "DELETE"):
        status, payload = _http_json(
            base_url,
            f"/v1/student-questions/{request_id}",
            method=method,
            token=foreign_token,
        )
        if (
            status != HTTPStatus.NOT_FOUND
            or payload.get("code") != "STUDENT_QUESTION_NOT_FOUND"
        ):
            return False
    return True


def _probe_http_authentication(base_url: str) -> dict[str, bool]:
    request_id = "student-question-" + "0" * 32
    request = {
        "schemaVersion": 2,
        "conversationConceptId": "meetings/auth-probe",
        "expectedGenerationSha256": "0" * 64,
        "topic": "authentication",
    }
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
        and health["capabilities"].get("studentQuestions") is True,
    }
    for label, path, method, body in (
        ("Post", "/v1/student-questions", "POST", request),
        ("Get", f"/v1/student-questions/{request_id}", "GET", None),
        ("Delete", f"/v1/student-questions/{request_id}", "DELETE", None),
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
        raise RuntimeError("Student product authentication boundary differs")
    return checks


def _evaluate_product_observations(
    observations: Sequence[StudentProductObservation],
    *,
    acceptance: StudentProductAcceptance,
    authentication_probe: Mapping[str, bool],
    semantic_qualification_exact: bool,
    hidden_only_indistinguishable: bool,
    worker_containment_met: bool,
) -> dict[str, object]:
    normal = [item for item in observations if item.normal]
    product_ids = [
        item.product_request_id
        for item in observations
        if item.product_request_id is not None
    ]
    statuses = [
        item.observed.status for item in observations if item.observed is not None
    ]
    normal_latencies = sorted(item.duration_milliseconds for item in normal)
    p95_index = max(0, math.ceil(len(normal_latencies) * 0.95) - 1)
    p95 = normal_latencies[p95_index] if normal_latencies else 2**31
    counts = {
        "caseCount": len(normal),
        "ownerCount": len({item.owner_id for item in normal}),
        "queryCount": len(observations),
        "synchronizedOwnerCount": len({item.owner_id for item in normal}),
        "completeCount": statuses.count("complete"),
        "unavailableCount": statuses.count("evidence-unavailable"),
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
        "hiddenOnlyIndistinguishable": hidden_only_indistinguishable,
        "serverDerivedQuestionsExact": semantic_qualification_exact
        and all(item.exact_match for item in normal),
        "oneSourceCitedQuestionExact": all(
            item.observed is not None
            and len(item.observed.questions) == 1
            and len(item.observed.questions[0].supports) == 1
            for item in normal
        ),
        "httpCancellationFailedClosed": any(
            item.observed is not None
            and item.observed.status == "cancelled"
            and not item.observed.questions
            for item in observations
        ),
        "workerContainmentMet": worker_containment_met,
    }
    expected = acceptance.expected_public_evidence()
    qualified = all(
        key == "qualified" or counts.get(key) == value
        for key, value in expected.items()
    )
    return {"qualified": qualified, **counts}


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    root = repository_root
    fixed = (
        root / ".github/workflows/ci.yml",
        root / "server/student-product-acceptance.json",
        root / "server/student-acceptance.json",
        root / "server/student-workload-fixtures.json",
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
        raise ValueError("Student product candidate inputs are incomplete")
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
            "Student product evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing == existing.parent:
            raise ValueError(
                "Student product evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Student product evidence destination must be new and outside the repository"
        )
    return requested


def _request_wire(request: StudentRequest) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "conversationConceptId": request.conversation_concept_id,
        "expectedGenerationSha256": request.expected_generation_sha256,
        "topic": request.topic,
    }


def _expected_product_evidence(
    generation: CompiledKnowledgeGeneration,
    corpus: StudentQualificationCorpus,
    *,
    tenant_id: str,
) -> dict[tuple[str, str], StudentEvidence]:
    if generation.tenant_id != tenant_id:
        raise ValueError("Student product compiled tenant differs")
    expected_items = _expected_student_evidence(generation, corpus)
    permissions = {
        permission.path_prefix: permission for permission in generation.permissions
    }
    if len(permissions) != len(generation.permissions):
        raise ValueError("Student product compiled permissions differ")

    def authority(owner_id: str) -> tuple[str, str]:
        visible_concepts: list[str] = []
        permission_sha256s: set[str] = set()
        for concept in generation.concepts:
            permission = permissions.get(concept.permission_path_prefix)
            if permission is None:
                raise ValueError("Student product concept permission differs")
            audience = any(
                principal.tenant_id == tenant_id and principal.subject_id == owner_id
                for principal in permission.audience
            )
            denied = any(
                principal.tenant_id == tenant_id and principal.subject_id == owner_id
                for principal in permission.denials
            )
            if audience and not denied and "knowledge.read" in permission.purposes:
                visible_concepts.append(concept.concept_id)
                permission_sha256s.add(permission.permission_sha256)
        permission_hash = _json_sha256(
            {
                "tenantId": tenant_id,
                "subjectId": owner_id,
                "purpose": "knowledge.read",
                "generationSha256": generation.generation_sha256,
                "permissionSha256s": sorted(permission_sha256s),
                "visibleConceptIds": sorted(visible_concepts),
            }
        )
        authorization_hash = _json_sha256(
            {
                "permissionHash": permission_hash,
                "requiredCapability": "knowledge.search.lexical",
            }
        )
        return permission_hash, authorization_hash

    values: dict[tuple[str, str], StudentEvidence] = {}
    for case in corpus.cases:
        permission_hash, authorization_hash = authority(case.owner_id)
        items = tuple(
            StudentEvidenceItem(
                concept_id=item.concept_id,
                source_revision=item.source_revision,
                content_sha256=item.content_sha256,
                char_start=item.char_start,
                char_end=item.char_end,
                text=item.text,
            )
            for item in expected_items[case.case_id]
        )
        values[(case.owner_id, case.concept_id)] = StudentEvidence.create(
            generation_sha256=generation.generation_sha256,
            permission_hash=permission_hash,
            authorization_hash=authorization_hash,
            conversation_concept_id=case.concept_id,
            items=items,
            output_budget_exhausted=False,
        )
    cross_permission, cross_authorization = authority(_CROSS_OWNER)
    for concept_id in (corpus.cases[0].concept_id, "meetings/absent-probe"):
        values[(_CROSS_OWNER, concept_id)] = StudentEvidence.create(
            generation_sha256=generation.generation_sha256,
            permission_hash=cross_permission,
            authorization_hash=cross_authorization,
            conversation_concept_id=concept_id,
            items=(),
            output_budget_exhausted=False,
        )
    return values


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class _HttpStudentService:
    def __init__(
        self,
        *,
        base_url: str,
        tokens_by_owner: Mapping[str, str],
        foreign_tokens_by_owner: Mapping[str, str],
        expected_evidence_by_concept: Mapping[str, tuple[StudentExpectedEvidence, ...]],
        expected_product_evidence: Mapping[tuple[str, str], StudentEvidence],
        authenticator: _QualificationAuthenticator,
    ) -> None:
        self._base_url = base_url
        self._tokens_by_owner = dict(tokens_by_owner)
        self._foreign_tokens_by_owner = dict(foreign_tokens_by_owner)
        self._expected_evidence_by_concept = dict(expected_evidence_by_concept)
        self._expected_product_evidence = dict(expected_product_evidence)
        self._authenticator = authenticator
        self._lock = threading.Lock()
        self._observations: list[StudentProductObservation] = []
        self._active: dict[str, tuple[str, str]] = {}

    def create_questions(
        self,
        request: StudentRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> StudentJobView:
        if cancellation.is_set():
            raise RuntimeError("Student product normal cancellation was pre-set")
        token = self._tokens_by_owner.get(principal.subject_id)
        foreign_token = self._foreign_tokens_by_owner.get(principal.subject_id)
        expected = self._expected_evidence_by_concept.get(
            request.conversation_concept_id
        )
        expected_pack = self._expected_product_evidence.get(
            (principal.subject_id, request.conversation_concept_id)
        )
        if (
            token is None
            or foreign_token is None
            or expected is None
            or expected_pack is None
        ):
            raise RuntimeError("Student product normal owner binding differs")
        started = time.monotonic()
        product_request_id: str | None = None
        observed: StudentProductView | None = None
        failure_kind: str | None = None
        owner_isolation_exact = False
        header = f"Bearer {token}"
        header_count_before = self._authenticator.observed_header_count(header)
        try:
            status, payload = _http_json(
                self._base_url,
                "/v1/student-questions",
                method="POST",
                token=token,
                body=_request_wire(request),
            )
            if status != HTTPStatus.ACCEPTED:
                raise RuntimeError("Student product submission was not accepted")
            initial = _parse_product_view(payload)
            if (
                initial.status not in _ACTIVE_STATUSES
                or initial.conversation_concept_id != request.conversation_concept_id
                or initial.generation_sha256 != request.expected_generation_sha256
            ):
                raise ValueError("Student product initial view differs")
            product_request_id = initial.request_id
            with self._lock:
                self._active[product_request_id] = (
                    token,
                    request.conversation_concept_id,
                )
            owner_isolation_exact = _foreign_owner_isolation_exact(
                self._base_url,
                product_request_id,
                foreign_token=foreign_token,
            )
            if not owner_isolation_exact:
                raise RuntimeError("Student product owner isolation differs")
            observed = _wait_for_terminal(
                self._base_url,
                product_request_id,
                token=token,
                deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
                expected_evidence=expected,
                expected_evidence_sha256=expected_pack.evidence_sha256,
            )
            if (
                observed.conversation_concept_id != request.conversation_concept_id
                or observed.generation_sha256 != request.expected_generation_sha256
            ):
                raise ValueError("Student product terminal source identity differs")
            return observed.to_job_view()
        except BaseException as error:
            failure_kind = type(error).__name__
            raise
        finally:
            duration = max(0, round((time.monotonic() - started) * 1_000))
            if product_request_id is not None:
                with self._lock:
                    self._active.pop(product_request_id, None)
            authentication_header_exact = (
                self._authenticator.observed_header_count(header) > header_count_before
            )
            exact = (
                observed is not None
                and observed.status == "complete"
                and authentication_header_exact
                and owner_isolation_exact
                and failure_kind is None
            )
            with self._lock:
                self._observations.append(
                    StudentProductObservation(
                        label=request.conversation_concept_id,
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

    def observations(self) -> tuple[StudentProductObservation, ...]:
        with self._lock:
            return tuple(self._observations)

    def cancel_active(self) -> None:
        with self._lock:
            active = tuple(
                (request_id, token) for request_id, (token, _) in self._active.items()
            )
        for request_id, token in active:
            try:
                _http_json(
                    self._base_url,
                    f"/v1/student-questions/{request_id}",
                    method="DELETE",
                    token=token,
                )
            except BaseException:
                pass


def _finalize_normal_observations(
    observations: Sequence[StudentProductObservation],
    result: StudentQualificationResult,
) -> tuple[StudentProductObservation, ...]:
    private_cases = result.private_evidence.get("cases")
    if not isinstance(private_cases, list):
        raise RuntimeError("Student product semantic cases are unavailable")
    exact_by_request: dict[str, bool] = {}
    for item in private_cases:
        if not isinstance(item, dict) or not isinstance(item.get("requestId"), str):
            raise RuntimeError("Student product semantic case is invalid")
        quality = item.get("quality")
        exact_by_request[item["requestId"]] = (
            item.get("status") == "complete"
            and isinstance(item.get("questions"), list)
            and len(item["questions"]) == 1
            and isinstance(quality, dict)
            and quality.get("supportsExact") is True
            and quality.get("outputBudgetExhausted") is False
        )
    if set(exact_by_request) != {item.product_request_id for item in observations}:
        raise RuntimeError("Student product semantic request binding differs")
    return tuple(
        replace(
            item,
            exact_match=item.exact_match
            and exact_by_request.get(item.product_request_id, False),
        )
        for item in observations
    )


def _run_unavailable_control(
    *,
    label: str,
    base_url: str,
    owner_id: str,
    request: StudentRequest,
    expected_product_evidence: StudentEvidence,
    token: str,
    foreign_token: str,
    authenticator: _QualificationAuthenticator,
) -> StudentProductObservation:
    started = time.monotonic()
    product_request_id: str | None = None
    observed: StudentProductView | None = None
    failure_kind: str | None = None
    owner_isolation_exact = False
    header = f"Bearer {token}"
    header_count_before = authenticator.observed_header_count(header)
    try:
        status, payload = _http_json(
            base_url,
            "/v1/student-questions",
            method="POST",
            token=token,
            body=_request_wire(request),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Student product unavailable control was not accepted")
        initial = _parse_product_view(payload)
        product_request_id = initial.request_id
        owner_isolation_exact = _foreign_owner_isolation_exact(
            base_url,
            product_request_id,
            foreign_token=foreign_token,
        )
        observed = _wait_for_terminal(
            base_url,
            product_request_id,
            token=token,
            deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
            expected_evidence=(),
            expected_evidence_sha256=expected_product_evidence.evidence_sha256,
        )
    except BaseException as error:
        failure_kind = type(error).__name__
    duration = max(0, round((time.monotonic() - started) * 1_000))
    authentication_header_exact = (
        authenticator.observed_header_count(header) > header_count_before
    )
    exact = (
        observed is not None
        and observed.status == "evidence-unavailable"
        and observed.reason == "evidence-unavailable"
        and observed.conversation_concept_id == request.conversation_concept_id
        and observed.generation_sha256 == request.expected_generation_sha256
        and not observed.questions
        and authentication_header_exact
        and owner_isolation_exact
        and failure_kind is None
    )
    return StudentProductObservation(
        label,
        owner_id,
        request,
        product_request_id,
        None,
        observed,
        duration,
        exact,
        authentication_header_exact,
        owner_isolation_exact,
        False,
        failure_kind,
    )


def _cancel_capacity_ticket(
    client: AgentAdmissionClient,
    ticket: AgentAdmissionTicket,
) -> bool:
    cancelled = client.cancel(ticket)
    if cancelled.outcome == "cancelled":
        return True
    if (
        cancelled.outcome != "cancellation-requested"
        or cancelled.cancellation_reason != "client-requested"
    ):
        raise RuntimeError("Student product capacity cancellation identity differs")
    acknowledged = client.acknowledge_cancellation(ticket)
    if acknowledged.outcome != "cancelled":
        raise RuntimeError("Student product capacity cancellation was not acknowledged")
    return True


def _run_cancelled_control(
    *,
    base_url: str,
    tenant_id: str,
    owner_id: str,
    request: StudentRequest,
    expected_evidence: tuple[StudentExpectedEvidence, ...],
    expected_product_evidence: StudentEvidence,
    token: str,
    foreign_token: str,
    authenticator: _QualificationAuthenticator,
    admission_socket_path: Path,
    dsn: str,
    observe_admission: Callable[[], Mapping[str, object]],
) -> StudentProductObservation:
    started = time.monotonic()
    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    holders: list[AgentAdmissionTicket] = []
    product_request_id: str | None = None
    observed: StudentProductView | None = None
    failure_kind: str | None = None
    owner_isolation_exact = False
    header = f"Bearer {token}"
    header_count_before = authenticator.observed_header_count(header)
    before = dict(observe_admission())
    cleanup_error: BaseException | None = None
    try:
        for index in range(_BROKER_ACTIVE_CAPACITY):
            ticket = admission.new_ticket()
            holders.append(ticket)
            principal = AuthenticatedPrincipal(
                tenant_id=tenant_id,
                subject_id=f"student-product-holder-{index}",
                client_id="student-product-qualification",
                scopes=frozenset(),
            )
            response = admission.submit(
                ticket,
                principal=principal,
                work=AgentWorkSpec(
                    role=AgentRole.STUDENT,
                    purpose=AgentPurpose.LEARNING_QUESTIONS,
                    route=ExecutionRoute.RAPID_AUTOMATION,
                    scheduling_class=SchedulingClass.BACKGROUND_LLM,
                ),
                source_sha256=hashlib.sha256(
                    f"{tenant_id}\0student-product-holder\0{index}".encode()
                ).hexdigest(),
                remaining_deadline_ms=90_000,
            )
            if response.outcome != "admitted":
                raise RuntimeError("Student product capacity holder was not admitted")
        status, payload = _http_json(
            base_url,
            "/v1/student-questions",
            method="POST",
            token=token,
            body=_request_wire(request),
        )
        if status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Student product cancellation control was not accepted")
        initial = _parse_product_view(payload)
        product_request_id = initial.request_id
        owner_isolation_exact = _foreign_owner_isolation_exact(
            base_url,
            product_request_id,
            foreign_token=foreign_token,
        )
        _wait_for_student_tool_audit_count(
            dsn,
            tenant_id=tenant_id,
            owner_id=owner_id,
            minimum_count=2,
            deadline=started + 15.0,
        )
        time.sleep(0.05)
        cancel_status, cancelled_payload = _http_json(
            base_url,
            f"/v1/student-questions/{product_request_id}",
            method="DELETE",
            token=token,
        )
        if cancel_status != HTTPStatus.ACCEPTED:
            raise RuntimeError("Student product cancellation was not accepted")
        cancelled = _parse_product_view(cancelled_payload)
        if cancelled.request_id != product_request_id or cancelled.status not in {
            "cancellation-requested",
            "cancelled",
        }:
            raise ValueError("Student product cancellation view differs")
        observed = _wait_for_terminal(
            base_url,
            product_request_id,
            token=token,
            deadline=started + _NORMAL_WAVE_TIMEOUT_SECONDS,
            expected_evidence=expected_evidence,
            expected_evidence_sha256=expected_product_evidence.evidence_sha256,
        )
    except BaseException as error:
        failure_kind = type(error).__name__
    finally:
        for ticket in reversed(holders):
            try:
                if not _cancel_capacity_ticket(admission, ticket):
                    raise RuntimeError(
                        "Student product capacity holder was not contained"
                    )
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if dict(observe_admission()) != before:
            cleanup_error = cleanup_error or RuntimeError(
                "Student product cancellation changed broker identity"
            )
        if cleanup_error is not None:
            raise cleanup_error
    duration = max(0, round((time.monotonic() - started) * 1_000))
    authentication_header_exact = (
        authenticator.observed_header_count(header) > header_count_before
    )
    exact = (
        observed is not None
        and observed.status == "cancelled"
        and observed.reason == "client-cancelled"
        and observed.conversation_concept_id == request.conversation_concept_id
        and observed.generation_sha256 == request.expected_generation_sha256
        and not observed.questions
        and authentication_header_exact
        and owner_isolation_exact
        and failure_kind is None
    )
    return StudentProductObservation(
        "capacity-held-cancellation",
        owner_id,
        request,
        product_request_id,
        None,
        observed,
        duration,
        exact,
        authentication_header_exact,
        owner_isolation_exact,
        False,
        failure_kind,
    )


def _wait_for_student_tool_audit_count(
    dsn: str,
    *,
    tenant_id: str,
    owner_id: str,
    minimum_count: int,
    deadline: float,
) -> None:
    while time.monotonic() < deadline:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            row = connection.execute(
                """SELECT count(*) FROM yap_knowledge_tool_audit
                   WHERE tenant_id = %s AND subject_id = %s
                     AND agent_id = 'student'
                     AND operation = 'conversation-evidence'""",
                (tenant_id, owner_id),
            ).fetchone()
        if row is not None and row[0] >= minimum_count:
            return
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        "Student product evidence read was not observed before cancellation"
    )


def _run_product_workload(
    *,
    base_url: str,
    corpus: StudentQualificationCorpus,
    semantic_acceptance: StudentQualificationAcceptance,
    product_acceptance: StudentProductAcceptance,
    tenant_id: str,
    generation_sha256: str,
    expected_evidence: Mapping[str, tuple[StudentExpectedEvidence, ...]],
    expected_product_evidence: Mapping[tuple[str, str], StudentEvidence],
    tokens_by_owner: Mapping[str, str],
    authenticator: _QualificationAuthenticator,
    admission_socket_path: Path,
    dsn: str,
    observe_provider: Callable[[], Mapping[str, object]],
    observe_admission: Callable[[], Mapping[str, object]],
) -> tuple[
    tuple[StudentProductObservation, ...],
    StudentQualificationResult,
    Mapping[str, bool],
    bool,
]:
    if (
        len(corpus.cases) != product_acceptance.case_count
        or len({case.owner_id for case in corpus.cases})
        != product_acceptance.owner_count
        or set(expected_evidence) != {case.case_id for case in corpus.cases}
    ):
        raise ValueError("Student product workload shape differs")
    expected_product_keys = {
        (case.owner_id, case.concept_id) for case in corpus.cases
    } | {
        (_CROSS_OWNER, corpus.cases[0].concept_id),
        (_CROSS_OWNER, "meetings/absent-probe"),
    }
    if set(expected_product_evidence) != expected_product_keys:
        raise ValueError("Student product evidence authority shape differs")
    owners = tuple(case.owner_id for case in corpus.cases)
    foreign_tokens = {
        owner: tokens_by_owner[owners[(index + 1) % len(owners)]]
        for index, owner in enumerate(owners)
    }
    expected_by_concept = {
        case.concept_id: expected_evidence[case.case_id] for case in corpus.cases
    }
    authentication_probe = _probe_http_authentication(base_url)
    service = _HttpStudentService(
        base_url=base_url,
        tokens_by_owner=tokens_by_owner,
        foreign_tokens_by_owner=foreign_tokens,
        expected_evidence_by_concept=expected_by_concept,
        expected_product_evidence=expected_product_evidence,
        authenticator=authenticator,
    )
    try:
        semantic_result = evaluate_student_qualification(
            service=service,
            corpus=corpus,
            acceptance=semantic_acceptance,
            tenant_id=tenant_id,
            generation_sha256=generation_sha256,
            expected_evidence=expected_evidence,
            observe_warm_state=observe_provider,
            observe_admission_state=observe_admission,
        )
    except BaseException:
        service.cancel_active()
        raise
    normal = _finalize_normal_observations(
        service.observations(),
        semantic_result,
    )
    if (
        len(normal) != product_acceptance.synchronized_owner_count
        or len({item.owner_id for item in normal}) != product_acceptance.owner_count
    ):
        raise RuntimeError("Student product synchronized wave differs")

    first = corpus.cases[0]
    cross_token = tokens_by_owner[_CROSS_OWNER]
    hidden = _run_unavailable_control(
        label="hidden-source",
        base_url=base_url,
        owner_id=_CROSS_OWNER,
        request=StudentRequest(
            conversation_concept_id=first.concept_id,
            expected_generation_sha256=generation_sha256,
            topic=first.topic,
        ),
        expected_product_evidence=expected_product_evidence[
            (_CROSS_OWNER, first.concept_id)
        ],
        token=cross_token,
        foreign_token=tokens_by_owner[first.owner_id],
        authenticator=authenticator,
    )
    absent = _run_unavailable_control(
        label="absent-source",
        base_url=base_url,
        owner_id=_CROSS_OWNER,
        request=StudentRequest(
            conversation_concept_id="meetings/absent-probe",
            expected_generation_sha256=generation_sha256,
            topic="absent evidence",
        ),
        expected_product_evidence=expected_product_evidence[
            (_CROSS_OWNER, "meetings/absent-probe")
        ],
        token=cross_token,
        foreign_token=tokens_by_owner[first.owner_id],
        authenticator=authenticator,
    )
    cancelled = _run_cancelled_control(
        base_url=base_url,
        tenant_id=tenant_id,
        owner_id=first.owner_id,
        request=StudentRequest(
            conversation_concept_id=first.concept_id,
            expected_generation_sha256=generation_sha256,
            topic=first.topic,
        ),
        expected_evidence=expected_evidence[first.case_id],
        expected_product_evidence=expected_product_evidence[
            (first.owner_id, first.concept_id)
        ],
        token=tokens_by_owner[first.owner_id],
        foreign_token=foreign_tokens[first.owner_id],
        authenticator=authenticator,
        admission_socket_path=admission_socket_path,
        dsn=dsn,
        observe_admission=observe_admission,
    )
    observations = (*normal, hidden, absent, cancelled)
    hidden_only_indistinguishable = (
        hidden.observed is not None
        and absent.observed is not None
        and hidden.observed.public_terminal_shape()
        == absent.observed.public_terminal_shape()
    )
    if len(observations) != product_acceptance.query_count:
        raise RuntimeError("Student product observation cardinality differs")
    return (
        observations,
        semantic_result,
        authentication_probe,
        hidden_only_indistinguishable,
    )


def _start_http_server(
    runtime: StudentProductRuntime,
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
        student_question_service=runtime.service,
    )
    host, port = server.server_address[:2]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        name="student-product-http",
        daemon=False,
    )
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_http_server(server, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("Student product HTTP worker was not contained")


def _expected_audit_outcome(status: str) -> str:
    try:
        return {
            "complete": "succeeded",
            "evidence-unavailable": "unavailable",
            "cancelled": "cancelled",
            "failed": "failed",
        }[status]
    except KeyError as error:
        raise ValueError("Student product terminal status differs") from error


def _bind_internal_request_ids(
    dsn: str,
    observations: Sequence[StudentProductObservation],
    *,
    tenant_id: str,
) -> tuple[StudentProductObservation, ...]:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        rows = connection.execute(
            """SELECT subject_id, request_id, request_sha256,
                      outcome, reason, result_count
               FROM yap_student_result_audit
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
    remaining = list(rows)
    bound: list[StudentProductObservation] = []
    for observation in observations:
        if observation.observed is None or observation.product_request_id is None:
            raise RuntimeError("Student product terminal observation is incomplete")
        expected = (
            observation.owner_id,
            student_request_sha256(observation.request),
            _expected_audit_outcome(observation.observed.status),
            observation.observed.reason,
            len(observation.observed.questions),
        )
        matched = [
            row
            for row in remaining
            if (row[0], row[2], row[3], row[4], row[5]) == expected
        ]
        if len(matched) != 1:
            raise RuntimeError("Student product durable request binding differs")
        row = matched[0]
        remaining.remove(row)
        internal_request_id = row[1]
        if (
            not isinstance(internal_request_id, str)
            or _INTERNAL_REQUEST_ID.fullmatch(internal_request_id) is None
            or internal_request_id == observation.product_request_id
        ):
            raise RuntimeError("Student product internal request identity differs")
        bound.append(replace(observation, internal_request_id=internal_request_id))
    if remaining:
        raise RuntimeError("Student product durable result cardinality differs")
    return tuple(bound)


def _verify_product_database_state(
    dsn: str,
    *,
    tenant_id: str,
    generation_sha256: str,
    observations: Sequence[StudentProductObservation],
    corpus: StudentQualificationCorpus,
    expected_product_evidence: Mapping[tuple[str, str], StudentEvidence],
    profile,
) -> dict[str, bool]:
    expected_by_request = {item.internal_request_id: item for item in observations}
    if None in expected_by_request or len(expected_by_request) != len(observations):
        raise RuntimeError("Student product bound request identities differ")
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        active = connection.execute(
            """SELECT generation_sha256 FROM yap_knowledge_active_builds
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        build_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_builds WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        admission_count = connection.execute(
            """SELECT count(*) FROM yap_knowledge_source_admissions
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchone()
        proposal_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_proposals WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        result_rows = connection.execute(
            """SELECT subject_id, request_id, request_sha256,
                      conversation_concept_id, work_sha256,
                      purpose, route, scheduling_class, provider_generation,
                      candidate_id, model, model_revision, runtime_id,
                      profile_sha256, candidate_lock_sha256,
                      generation_sha256, evidence_sha256,
                      permission_hash, authorization_hash,
                      outcome, reason, result_count
               FROM yap_student_result_audit
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        tool_rows = connection.execute(
            """SELECT subject_id, operation, outcome, result_count,
                      generation_sha256,
                      permission_hash, authorization_hash
               FROM yap_knowledge_tool_audit
               WHERE tenant_id = %s AND agent_id = 'student'""",
            (tenant_id,),
        ).fetchall()

    result_exact = len(result_rows) == len(observations)
    provider_bound_count = 0
    for row in result_rows:
        observation = expected_by_request.get(row[1])
        if observation is None or observation.observed is None:
            result_exact = False
            continue
        view = observation.observed
        expected_pack = expected_product_evidence.get(
            (observation.owner_id, observation.request.conversation_concept_id)
        )
        if expected_pack is None:
            result_exact = False
            continue
        succeeded = view.status == "complete"
        provider_bound_count += row[8] is not None
        result_exact = result_exact and (
            row[0] == observation.owner_id
            and row[2] == student_request_sha256(observation.request)
            and row[3] == observation.request.conversation_concept_id
            and row[4] == student_work_sha256(observation.request, expected_pack)
            and row[5:8] == ("learning-questions", "rapid-automation", "background-llm")
            and (
                (isinstance(row[8], int) and row[8] > 0)
                if succeeded
                else row[8] is None
            )
            and row[9] == profile.candidate_id
            and row[10] == profile.expected_model
            and row[11] == profile.model_revision
            and row[12] == profile.runtime_id
            and row[13] == profile.profile_sha256
            and row[14] == profile.candidate_lock_sha256
            and row[15] == generation_sha256
            and row[16] == expected_pack.evidence_sha256
            and row[17] == expected_pack.permission_hash
            and row[18] == expected_pack.authorization_hash
            and row[19] == _expected_audit_outcome(view.status)
            and row[20] == view.reason
            and row[21] == len(view.questions)
            and view.evidence_sha256 == expected_pack.evidence_sha256
        )

    expected_tool_rows: list[tuple[object, ...]] = []
    for observation in observations:
        expected_pack = expected_product_evidence.get(
            (observation.owner_id, observation.request.conversation_concept_id)
        )
        if expected_pack is None:
            raise RuntimeError("Student product expected audit evidence differs")
        expected_tool_rows.append(
            (
                observation.owner_id,
                "conversation-evidence",
                "succeeded",
                len(expected_pack.items),
                generation_sha256,
                expected_pack.permission_hash,
                expected_pack.authorization_hash,
            )
        )
    checks = {
        "activeGenerationUnchanged": active == [(generation_sha256,)],
        "singleGenerationRetained": build_count == (1,),
        "singleSourceAdmissionRetained": admission_count == (1,),
        "proposalWritesAbsent": proposal_count == (0,),
        "studentResultAuditExact": result_exact,
        "studentToolAuditExact": sorted(tool_rows) == sorted(expected_tool_rows),
        "completeProviderGenerationExact": provider_bound_count
        == sum(
            item.observed is not None and item.observed.status == "complete"
            for item in observations
        ),
        "productInternalRequestBindingExact": len(expected_by_request)
        == len(observations),
    }
    if not all(checks.values()):
        raise RuntimeError("Student product durable state differs")
    return checks


def _install_and_preflight_database(dsn: str, *, tenant_id: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_student_result_audit_schema(connection)
        counts = connection.execute(
            """SELECT
                (SELECT count(*) FROM yap_knowledge_source_admissions
                 WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_builds
                 WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_active_builds
                 WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_proposals
                 WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_knowledge_tool_audit
                 WHERE tenant_id = %s),
                (SELECT count(*) FROM yap_student_result_audit
                 WHERE tenant_id = %s)""",
            (tenant_id,) * 6,
        ).fetchone()
    if counts != (0, 0, 0, 0, 0, 0):
        raise RuntimeError("Student product qualification tenant is not fresh")


def _restart_database(
    database: OwnedPostgresKnowledgeRuntime,
    started: StartedKnowledgeDatabase,
) -> StartedKnowledgeDatabase:
    restarted = database.restart(timeout_seconds=120)
    if (
        restarted.container_id != started.container_id
        or restarted.process_id == started.process_id
    ):
        raise RuntimeError("Student product database restart identity differs")
    return restarted


def _require_exact_teardown(teardown: Mapping[str, bool]) -> None:
    required = {
        "containerAbsent",
        "listenerAbsent",
        "networkAbsent",
        "ownedProcessAbsent",
        "sameLabelOwnersAbsent",
        "volumeAbsent",
    }
    if set(teardown) != required or not all(teardown.values()):
        raise RuntimeError("Student product database teardown differs")


def _private_observations(
    observations: Sequence[StudentProductObservation],
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for item in observations:
        if (
            item.product_request_id is None
            or item.internal_request_id is None
            or item.observed is None
        ):
            raise RuntimeError("Student product private observation is incomplete")
        values.append(
            {
                "label": item.label,
                "ownerId": item.owner_id,
                "productRequestId": item.product_request_id,
                "internalRequestId": item.internal_request_id,
                "requestSha256": student_request_sha256(item.request),
                "status": item.observed.status,
                "reason": item.observed.reason,
                "evidenceSha256": item.observed.evidence_sha256,
                "durationMilliseconds": item.duration_milliseconds,
                "questionCount": len(item.observed.questions),
                "exactMatch": item.exact_match,
                "authenticationHeaderExact": item.authentication_header_exact,
                "ownerIsolationExact": item.owner_isolation_exact,
                "normal": item.normal,
                "failureKind": item.failure_kind,
            }
        )
    return values


def run_student_product_qualification_gate(
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
    product_acceptance = load_student_product_acceptance(
        root / "server/student-product-acceptance.json"
    )
    semantic_acceptance = load_student_qualification_acceptance(
        root / "server/student-acceptance.json"
    )
    corpus = load_student_qualification_corpus(
        root / "server/student-workload-fixtures.json"
    )
    rapid_profile_path = root / "server/agent-service-profiles/rapid-automation.json"
    complex_profile_path = (
        root / "server/agent-service-profiles/complex-orchestration.json"
    )
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    rapid_profile = load_student_service_profile(
        rapid_profile_path,
        candidate_lock_path,
    )
    complex_profile = load_complex_agent_vllm_service_profile(
        complex_profile_path,
        candidate_lock_path,
    )
    if rapid_profile.candidate_lock_sha256 != complex_profile.candidate_lock_sha256:
        raise ValueError("Student product broker candidate lock identity differs")
    _require_full_rapid_profile(
        rapid_profile.maximum_sequences,
        rapid_profile.launch_arguments,
    )
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"student-product-q-{secrets.token_hex(8)}"
    qualification_run_id = f"run-{secrets.token_hex(8)}"

    def observe_provider() -> dict[str, object]:
        value = read_service_state(rapid_state_path)
        validate_state_identity(value, rapid_profile)
        probe_exact_service(rapid_profile)
        return value

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

    capacity_evidence = probe_agent_admission_broker_capacity(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        work=AgentWorkSpec(
            role=AgentRole.STUDENT,
            purpose=AgentPurpose.LEARNING_QUESTIONS,
            route=ExecutionRoute.RAPID_AUTOMATION,
            scheduling_class=SchedulingClass.BACKGROUND_LLM,
        ),
        expected_route=ExecutionRoute.RAPID_AUTOMATION,
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
    runtime: StudentProductRuntime | None = None
    server = None
    server_thread: threading.Thread | None = None
    generation = None
    expected_evidence: Mapping[str, tuple[StudentExpectedEvidence, ...]] | None = None
    expected_product_evidence: Mapping[tuple[str, str], StudentEvidence] | None = None
    observations: tuple[StudentProductObservation, ...] | None = None
    semantic_result: StudentQualificationResult | None = None
    authentication_probe: Mapping[str, bool] | None = None
    hidden_only_indistinguishable = False
    database_state: dict[str, bool] | None = None
    teardown: Mapping[str, bool] | None = None
    worker_containment_met = False
    try:
        started = database.start(timeout_seconds=120)
        _install_and_preflight_database(started.dsn, tenant_id=tenant_id)
        with tempfile.TemporaryDirectory(
            prefix="yap-student-product-qualification-"
        ) as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            generation = _initialize_student_knowledge(
                started.dsn,
                corpus,
                private_runtime_root / "okf",
                tenant_id=tenant_id,
            )
            restarted = _restart_database(database, started)
            started = restarted
            dsn_path = private_runtime_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, restarted.dsn)
            expected_evidence = _expected_student_evidence(generation, corpus)
            expected_product_evidence = _expected_product_evidence(
                generation,
                corpus,
                tenant_id=tenant_id,
            )
            tokens_by_owner = {
                owner: f"product-{secrets.token_hex(24)}"
                for owner in (*[case.owner_id for case in corpus.cases], _CROSS_OWNER)
            }
            authenticator = _QualificationAuthenticator(
                tenant_id=tenant_id,
                tokens={token: owner for owner, token in tokens_by_owner.items()},
            )
            runtime = build_student_product_runtime(
                {
                    STUDENT_RUNTIME: "warm_qwen",
                    STUDENT_ADMISSION_SOCKET: str(admission_socket_path),
                    STUDENT_PROFILE: str(rapid_profile_path),
                    STUDENT_CANDIDATE_LOCK: str(candidate_lock_path),
                    STUDENT_KNOWLEDGE_DSN_FILE: str(dsn_path),
                },
                authenticated_team_mode=True,
            )
            if runtime is None:
                raise RuntimeError("Student product runtime is unavailable")
            server, server_thread, base_url = _start_http_server(
                runtime,
                authenticator,
            )
            (
                observations,
                semantic_result,
                authentication_probe,
                hidden_only_indistinguishable,
            ) = _run_product_workload(
                base_url=base_url,
                corpus=corpus,
                semantic_acceptance=semantic_acceptance,
                product_acceptance=product_acceptance,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                expected_evidence=expected_evidence,
                expected_product_evidence=expected_product_evidence,
                tokens_by_owner=tokens_by_owner,
                authenticator=authenticator,
                admission_socket_path=admission_socket_path,
                dsn=restarted.dsn,
                observe_provider=observe_provider,
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
            observations = _bind_internal_request_ids(
                result_restarted.dsn,
                observations,
                tenant_id=tenant_id,
            )
            database_state = _verify_product_database_state(
                result_restarted.dsn,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                observations=observations,
                corpus=corpus,
                expected_product_evidence=expected_product_evidence,
                profile=rapid_profile,
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
        generation is None
        or expected_evidence is None
        or expected_product_evidence is None
        or observations is None
        or semantic_result is None
        or authentication_probe is None
        or database_state is None
        or teardown is None
    ):
        raise RuntimeError("Student product qualification evidence is incomplete")
    semantic_qualification_exact = (
        semantic_result.public_evidence.get("outcome")
        == "student-learning-questions-qualified"
    )
    public = _evaluate_product_observations(
        observations,
        acceptance=product_acceptance,
        authentication_probe=authentication_probe,
        semantic_qualification_exact=semantic_qualification_exact,
        hidden_only_indistinguishable=hidden_only_indistinguishable,
        worker_containment_met=worker_containment_met,
    )
    if public["qualified"] is not True:
        raise RuntimeError("Student product qualification did not meet acceptance")
    candidate.verify_unchanged(runner=runner)
    semantic: dict[str, object] = dict(public)
    semantic.update(
        {
            "schemaVersion": 1,
            "qualificationScope": "student-authenticated-product-server-boundary",
            "outcome": "student-authenticated-product-server-boundary-qualified",
            "acceptancePlanSha256": product_acceptance.plan_sha256,
            "semanticAcceptancePlanSha256": semantic_acceptance.plan_sha256,
            "corpusId": corpus.corpus_id,
            "corpusSha256": corpus.corpus_sha256,
            "semanticEvidenceSha256": semantic_result.public_evidence["evidenceSha256"],
            "qualificationTenantSha256": hashlib.sha256(tenant_id.encode()).hexdigest(),
            "qualificationRunSha256": hashlib.sha256(
                qualification_run_id.encode()
            ).hexdigest(),
            "authentication": dict(authentication_probe),
            "workload": {
                "route": "rapid-automation",
                "schedulingClass": "background-llm",
                "model": rapid_profile.expected_model,
                "maximumOutputTokens": _MAXIMUM_OUTPUT_TOKENS,
                "maximumSequences": rapid_profile.maximum_sequences,
                "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
                "brokerExpectedCapacityObserved": capacity_evidence[
                    "expectedCapacityObserved"
                ],
                "overflowOwnerQueued": capacity_evidence["overflowOwnerQueued"],
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
        private_destination,
        {
            "schemaVersion": 1,
            "privacyScope": "private-student-product-qualification",
            "tenantId": tenant_id,
            "qualificationRunId": qualification_run_id,
            "publicEvidence": receipt,
            "qualification": {
                "acceptancePlanSha256": product_acceptance.plan_sha256,
                "semanticAcceptancePlanSha256": semantic_acceptance.plan_sha256,
                "corpusSha256": corpus.corpus_sha256,
                "observations": _private_observations(observations),
                "semantic": semantic_result.private_evidence,
            },
        },
    )
    return receipt


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError(
            "Student product qualification requires the private ARM64 host"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify the authenticated Student product vertical",
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
    receipt = run_student_product_qualification_gate(
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
        == "student-authenticated-product-server-boundary-qualified"
        else 1
    )


__all__ = [
    "StudentProductAcceptance",
    "StudentProductObservation",
    "StudentProductView",
    "load_student_product_acceptance",
    "run_student_product_qualification_gate",
]


if __name__ == "__main__":
    raise SystemExit(main())
