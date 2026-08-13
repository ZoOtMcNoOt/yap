"""Run the exact checked Auditor grounded cited-report qualification."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import subprocess
import tempfile
import threading
from typing import Callable, Mapping, Sequence

import psycopg

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
from yap_server.agents.auditor import (
    AuditorEvidencePack,
    AuditorEvidenceChanged,
    AuditorRequest,
    PostgresAuditorEvidenceReader,
    auditor_request_sha256,
    auditor_work_sha256,
)
from yap_server.agents.auditor_model import (
    MAXIMUM_AUDITOR_INPUT_TOKENS,
    AuditorDecision,
)
from yap_server.agents.auditor_result_audit import (
    AuditorRuntimeAuditIdentity,
    PostgresAuditorResultAuditor,
    install_auditor_result_audit_schema,
)
from yap_server.agents.auditor_runtime import (
    AUDITOR_ADMISSION_SOCKET,
    AUDITOR_CANDIDATE_LOCK,
    AUDITOR_KNOWLEDGE_DSN_FILE,
    AUDITOR_PROFILE,
    AUDITOR_RUNTIME,
    AuditorRuntime,
    build_auditor_runtime,
    load_auditor_service_profile,
)
from yap_server.agents.auditor_service import (
    AUDITOR_OPERATION_DEADLINE_SECONDS,
    AUDITOR_TERMINAL_AUDIT_DEADLINE_SECONDS,
    AUDITOR_WORKFLOW_DEADLINE_SECONDS,
    AuditorJobView,
    AuditorService,
)
from yap_server.auth import AuthenticatedPrincipal
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
from yap_server.evaluation.private_json_evidence import (
    write_new_private_json_evidence,
)
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_source_admission import (
    admit_curated_knowledge_generation,
)
from yap_server.knowledge.knowledge_tool_audit import (
    install_knowledge_tool_audit_schema,
)
from yap_server.knowledge.knowledge_tool_contract import (
    KnowledgeGenerationStale,
    KnowledgeToolCancelled,
)
from yap_server.knowledge.okf_compiler import (
    CompiledKnowledgeGeneration,
    compile_okf_bundle,
)
from yap_server.knowledge.permission_policy import permission_record
from yap_server.pools.agent_vllm_service_profile import (
    RAPID_AUTOMATION_PROFILE_SHA256,
    AgentVllmServiceProfile,
)
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
    private_postgres_connection_factory,
)

from .auditor_qualification import (
    AuditorBoundQualificationCorpus,
    AuditorQualificationAcceptance,
    AuditorQualificationCorpus,
    AuditorQualificationInvocation,
    AuditorQualificationRenderedGeneration,
    AuditorQualificationResult,
    bind_auditor_compiled_corpus,
    build_auditor_qualification_invocations,
    evaluate_auditor_qualification,
    load_auditor_qualification_acceptance,
    load_auditor_qualification_corpus,
    render_auditor_qualification_generations,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_CURATOR_ID = "auditor-qualification-curator"
_SOURCE_PATH = "server/auditor-workload-fixtures.json"
_BROKER_ACTIVE_CAPACITY = 8
_MAXIMUM_P95_MILLISECONDS = 85_000
_MAXIMUM_OUTPUT_TOKENS = 512
_MAXIMUM_INPUT_TOKENS = 7_680
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TEARDOWN_KEYS = {
    "containerAbsent",
    "listenerAbsent",
    "networkAbsent",
    "ownedProcessAbsent",
    "sameLabelOwnersAbsent",
    "volumeAbsent",
}


@dataclass(frozen=True, slots=True)
class _InitializedKnowledge:
    rendered: tuple[AuditorQualificationRenderedGeneration, ...]
    compiled: dict[str, CompiledKnowledgeGeneration]
    bound: AuditorBoundQualificationCorpus


@dataclass(slots=True)
class _ControlledModeEvidence:
    client_cancelled_after_admission: bool = False
    deadline_after_admission: bool = False
    invalid_output_after_admission: bool = False
    stale_generation_reauthorization: bool = False
    synchronized_service_calls: int = 0
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def record_synchronized_service_call(self) -> None:
        with self._lock:
            self.synchronized_service_calls += 1

    def require_complete(self, *, expected_synchronized_service_calls: int) -> None:
        if not all(
            (
                self.client_cancelled_after_admission,
                self.deadline_after_admission,
                self.invalid_output_after_admission,
                self.stale_generation_reauthorization,
                self.synchronized_service_calls == expected_synchronized_service_calls,
            )
        ):
            raise RuntimeError("Auditor controlled-mode evidence is incomplete")


@dataclass(frozen=True, slots=True)
class _AdmissionExchange:
    command: str
    request_id: str
    outcome: str
    work: AgentWorkSpec | None = None
    cancellation_reason: str | None = None


class _ObservedAuditorAdmission:
    """Delegate to the production client while recording exact Auditor lease use."""

    def __init__(self, delegate: AgentAdmissionClient) -> None:
        self._delegate = delegate
        self._lock = threading.Lock()
        self._tickets: list[AgentAdmissionTicket] = []
        self._exchanges: list[_AdmissionExchange] = []

    def new_ticket(self) -> AgentAdmissionTicket:
        ticket = self._delegate.new_ticket()
        with self._lock:
            self._tickets.append(ticket)
        return ticket

    def submit(
        self,
        ticket: AgentAdmissionTicket,
        *,
        principal: AuthenticatedPrincipal,
        work: AgentWorkSpec,
        source_sha256: str,
        remaining_deadline_ms: int,
    ) -> AgentAdmission:
        result = self._delegate.submit(
            ticket,
            principal=principal,
            work=work,
            source_sha256=source_sha256,
            remaining_deadline_ms=remaining_deadline_ms,
        )
        self._record("submit", ticket, result, work=work)
        return result

    def status(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        result = self._delegate.status(ticket)
        self._record("status", ticket, result)
        return result

    def cancel(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        result = self._delegate.cancel(ticket)
        self._record("cancel", ticket, result)
        return result

    def complete(self, ticket: AgentAdmissionTicket) -> AgentAdmission:
        result = self._delegate.complete(ticket)
        self._record("complete", ticket, result)
        return result

    def acknowledge_cancellation(
        self,
        ticket: AgentAdmissionTicket,
    ) -> AgentAdmission:
        result = self._delegate.acknowledge_cancellation(ticket)
        self._record("acknowledge-cancellation", ticket, result)
        return result

    def require_exact_lifecycle(
        self,
        *,
        invocation_modes: Mapping[str, str],
    ) -> dict[str, object]:
        with self._lock:
            tickets = tuple(self._tickets)
            exchanges = tuple(self._exchanges)
        ticket_by_id = {ticket.request_id: ticket for ticket in tickets}
        submits = tuple(item for item in exchanges if item.command == "submit")
        completes = tuple(item for item in exchanges if item.command == "complete")
        cancels = tuple(item for item in exchanges if item.command == "cancel")
        acknowledgements = tuple(
            item for item in exchanges if item.command == "acknowledge-cancellation"
        )
        submitted_ids = {item.request_id for item in submits}
        completed_ids = {item.request_id for item in completes}
        cancelled_ids = {item.request_id for item in cancels}
        acknowledged_ids = {item.request_id for item in acknowledgements}
        terminal = {
            request_id: self._delegate.status(ticket).outcome
            for request_id, ticket in ticket_by_id.items()
            if request_id in submitted_ids
        }
        expected_work = AgentWorkSpec(
            role=AgentRole.AUDITOR,
            purpose=AgentPurpose.KNOWLEDGE_AUDIT,
            route=ExecutionRoute.COMPLEX_ORCHESTRATION,
            scheduling_class=SchedulingClass.IDLE_ONLY,
        )
        expected_modes = {
            "normal",
            "pre-cancelled",
            "client-cancelled",
            "deadline",
            "stale-generation",
            "invalid-output",
        }
        expected_unsubmitted_ids = {
            request_id
            for request_id, mode in invocation_modes.items()
            if mode == "pre-cancelled"
        }
        expected_client_cancelled_ids = {
            request_id
            for request_id, mode in invocation_modes.items()
            if mode == "client-cancelled"
        }
        expected_deadline_ids = {
            request_id
            for request_id, mode in invocation_modes.items()
            if mode == "deadline"
        }
        expected_cancelled_ids = expected_client_cancelled_ids | expected_deadline_ids
        expected_completed_ids = (
            set(invocation_modes) - expected_unsubmitted_ids - expected_cancelled_ids
        )
        cancel_by_id = {item.request_id: item for item in cancels}
        acknowledgement_outcomes = {
            item.request_id: item.outcome for item in acknowledgements
        }
        exact = (
            len(invocation_modes) == 29
            and set(invocation_modes.values()) <= expected_modes
            and sum(mode == "normal" for mode in invocation_modes.values()) == 24
            and all(
                sum(mode == expected for mode in invocation_modes.values()) == 1
                for expected in expected_modes - {"normal"}
            )
            and len(tickets) == 29
            and len(ticket_by_id) == 29
            and set(ticket_by_id) == set(invocation_modes)
            and len(submits) == len(submitted_ids) == 28
            and submitted_ids <= set(ticket_by_id)
            and {item.request_id for item in exchanges}.issubset(set(ticket_by_id))
            and all(
                item.outcome == "admitted" and item.work == expected_work
                for item in submits
            )
            and len(completes) == len(completed_ids) == 26
            and all(item.outcome == "completed" for item in completes)
            and len(cancels) == len(cancelled_ids) == 2
            and len(acknowledgements) == len(acknowledged_ids) == 2
            and all(
                request_id in cancel_by_id
                and cancel_by_id[request_id].outcome == "cancellation-requested"
                and cancel_by_id[request_id].cancellation_reason == "client-requested"
                and acknowledgement_outcomes.get(request_id) == "cancelled"
                for request_id in expected_client_cancelled_ids
            )
            and all(
                request_id in cancel_by_id
                and cancel_by_id[request_id].outcome == "cancellation-requested"
                and cancel_by_id[request_id].cancellation_reason == "deadline-exceeded"
                and acknowledgement_outcomes.get(request_id) == "deadline-exceeded"
                for request_id in expected_deadline_ids
            )
            and completed_ids.isdisjoint(cancelled_ids)
            and cancelled_ids == acknowledged_ids
            and completed_ids | cancelled_ids == submitted_ids
            and set(ticket_by_id) - submitted_ids == expected_unsubmitted_ids
            and completed_ids == expected_completed_ids
            and cancelled_ids == expected_cancelled_ids
            and sum(outcome == "completed" for outcome in terminal.values()) == 26
            and sum(outcome == "cancelled" for outcome in terminal.values()) == 1
            and sum(outcome == "deadline-exceeded" for outcome in terminal.values())
            == 1
        )
        if not exact:
            raise RuntimeError("Auditor admission lifecycle evidence differs")
        return {
            "ticketCount": len(tickets),
            "submittedTicketCount": len(submits),
            "completedTicketCount": len(completes),
            "cancelledTicketCount": len(cancels),
            "clientCancelledTicketCount": len(expected_client_cancelled_ids),
            "deadlineExpiredTicketCount": len(expected_deadline_ids),
            "preCancelledUnsubmittedTicketCount": 1,
            "singleLeasePerInvocationExact": True,
            "allSubmittedTicketsTerminal": True,
        }

    def _record(
        self,
        command: str,
        ticket: AgentAdmissionTicket,
        result: AgentAdmission,
        *,
        work: AgentWorkSpec | None = None,
    ) -> None:
        with self._lock:
            self._exchanges.append(
                _AdmissionExchange(
                    command,
                    ticket.request_id,
                    result.outcome,
                    work,
                    result.cancellation_reason,
                )
            )


def run_auditor_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Auditor on the already-warm full complex route."""

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
    acceptance = load_auditor_qualification_acceptance(
        root / "server/auditor-acceptance.json"
    )
    corpus = load_auditor_qualification_corpus(
        root / "server/auditor-workload-fixtures.json"
    )
    _require_exact_deadline_contract(acceptance.maximum_normal_p95_milliseconds)

    profile_path = root / "server/agent-service-profiles/complex-orchestration.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_auditor_service_profile(profile_path, candidate_lock_path)
    _require_full_complex_profile(
        profile.maximum_sequences,
        profile.batch_invariant,
        profile.launch_arguments,
    )
    if (
        acceptance.maximum_normal_p95_milliseconds != _MAXIMUM_P95_MILLISECONDS
        or profile.maximum_sequences != _BROKER_ACTIVE_CAPACITY
    ):
        raise ValueError("Auditor qualification acceptance differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"auditor-q-{secrets.token_hex(8)}"
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

    idle_only_evidence = _probe_idle_only_admission(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        tenant_id=tenant_id,
        run_scope=qualification_run_id,
        observe_provider_state=observe_provider,
        observe_broker_state=observe_admission,
    )
    capacity_evidence = probe_agent_admission_broker_capacity(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path)),
        work=AgentWorkSpec(
            role=AgentRole.AUDITOR,
            purpose=AgentPurpose.KNOWLEDGE_AUDIT,
            route=ExecutionRoute.COMPLEX_ORCHESTRATION,
            scheduling_class=SchedulingClass.IDLE_ONLY,
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
    initialized: _InitializedKnowledge | None = None
    result: AuditorQualificationResult | None = None
    admission_evidence: dict[str, object] | None = None
    database_state: dict[str, bool] | None = None
    teardown: dict[str, bool] | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(prefix="yap-auditor-qualification-") as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            initialized = _initialize_auditor_knowledge(
                started.dsn,
                corpus,
                private_runtime_root / "okf",
                tenant_id=tenant_id,
            )

            restarted = _restart_database(database, started)
            started = restarted
            _verify_initialized_knowledge(restarted.dsn, initialized)
            dsn_path = private_runtime_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, restarted.dsn)
            runtime, auditor_admission = _build_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=dsn_path,
            )
            provider_before_workload = observe_provider()
            broker_before_workload = observe_admission()
            executor, controlled_evidence = _build_auditor_executor(
                runtime=runtime,
                admission=auditor_admission,
                dsn_path=dsn_path,
                profile=profile,
                initialized=initialized,
            )
            result = evaluate_auditor_qualification(
                executor=executor,
                corpus=initialized.bound,
                acceptance=acceptance,
            )
            if result.public_evidence.get("qualified") is not True:
                raise RuntimeError("Auditor qualification did not meet acceptance")
            controlled_evidence.require_complete(
                expected_synchronized_service_calls=(
                    acceptance.synchronized_invocation_count
                )
            )
            invocation_modes = {
                item.request_id: item.invocation.mode
                for item in result.observations
                if item.request_id is not None
            }
            admission_evidence = auditor_admission.require_exact_lifecycle(
                invocation_modes=invocation_modes
            )
            if (
                observe_provider() != provider_before_workload
                or observe_admission() != broker_before_workload
            ):
                raise RuntimeError(
                    "Auditor workload changed provider or broker identity"
                )

            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            database_state = _verify_auditor_database_state(
                result_restarted.dsn,
                initialized,
                result,
                acceptance=acceptance,
                profile=profile,
                provider_generation=_provider_generation(provider_before_workload),
            )
        teardown = database.stop(timeout_seconds=15)
        _require_exact_teardown(teardown)
        started = None
    except BaseException as error:
        if started is not None:
            try:
                database.contain_failed_run()
            except BaseException as containment_error:
                raise containment_error from error
        raise

    if (
        initialized is None
        or result is None
        or admission_evidence is None
        or database_state is None
        or teardown is None
    ):
        raise RuntimeError("Auditor qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic = dict(result.public_evidence)
    semantic["qualificationScope"] = "auditor-source-cited-review-findings"
    semantic["outcome"] = "auditor-source-cited-review-findings-qualified"
    semantic["acceptancePlanSha256"] = acceptance.plan_sha256
    semantic["corpusSha256"] = corpus.corpus_sha256
    semantic["qualificationTenantSha256"] = hashlib.sha256(
        tenant_id.encode("utf-8")
    ).hexdigest()
    semantic["qualificationRunSha256"] = hashlib.sha256(
        qualification_run_id.encode("utf-8")
    ).hexdigest()
    semantic["workload"] = {
        "route": "complex-orchestration",
        "schedulingClass": "idle-only",
        "candidateId": profile.candidate_id,
        "model": profile.expected_model,
        "modelRevision": profile.model_revision,
        "runtimeId": profile.runtime_id,
        "profileSha256": profile.profile_sha256,
        "candidateLockSha256": profile.candidate_lock_sha256,
        "maximumOutputTokens": _MAXIMUM_OUTPUT_TOKENS,
        "maximumInputTokens": _MAXIMUM_INPUT_TOKENS,
        "maximumModelLength": 8_192,
        "maximumSequences": profile.maximum_sequences,
        "maximumBatchedTokens": 8_192,
        "batchInvariant": profile.batch_invariant,
        "prefixCachingEnabled": False,
        "requestSeed": 0,
        **admission_evidence,
        **idle_only_evidence,
        "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
        "admissionBrokerBinarySha256": expected_broker_sha256,
        "brokerExpectedCapacityObserved": capacity_evidence["expectedCapacityObserved"],
        "brokerComplexProfileObserved": capacity_evidence["expectedRouteObserved"],
        "ninthOwnerQueued": capacity_evidence["overflowOwnerQueued"],
        "capacityProbeContained": capacity_evidence["contained"],
        "capacityProbeProviderIdentityUnchanged": capacity_evidence[
            "providerIdentityUnchanged"
        ],
        "capacityProbeBrokerIdentityUnchanged": capacity_evidence[
            "brokerIdentityUnchanged"
        ],
        "gpuMemoryUtilization": "0.70",
        "requestTimeModelLaunchAbsent": True,
        "requestTimeModelSwapAbsent": True,
    }
    semantic["knowledge"] = {
        "freshTenantStateObserved": True,
        "generationRestartReadBackObserved": True,
        "resultRestartReadBackObserved": True,
        **database_state,
        "runtimeLockSha256": database_lock.lock_sha256,
        "teardown": teardown,
    }
    receipt = bind_checked_candidate_evidence(semantic, candidate)
    write_new_private_json_evidence(
        private_evidence_destination,
        {
            "schemaVersion": 1,
            "privacyScope": "private-auditor-qualification",
            "tenantId": tenant_id,
            "qualificationRunId": qualification_run_id,
            "publicEvidence": receipt,
            "qualification": {
                "acceptancePlanSha256": acceptance.plan_sha256,
                "corpusSha256": corpus.corpus_sha256,
                "observations": _private_observations(result),
            },
        },
    )
    return receipt


def _probe_idle_only_admission(
    client: AgentAdmissionClient,
    *,
    tenant_id: str,
    run_scope: str,
    observe_provider_state: Callable[[], Mapping[str, object]],
    observe_broker_state: Callable[[], Mapping[str, object]],
) -> dict[str, object]:
    provider_before = dict(observe_provider_state())
    broker_before = dict(observe_broker_state())
    idle_work = AgentWorkSpec(
        role=AgentRole.AUDITOR,
        purpose=AgentPurpose.KNOWLEDGE_AUDIT,
        route=ExecutionRoute.COMPLEX_ORCHESTRATION,
        scheduling_class=SchedulingClass.IDLE_ONLY,
    )
    non_idle_work = AgentWorkSpec(
        role=AgentRole.COORDINATOR,
        purpose=AgentPurpose.CONVERSATION_COORDINATE,
        route=ExecutionRoute.COMPLEX_ORCHESTRATION,
        scheduling_class=SchedulingClass.BACKGROUND_LLM,
    )

    active_non_idle = client.new_ticket()
    blocked_by_active = client.new_ticket()
    anchor_idle = client.new_ticket()
    pending_non_idle = client.new_ticket()
    blocked_by_pending = client.new_ticket()
    tickets = (
        active_non_idle,
        blocked_by_active,
        anchor_idle,
        pending_non_idle,
        blocked_by_pending,
    )
    try:
        active = client.submit(
            active_non_idle,
            principal=_probe_principal(tenant_id, f"{run_scope}-active-owner"),
            work=non_idle_work,
            source_sha256=_probe_sha256(run_scope, "active-non-idle"),
            remaining_deadline_ms=60_000,
        )
        blocked_active = client.submit(
            blocked_by_active,
            principal=_probe_principal(tenant_id, f"{run_scope}-blocked-active"),
            work=idle_work,
            source_sha256=_probe_sha256(run_scope, "blocked-by-active"),
            remaining_deadline_ms=60_000,
        )
        if active.outcome != "admitted" or blocked_active.outcome != "queued":
            raise RuntimeError("Auditor idle-only active-work exclusion differs")
        _cancel_probe_ticket(client, blocked_by_active)
        if client.complete(active_non_idle).outcome != "completed":
            raise RuntimeError("Auditor active-work probe did not complete")

        anchor = client.submit(
            anchor_idle,
            principal=_probe_principal(tenant_id, f"{run_scope}-pending-owner"),
            work=idle_work,
            source_sha256=_probe_sha256(run_scope, "idle-anchor"),
            remaining_deadline_ms=60_000,
        )
        pending = client.submit(
            pending_non_idle,
            principal=_probe_principal(tenant_id, f"{run_scope}-pending-owner"),
            work=non_idle_work,
            source_sha256=_probe_sha256(run_scope, "pending-non-idle"),
            remaining_deadline_ms=60_000,
        )
        blocked_pending = client.submit(
            blocked_by_pending,
            principal=_probe_principal(tenant_id, f"{run_scope}-blocked-pending"),
            work=idle_work,
            source_sha256=_probe_sha256(run_scope, "blocked-by-pending"),
            remaining_deadline_ms=60_000,
        )
        if (
            anchor.outcome != "admitted"
            or pending.outcome != "queued"
            or blocked_pending.outcome != "queued"
        ):
            raise RuntimeError("Auditor idle-only pending-work exclusion differs")
        _cancel_probe_ticket(client, blocked_by_pending)
        _cancel_probe_ticket(client, pending_non_idle)
        if client.complete(anchor_idle).outcome != "completed":
            raise RuntimeError("Auditor pending-work probe did not complete")
    except BaseException:
        containment_error: BaseException | None = None
        for ticket in tickets:
            try:
                _contain_probe_ticket(client, ticket)
            except BaseException as ticket_error:
                containment_error = containment_error or ticket_error
        if containment_error is not None:
            raise RuntimeError(
                "Auditor idle-only probe was not contained"
            ) from containment_error
        raise

    terminal = tuple(client.status(ticket).outcome for ticket in tickets)
    if terminal != (
        "completed",
        "cancelled",
        "completed",
        "cancelled",
        "cancelled",
    ):
        raise RuntimeError("Auditor idle-only probe terminal state differs")
    if (
        dict(observe_provider_state()) != provider_before
        or dict(observe_broker_state()) != broker_before
    ):
        raise RuntimeError("Auditor idle-only probe changed process identity")
    return {
        "nonIdleActiveBlocksIdleOnlyObserved": True,
        "nonIdlePendingBlocksIdleOnlyObserved": True,
        "idleOnlyAdmissionResumesAfterNonIdleTerminal": True,
        "idleOnlyProbeContained": True,
        "idleOnlyProbeProviderIdentityUnchanged": True,
        "idleOnlyProbeBrokerIdentityUnchanged": True,
    }


def _probe_principal(tenant_id: str, subject_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=subject_id,
        client_id="auditor-qualification",
        scopes=frozenset(),
        roles=frozenset(),
    )


def _probe_sha256(run_scope: str, label: str) -> str:
    return hashlib.sha256(f"{run_scope}:{label}".encode("utf-8")).hexdigest()


def _cancel_probe_ticket(
    client: AgentAdmissionClient,
    ticket: AgentAdmissionTicket,
) -> None:
    cancelled = client.cancel(ticket)
    if cancelled.outcome == "cancellation-requested":
        cancelled = client.acknowledge_cancellation(ticket)
    if cancelled.outcome not in {"cancelled", "deadline-exceeded"}:
        raise RuntimeError("Auditor idle-only probe cancellation differs")


def _contain_probe_ticket(
    client: AgentAdmissionClient,
    ticket: AgentAdmissionTicket,
) -> None:
    current = client.status(ticket)
    if current.outcome in {"completed", "cancelled", "deadline-exceeded"}:
        return
    if current.outcome == "admitted":
        if client.complete(ticket).outcome != "completed":
            raise RuntimeError("Auditor probe admission was not contained")
        return
    _cancel_probe_ticket(client, ticket)


def _initialize_auditor_knowledge(
    dsn: str,
    corpus: AuditorQualificationCorpus,
    root: Path,
    *,
    tenant_id: str,
) -> _InitializedKnowledge:
    root.mkdir(mode=0o700)
    rendered = render_auditor_qualification_generations(
        corpus,
        tenant_id=tenant_id,
    )
    compiled: dict[str, CompiledKnowledgeGeneration] = {}
    for generation in rendered:
        bundle = root / generation.generation_id
        bundle.mkdir(mode=0o700)
        _write_rendered_generation(bundle, generation)
        compiled[generation.generation_id] = compile_okf_bundle(
            bundle,
            tenant_id=tenant_id,
            source_revision=generation.source_revision,
        )
    curator = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=_CURATOR_ID,
        client_id="auditor-qualification",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )
    order = tuple(item.generation_id for item in corpus.generations)
    if order != ("predecessor", "successor"):
        raise ValueError("Auditor qualification generation order differs")
    source_admission_sha256s: dict[str, str] = {}
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_auditor_result_audit_schema(connection)
        _assert_empty_auditor_state(connection, tenant_id=tenant_id)
        for generation_id in order:
            generation = compiled[generation_id]
            admission = admit_curated_knowledge_generation(
                connection,
                principal=curator,
                repository_revision=generation.source_revision,
                source_path=_SOURCE_PATH,
                generation=generation,
            )
            source_admission_sha256s[generation_id] = admission.admission_sha256
            stage_compiled_generation(
                connection,
                generation,
                source_admission_sha256=admission.admission_sha256,
            )
            embedding = (1.0,) + (0.0,) * 767
            store_generation_embeddings(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
                embedding_model_id="auditor-qualification",
                embedding_model_revision=corpus.corpus_sha256,
                embeddings={chunk.chunk_id: embedding for chunk in generation.chunks},
            )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
    bound = bind_auditor_compiled_corpus(
        corpus,
        rendered,
        compiled,
        source_admission_sha256s=source_admission_sha256s,
    )
    return _InitializedKnowledge(rendered, compiled, bound)


def _write_rendered_generation(
    root: Path,
    generation: AuditorQualificationRenderedGeneration,
) -> None:
    seen: set[Path] = set()
    for item in generation.files:
        relative = PurePosixPath(item.relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != item.relative_path
            or not isinstance(item.body, bytes)
            or not item.body
            or b"\r" in item.body
            or not item.body.endswith(b"\n")
        ):
            raise ValueError("Auditor rendered file is invalid")
        path = root.joinpath(*relative.parts)
        if path in seen:
            raise ValueError("Auditor rendered file is duplicated")
        seen.add(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(item.body)
            output.flush()
            os.fsync(output.fileno())


def _assert_empty_auditor_state(connection, *, tenant_id: str) -> None:
    tables = (
        "yap_knowledge_builds",
        "yap_knowledge_source_admissions",
        "yap_knowledge_active_builds",
        "yap_knowledge_activation_history",
        "yap_knowledge_proposals",
        "yap_knowledge_tool_audit",
        "yap_auditor_result_audit",
    )
    counts = tuple(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        for table in tables
    )
    if counts != ((0,),) * len(tables):
        raise RuntimeError("Auditor qualification tenant is not fresh")


def _restart_database(
    database: OwnedPostgresKnowledgeRuntime,
    started: StartedKnowledgeDatabase,
) -> StartedKnowledgeDatabase:
    restarted = database.restart(timeout_seconds=120)
    if (
        restarted.container_id != started.container_id
        or restarted.process_id == started.process_id
    ):
        raise RuntimeError("Auditor database restart identity differs")
    return restarted


def _verify_initialized_knowledge(
    dsn: str,
    initialized: _InitializedKnowledge,
) -> None:
    tenant_id = initialized.bound.tenant_id
    expected_concepts = _sorted_rows(
        (
            generation.generation_sha256,
            concept.concept_id,
            concept.source_path,
            concept.content_sha256,
            concept.permission_path_prefix,
            concept.body,
            list(concept.links),
        )
        for generation in initialized.compiled.values()
        for concept in generation.concepts
    )
    expected_chunks = _sorted_rows(
        (
            generation.generation_sha256,
            chunk.concept_id,
            chunk.chunk_id,
            chunk.permission_sha256,
            chunk.char_start,
            chunk.char_end,
            chunk.text,
            list(chunk.linked_concept_ids),
        )
        for generation in initialized.compiled.values()
        for chunk in generation.chunks
    )
    expected_permissions = _sorted_rows(
        (
            generation.generation_sha256,
            permission.path_prefix,
            permission.permission_sha256,
            permission_record(permission),
        )
        for generation in initialized.compiled.values()
        for permission in generation.permissions
    )
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        active = connection.execute(
            "SELECT generation_sha256 FROM yap_knowledge_active_builds "
            "WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall()
        concepts = connection.execute(
            """SELECT generation_sha256, concept_id, source_path,
                      content_sha256, permission_path_prefix, body, links
               FROM yap_knowledge_concepts WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        chunks = connection.execute(
            """SELECT generation_sha256, concept_id, chunk_id,
                      permission_sha256, char_start, char_end, body,
                      linked_concept_ids
               FROM yap_knowledge_chunks WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        permissions = connection.execute(
            """SELECT generation_sha256, path_prefix, permission_sha256,
                      policy
               FROM yap_knowledge_permissions WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
    successor = initialized.compiled["successor"].generation_sha256
    if (
        active != [(successor,)]
        or _sorted_rows(concepts) != expected_concepts
        or _sorted_rows(chunks) != expected_chunks
        or _sorted_rows(permissions) != expected_permissions
    ):
        raise RuntimeError("Auditor compiled knowledge restart readback differs")


def _build_runtime(
    *,
    admission_socket_path: Path,
    profile_path: Path,
    candidate_lock_path: Path,
    dsn_path: Path,
) -> tuple[AuditorRuntime, _ObservedAuditorAdmission]:
    admission = _ObservedAuditorAdmission(
        AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    )
    runtime = build_auditor_runtime(
        {
            AUDITOR_RUNTIME: "warm_gemma",
            AUDITOR_ADMISSION_SOCKET: str(admission_socket_path),
            AUDITOR_PROFILE: str(profile_path),
            AUDITOR_CANDIDATE_LOCK: str(candidate_lock_path),
            AUDITOR_KNOWLEDGE_DSN_FILE: str(dsn_path),
        },
        authenticated_team_mode=True,
        admission=admission,
    )
    if (
        runtime is None
        or runtime.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS
        or runtime.maximum_input_tokens != _MAXIMUM_INPUT_TOKENS
    ):
        raise RuntimeError("Auditor qualification runtime is unavailable")
    return runtime, admission


def _build_auditor_executor(
    *,
    runtime: AuditorRuntime,
    admission: _ObservedAuditorAdmission,
    dsn_path: Path,
    profile: AgentVllmServiceProfile,
    initialized: _InitializedKnowledge,
) -> tuple[
    Callable[[AuditorQualificationInvocation, threading.Event], AuditorJobView],
    _ControlledModeEvidence,
]:
    if not isinstance(runtime, AuditorRuntime) or not isinstance(
        initialized, _InitializedKnowledge
    ):
        raise TypeError("Auditor qualification knowledge is invalid")
    connection_factory = private_postgres_connection_factory(dsn_path)
    evidence_reader = PostgresAuditorEvidenceReader(connection_factory)
    auditor = PostgresAuditorResultAuditor(
        connection_factory,
        AuditorRuntimeAuditIdentity(
            candidate_id=profile.candidate_id,
            model=profile.expected_model,
            model_revision=profile.model_revision,
            runtime_id=profile.runtime_id,
            profile_sha256=profile.profile_sha256,
            candidate_lock_sha256=profile.candidate_lock_sha256,
        ),
    )
    controlled = _ControlledModeEvidence()

    def execute(
        invocation: AuditorQualificationInvocation,
        cancellation: threading.Event,
    ) -> AuditorJobView:
        if invocation.mode not in {
            "normal",
            "pre-cancelled",
            "client-cancelled",
            "deadline",
            "stale-generation",
            "invalid-output",
        }:
            raise ValueError("Auditor qualification mode differs")
        principal = AuthenticatedPrincipal(
            tenant_id=invocation.tenant_id,
            subject_id=invocation.owner_id,
            client_id="auditor-qualification",
            scopes=frozenset(),
            roles=frozenset(),
        )
        service = runtime.service
        if invocation.mode == "normal":
            controlled.record_synchronized_service_call()
        if invocation.mode not in {"normal", "pre-cancelled"}:
            selected_auditor = auditor
            if invocation.mode == "stale-generation":
                selected_auditor = _StaleGenerationAuditor(
                    auditor,
                    connection_factory,
                    tenant_id=invocation.tenant_id,
                    predecessor_sha256=initialized.bound.generation_sha256s[
                        "predecessor"
                    ],
                    successor_sha256=initialized.bound.generation_sha256s["successor"],
                    evidence=controlled,
                )
            service = AuditorService(
                admission=admission,
                evidence_reader=evidence_reader,
                model=_controlled_model(
                    invocation.mode,
                    client_cancellation=cancellation,
                    evidence=controlled,
                ),
                result_auditor=selected_auditor,
            )
        return service.audit(
            AuditorRequest(
                focus=invocation.focus,
                maximum_findings=invocation.maximum_findings,
                expected_generation_sha256=invocation.expected_generation_sha256,
            ),
            principal=principal,
            cancellation=cancellation,
        )

    return execute, controlled


def _controlled_model(
    mode: str,
    *,
    client_cancellation: threading.Event,
    evidence: _ControlledModeEvidence,
):
    if mode == "client-cancelled":
        return _ClientCancelledModel(client_cancellation, evidence)
    if mode == "deadline":
        return _DeadlineModel(evidence)
    if mode == "invalid-output":
        return _InvalidOutputModel(evidence)
    if mode == "stale-generation":
        return _StaleGenerationModel()
    raise ValueError("Auditor controlled mode differs")


class _ClientCancelledModel:
    def __init__(
        self,
        client_cancellation: threading.Event,
        evidence: _ControlledModeEvidence,
    ) -> None:
        self._client_cancellation = client_cancellation
        self._evidence = evidence

    def review(
        self,
        request: AuditorRequest,
        evidence: AuditorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AuditorDecision:
        del request, evidence
        self._client_cancellation.set()
        if not cancellation.wait(2.0):
            raise RuntimeError("Auditor client cancellation was not forwarded")
        self._evidence.client_cancelled_after_admission = True
        raise KnowledgeToolCancelled("Auditor qualification client cancellation")


class _DeadlineModel:
    def __init__(self, evidence: _ControlledModeEvidence) -> None:
        self._evidence = evidence

    def review(
        self,
        request: AuditorRequest,
        evidence: AuditorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AuditorDecision:
        del request, evidence
        if not cancellation.wait(AUDITOR_OPERATION_DEADLINE_SECONDS + 2.0):
            raise RuntimeError("Auditor operation deadline did not fire")
        self._evidence.deadline_after_admission = True
        raise KnowledgeToolCancelled("Auditor qualification operation deadline")


class _InvalidOutputModel:
    def __init__(self, evidence: _ControlledModeEvidence) -> None:
        self._evidence = evidence

    def review(
        self,
        request: AuditorRequest,
        evidence: AuditorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AuditorDecision:
        del request, evidence, cancellation
        self._evidence.invalid_output_after_admission = True
        raise ValueError("Auditor qualification invalid output")


class _StaleGenerationModel:
    def review(
        self,
        request: AuditorRequest,
        evidence: AuditorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AuditorDecision:
        del request
        if cancellation.is_set() or len(evidence.items) < 2:
            raise RuntimeError("Auditor stale-generation evidence is incomplete")
        return AuditorDecision("report", ((0, 1),))


class _StaleGenerationAuditor:
    def __init__(
        self,
        delegate: PostgresAuditorResultAuditor,
        connection_factory: PrivatePostgresConnectionFactory,
        *,
        tenant_id: str,
        predecessor_sha256: str,
        successor_sha256: str,
        evidence: _ControlledModeEvidence,
    ) -> None:
        self._delegate = delegate
        self._connection_factory = connection_factory
        self._tenant_id = tenant_id
        self._predecessor_sha256 = predecessor_sha256
        self._successor_sha256 = successor_sha256
        self._evidence = evidence
        self._armed = True

    def record(self, **values: object) -> None:
        if not self._armed or values.get("status") != "complete":
            self._delegate.record(**values)  # type: ignore[arg-type]
            return
        self._armed = False
        self._activate(self._predecessor_sha256)
        try:
            self._delegate.record(**values)  # type: ignore[arg-type]
        except (KnowledgeGenerationStale, AuditorEvidenceChanged, LookupError):
            self._evidence.stale_generation_reauthorization = True
            raise
        else:
            raise RuntimeError(
                "Auditor stale generation publication remained admissible"
            )
        finally:
            self._activate(self._successor_sha256)

    def _activate(self, generation_sha256: str) -> None:
        with self._connection_factory() as connection:
            activate_complete_generation(
                connection,
                tenant_id=self._tenant_id,
                generation_sha256=generation_sha256,
            )


def _verify_auditor_database_state(
    dsn: str,
    initialized: _InitializedKnowledge,
    result: AuditorQualificationResult,
    *,
    acceptance: AuditorQualificationAcceptance,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
) -> dict[str, bool]:
    corpus = initialized.bound.corpus
    tenant_id = initialized.bound.tenant_id
    predecessor = initialized.compiled["predecessor"]
    successor = initialized.compiled["successor"]
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
                      evidence_sha256, report_sha256, citation_sha256,
                      generation_sha256, source_admission_sha256,
                      permission_hash, authorization_hash, agent_role,
                      purpose, route, scheduling_class, provider_generation,
                      candidate_id, model, model_revision, runtime_id,
                      profile_sha256, candidate_lock_sha256, outcome, reason,
                      result_count, duration_milliseconds >= 0
               FROM yap_auditor_result_audit WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        tool_rows = connection.execute(
            """SELECT subject_id, agent_id, operation, outcome, result_count,
                      generation_sha256, permission_hash, authorization_hash,
                      duration_milliseconds >= 0
               FROM yap_knowledge_tool_audit
               WHERE tenant_id = %s AND agent_id = 'auditor'""",
            (tenant_id,),
        ).fetchall()
    expected_result_rows, expected_tool_rows = _expected_audit_rows(
        initialized,
        result,
        acceptance=acceptance,
        profile=profile,
        provider_generation=provider_generation,
        actual_result_rows=result_rows,
    )
    expected_builds = [
        (
            generation.generation_sha256,
            generation.source_revision,
            len(generation.concepts),
            len(generation.chunks),
            len(generation.relationships),
            len(generation.permissions),
            "auditor-qualification",
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
            (
                predecessor.generation_sha256,
                successor.generation_sha256,
                "publish",
            ),
            (
                successor.generation_sha256,
                predecessor.generation_sha256,
                "publish",
            ),
        ],
        "proposalWritesAbsent": proposals == (0,),
        "auditorResultAuditExact": _sorted_rows(result_rows)
        == _sorted_rows(expected_result_rows),
        "knowledgeToolAuditExact": _sorted_rows(tool_rows)
        == _sorted_rows(expected_tool_rows),
    }
    if not all(checks.values()):
        raise RuntimeError("Auditor durable state differs after qualification")
    return checks


def _expected_audit_rows(
    initialized: _InitializedKnowledge,
    result: AuditorQualificationResult,
    *,
    acceptance: AuditorQualificationAcceptance,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
    actual_result_rows: Sequence[Sequence[object]],
) -> tuple[
    list[tuple[object, ...]],
    list[tuple[object, ...]],
]:
    bound = initialized.bound
    invocations = build_auditor_qualification_invocations(
        bound.corpus,
        acceptance,
        tenant_id=bound.tenant_id,
        generation_sha256s=bound.generation_sha256s,
    )
    observations = {item.invocation.invocation_id: item for item in result.observations}
    if set(observations) != {item.invocation_id for item in invocations} or any(
        not item.exact_match for item in observations.values()
    ):
        raise RuntimeError("Auditor qualification observations differ")
    result_by_request_id: dict[str, tuple[object, ...]] = {}
    for row in actual_result_rows:
        item = tuple(row)
        request_id = item[1] if len(item) == 26 else None
        if (
            not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or request_id in result_by_request_id
        ):
            raise RuntimeError("Auditor durable request identity is invalid")
        result_by_request_id[request_id] = item

    result_rows: list[tuple[object, ...]] = []
    tool_rows: list[tuple[object, ...]] = []
    for invocation in invocations:
        observation = observations[invocation.invocation_id]
        request_id = observation.request_id
        if (
            not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or request_id not in result_by_request_id
        ):
            raise RuntimeError("Auditor request audit identity is invalid")
        request = AuditorRequest(
            focus=invocation.focus,
            maximum_findings=invocation.maximum_findings,
            expected_generation_sha256=invocation.expected_generation_sha256,
        )
        expected = bound.expected_views[invocation.expected_view_id]
        evidence = (
            None
            if invocation.mode == "pre-cancelled"
            else bound.evidence_by_case.get(invocation.case_id)
        )
        if evidence is None and expected.reason == "empty-result":
            evidence = _empty_auditor_evidence(
                tenant_id=bound.tenant_id,
                owner_id=invocation.owner_id,
                generation_sha256=invocation.expected_generation_sha256,
                source_admission_sha256=_source_admission_for_generation(
                    bound,
                    invocation.expected_generation_sha256,
                ),
            )
        elif evidence is None and invocation.mode != "pre-cancelled":
            raise RuntimeError("Auditor expected evidence binding is absent")
        if expected.status == "complete":
            outcome = "succeeded"
        elif expected.status == "evidence-unavailable":
            outcome = "unavailable"
        elif expected.status == "failed":
            outcome = "failed"
        elif expected.status == "cancelled":
            outcome = "cancelled"
        else:
            raise RuntimeError("Auditor expected terminal audit differs")
        report = expected.report
        result_count = len(report.findings) if report is not None else 0
        result_rows.append(
            (
                invocation.owner_id,
                request_id,
                auditor_request_sha256(request),
                (
                    auditor_work_sha256(request, evidence)
                    if evidence is not None
                    else None
                ),
                evidence.evidence_sha256 if evidence is not None else None,
                report.report_sha256 if report is not None else None,
                report.citation_sha256 if report is not None else None,
                evidence.generation_sha256 if evidence is not None else None,
                evidence.source_admission_sha256 if evidence is not None else None,
                evidence.permission_hash if evidence is not None else None,
                evidence.authorization_hash if evidence is not None else None,
                "auditor",
                "knowledge-audit",
                "complex-orchestration",
                "idle-only",
                provider_generation if evidence is not None else None,
                profile.candidate_id,
                profile.expected_model,
                profile.model_revision,
                profile.runtime_id,
                profile.profile_sha256,
                profile.candidate_lock_sha256,
                outcome,
                expected.reason,
                result_count,
                True,
            )
        )
        if invocation.mode == "pre-cancelled":
            continue
        assert evidence is not None
        tool_rows.append(
            (
                invocation.owner_id,
                "auditor",
                "search",
                "succeeded",
                len(evidence.items),
                evidence.generation_sha256,
                evidence.permission_hash,
                evidence.authorization_hash,
                True,
            )
        )
    if len(result_rows) != 29 or len(tool_rows) != 28:
        raise RuntimeError("Auditor audit cardinality differs")
    return result_rows, tool_rows


def _source_admission_for_generation(
    bound: AuditorBoundQualificationCorpus,
    generation_sha256: str,
) -> str:
    generation_id = next(
        (
            identity
            for identity, digest in bound.generation_sha256s.items()
            if digest == generation_sha256
        ),
        None,
    )
    if generation_id is None:
        raise RuntimeError("Auditor evidence generation is not compiler-bound")
    return bound.source_admission_sha256s[generation_id]


def _empty_auditor_evidence(
    *,
    tenant_id: str,
    owner_id: str,
    generation_sha256: str,
    source_admission_sha256: str,
) -> AuditorEvidencePack:
    permission_hash = _json_sha256(
        {
            "tenantId": tenant_id,
            "subjectId": owner_id,
            "purpose": "knowledge.read",
            "generationSha256": generation_sha256,
            "permissionSha256s": [],
            "visibleConceptIds": [],
        }
    )
    authorization_hash = _json_sha256(
        {
            "permissionHash": permission_hash,
            "requiredCapability": "knowledge.search.lexical",
        }
    )
    return AuditorEvidencePack.create(
        generation_sha256=generation_sha256,
        source_admission_sha256=source_admission_sha256,
        permission_hash=permission_hash,
        authorization_hash=authorization_hash,
        items=(),
        output_budget_exhausted=False,
    )


def _private_observations(
    result: AuditorQualificationResult,
) -> list[dict[str, object]]:
    return [
        {
            "invocationId": item.invocation.invocation_id,
            "caseId": item.invocation.case_id,
            "runId": item.invocation.run_id,
            "waveId": item.invocation.wave_id,
            "declaredPosition": item.invocation.declared_position,
            "ownerId": item.invocation.owner_id,
            "requestId": item.request_id,
            "durationMilliseconds": item.duration_milliseconds,
            "exactMatch": item.exact_match,
            "failureKind": item.failure_kind,
            "expectedStatus": item.expected.status,
            "observedStatus": (
                item.observed.status if item.observed is not None else None
            ),
        }
        for item in result.observations
    ]


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _provider_generation(value: Mapping[str, object]) -> int:
    generation = value.get("processGeneration")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise RuntimeError("Auditor provider generation is invalid")
    return generation


def _sorted_rows(rows) -> list[tuple[object, ...]]:
    return sorted((tuple(row) for row in rows), key=repr)


def _require_exact_deadline_contract(maximum_p95_milliseconds: int) -> None:
    if (
        AUDITOR_OPERATION_DEADLINE_SECONDS != 60.0
        or AUDITOR_TERMINAL_AUDIT_DEADLINE_SECONDS != 64.0
        or AUDITOR_WORKFLOW_DEADLINE_SECONDS != 66.0
        or MAXIMUM_AUDITOR_INPUT_TOKENS != _MAXIMUM_INPUT_TOKENS
        or maximum_p95_milliseconds != _MAXIMUM_P95_MILLISECONDS
    ):
        raise ValueError("Auditor qualification deadline contract differs")


def _require_full_complex_profile(
    maximum_sequences: int,
    batch_invariant: bool,
    launch_arguments: tuple[str, ...],
) -> None:
    arguments = {
        launch_arguments[index]: launch_arguments[index + 1]
        for index in range(len(launch_arguments) - 1)
        if launch_arguments[index].startswith("--")
        and not launch_arguments[index + 1].startswith("--")
    }
    if (
        maximum_sequences != _BROKER_ACTIVE_CAPACITY
        or batch_invariant is not True
        or arguments.get("--gpu-memory-utilization") != "0.70"
        or arguments.get("--max-model-len") != "8192"
        or arguments.get("--max-num-seqs") != "8"
        or arguments.get("--max-num-batched-tokens") != "8192"
        or "--no-enable-prefix-caching" not in launch_arguments
        or "--enable-prefix-caching" in launch_arguments
    ):
        raise ValueError("Auditor qualification requires the full complex profile")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "auditor-acceptance.json",
        server / "auditor-workload-fixtures.json",
        server / "agent-model-route-qualification.lock.json",
        server / "agent-reasoning-candidates.lock.json",
        server / "agent-service-profiles/rapid-automation.json",
        server / "agent-service-profiles/complex-orchestration.json",
        server / "runtime/knowledge/postgres-pgvector.lock.json",
        server / "pyproject.toml",
        server / "uv.lock",
        server / "orchestrator/Cargo.toml",
        server / "orchestrator/Cargo.lock",
        repository_root / "infra/yap-server-node/agent-vllm-server.sh",
        server / "tests/agents/test_auditor.py",
        server / "tests/agents/test_auditor_model.py",
        server / "tests/agents/test_auditor_postgres.py",
        server / "tests/agents/test_auditor_result_audit.py",
        server / "tests/agents/test_auditor_runtime.py",
        server / "tests/agents/test_auditor_service.py",
        server / "tests/evaluation/test_agent_admission_broker_observation.py",
        server / "tests/evaluation/test_agent_service_lifecycle_observation.py",
        server / "tests/evaluation/test_auditor_qualification.py",
        server / "tests/evaluation/test_auditor_qualification_gate.py",
        server / "tests/evaluation/test_checked_candidate.py",
        server / "tests/evaluation/test_owned_postgres_knowledge_runtime.py",
        server / "tests/evaluation/test_private_json_evidence.py",
        server / "tests/evaluation/test_provider_runtime_observations.py",
        server / "tests/infra/test_agent_vllm_server.py",
        server / "tests/pools/test_agent_vllm_service_profile.py",
    )
    first_party_sources = tuple(
        sorted(
            (
                *server.glob("src/yap_server/**/*.py"),
                *server.glob("orchestrator/src/**/*.rs"),
                *server.glob("orchestrator/tests/**/*.rs"),
            ),
            key=lambda path: path.as_posix(),
        )
    )
    paths = (*fixed, *first_party_sources)
    if len(set(paths)) != len(paths) or any(not path.is_file() for path in paths):
        raise ValueError("Auditor qualification candidate inputs are incomplete")
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
            "Auditor evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Auditor evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Auditor evidence destination must be new and outside the repository"
        )
    return requested


def _write_new_private_text(path: Path, value: str) -> None:
    if (
        path.exists()
        or path.is_symlink()
        or not value
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError("Auditor private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _require_exact_teardown(value: Mapping[str, bool]) -> None:
    if set(value) != _TEARDOWN_KEYS or not all(value.values()):
        raise RuntimeError("Auditor database teardown differs")


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Auditor qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Auditor on the already-warm full complex route",
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
    receipt = run_auditor_qualification_gate(
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
        if receipt["outcome"] == "auditor-source-cited-review-findings-qualified"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_auditor_qualification_gate"]
