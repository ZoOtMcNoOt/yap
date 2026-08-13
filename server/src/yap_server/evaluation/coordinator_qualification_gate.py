"""Run the exact checked Coordinator selection-only qualification."""

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
import time
from typing import Callable, Mapping, Sequence

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
from yap_server.agents.coordinator_model import (
    MAXIMUM_COORDINATOR_INPUT_TOKENS,
    CoordinatorDecision,
)
from yap_server.agents.coordinator_result_audit import (
    CoordinatorRuntimeAuditIdentity,
    PostgresCoordinatorResultAuditor,
    install_coordinator_result_audit_schema,
)
from yap_server.agents.coordinator_runtime import (
    COORDINATOR_ADMISSION_SOCKET,
    COORDINATOR_CANDIDATE_LOCK,
    COORDINATOR_KNOWLEDGE_DSN_FILE,
    COORDINATOR_PROFILE,
    COORDINATOR_RUNTIME,
    CoordinatorRuntime,
    build_coordinator_runtime,
    load_coordinator_service_profile,
)
from yap_server.agents.coordinator_service import (
    COORDINATOR_OPERATION_DEADLINE_SECONDS,
    COORDINATOR_TERMINAL_AUDIT_DEADLINE_SECONDS,
    COORDINATOR_WORKFLOW_DEADLINE_SECONDS,
    CoordinatorJobView,
    CoordinatorService,
)
from yap_server.agents.curator import curator_request_sha256, curator_work_sha256
from yap_server.agents.curator_publisher import PostgresCuratorPublisher
from yap_server.agents.curator_result_audit import (
    CuratorRuntimeAuditIdentity,
    PostgresCuratorResultAuditor,
    install_curator_result_audit_schema,
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
from yap_server.evaluation.private_json_evidence import write_new_private_json_evidence
from yap_server.knowledge.generation_ledger import (
    activate_complete_generation,
    install_knowledge_schema,
    stage_compiled_generation,
    store_generation_embeddings,
)
from yap_server.knowledge.knowledge_proposals import PostgresCoordinatorEvidenceReader
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

from .coordinator_qualification import (
    CoordinatorBoundQualificationCorpus,
    CoordinatorCompiledQualificationCorpus,
    CoordinatorQualificationAcceptance,
    CoordinatorQualificationCorpus,
    CoordinatorQualificationInvocation,
    CoordinatorQualificationRenderedGeneration,
    CoordinatorQualificationResult,
    bind_coordinator_compiled_corpus,
    bind_coordinator_curator_lineage,
    build_coordinator_qualification_invocations,
    evaluate_coordinator_qualification,
    load_coordinator_qualification_acceptance,
    load_coordinator_qualification_corpus,
    render_coordinator_qualification_generations,
)


_BROKER_ACTIVE_CAPACITY = 8
_MAXIMUM_OUTPUT_TOKENS = 512
_MAXIMUM_INPUT_TOKENS = 7_680
_MAXIMUM_P95_MILLISECONDS = 85_000
_SOURCE_PATH = "server/coordinator-workload-fixtures.json"
_CURATOR_ID = "coordinator-qualification-curator"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]
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
    rendered: tuple[CoordinatorQualificationRenderedGeneration, ...]
    compiled: dict[str, CompiledKnowledgeGeneration]
    corpus: CoordinatorCompiledQualificationCorpus


@dataclass(slots=True)
class _ControlledModeEvidence:
    client_cancelled_after_service_call: bool = False
    deadline_after_service_call: bool = False
    invalid_output_after_service_call: bool = False
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
                self.client_cancelled_after_service_call,
                self.deadline_after_service_call,
                self.invalid_output_after_service_call,
                self.stale_generation_reauthorization,
                self.synchronized_service_calls == expected_synchronized_service_calls,
            )
        ):
            raise RuntimeError("Coordinator controlled-mode evidence is incomplete")


def run_coordinator_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Coordinator on the already-warm full complex route."""

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
    acceptance = load_coordinator_qualification_acceptance(
        root / "server/coordinator-acceptance.json"
    )
    corpus = load_coordinator_qualification_corpus(
        root / "server/coordinator-workload-fixtures.json"
    )
    _require_exact_deadline_contract(acceptance.maximum_normal_p95_milliseconds)
    profile_path = root / "server/agent-service-profiles/complex-orchestration.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_coordinator_service_profile(profile_path, candidate_lock_path)
    _require_full_complex_profile(
        profile.maximum_sequences,
        profile.batch_invariant,
        profile.launch_arguments,
    )
    if (
        profile.maximum_sequences != _BROKER_ACTIVE_CAPACITY
        or acceptance.owner_count != _BROKER_ACTIVE_CAPACITY
        or acceptance.owners_per_synchronized_wave != _BROKER_ACTIVE_CAPACITY
    ):
        raise ValueError("Coordinator qualification capacity contract differs")

    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"coordinator-q-{secrets.token_hex(8)}"
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
    initialized: _InitializedKnowledge | None = None
    bound: CoordinatorBoundQualificationCorpus | None = None
    result: CoordinatorQualificationResult | None = None
    database_state: dict[str, bool] | None = None
    teardown: dict[str, bool] | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(
            prefix="yap-coordinator-qualification-"
        ) as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            initialized = _initialize_coordinator_knowledge(
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
            provider_before_workload = observe_provider()
            broker_before_workload = observe_admission()
            provider_generation = _provider_generation(provider_before_workload)
            curator_request_ids = _publish_curator_proposals(
                dsn_path,
                initialized.corpus,
                profile=profile,
                provider_generation=provider_generation,
                qualification_run_id=qualification_run_id,
            )
            bound = bind_coordinator_curator_lineage(
                initialized.corpus,
                curator_request_ids,
            )
            runtime = _build_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=dsn_path,
            )
            executor, controlled = _build_coordinator_executor(
                runtime=runtime,
                admission_socket_path=admission_socket_path,
                dsn_path=dsn_path,
                profile=profile,
                bound=bound,
            )
            result = evaluate_coordinator_qualification(
                executor=executor,
                corpus=bound,
                acceptance=acceptance,
            )
            if result.public_evidence.get("qualified") is not True:
                raise RuntimeError("Coordinator qualification did not meet acceptance")
            controlled.require_complete(
                expected_synchronized_service_calls=(
                    acceptance.synchronized_invocation_count
                )
            )
            if (
                observe_provider() != provider_before_workload
                or observe_admission() != broker_before_workload
            ):
                raise RuntimeError(
                    "Coordinator workload changed provider or broker identity"
                )

            before_restart = _persistence_snapshot(restarted.dsn, tenant_id=tenant_id)
            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            after_restart = _persistence_snapshot(
                result_restarted.dsn,
                tenant_id=tenant_id,
            )
            if after_restart != before_restart:
                raise RuntimeError("Coordinator persistence changed across restart")
            database_state = _verify_coordinator_database_state(
                result_restarted.dsn,
                initialized,
                bound,
                result,
                acceptance=acceptance,
                profile=profile,
                provider_generation=provider_generation,
                curator_request_ids=curator_request_ids,
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
        or bound is None
        or result is None
        or database_state is None
        or teardown is None
    ):
        raise RuntimeError("Coordinator qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic: dict[str, object] = dict(result.public_evidence)
    semantic["qualificationScope"] = "coordinator-proposal-bundle-selection"
    semantic["outcome"] = "coordinator-proposal-bundle-selection-qualified"
    semantic["acceptancePlanSha256"] = acceptance.plan_sha256
    semantic["corpusSha256"] = corpus.corpus_sha256
    semantic["qualificationTenantSha256"] = hashlib.sha256(
        tenant_id.encode("utf-8")
    ).hexdigest()
    semantic["qualificationRunSha256"] = hashlib.sha256(
        qualification_run_id.encode("utf-8")
    ).hexdigest()
    semantic["workload"] = _workload_receipt(
        profile,
        capacity_evidence=capacity_evidence,
        broker_sha256=expected_broker_sha256,
        synchronized_service_calls=controlled.synchronized_service_calls,
    )
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
            "privacyScope": "private-coordinator-qualification",
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


def _initialize_coordinator_knowledge(
    dsn: str,
    corpus: CoordinatorQualificationCorpus,
    root: Path,
    *,
    tenant_id: str,
) -> _InitializedKnowledge:
    root.mkdir(mode=0o700)
    rendered = render_coordinator_qualification_generations(
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
    bound = bind_coordinator_compiled_corpus(corpus, rendered, compiled)
    curator = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=_CURATOR_ID,
        client_id="coordinator-qualification",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )
    order = tuple(item.generation_id for item in corpus.generations)
    if order != ("predecessor", "successor"):
        raise ValueError("Coordinator qualification generation order differs")
    with _connect_database(dsn) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_curator_result_audit_schema(connection)
        install_coordinator_result_audit_schema(connection)
        _assert_empty_coordinator_state(connection, tenant_id=tenant_id)
        for generation_id in order:
            generation = compiled[generation_id]
            admission = admit_curated_knowledge_generation(
                connection,
                principal=curator,
                repository_revision=generation.source_revision,
                source_path=_SOURCE_PATH,
                generation=generation,
            )
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
                embedding_model_id="coordinator-qualification",
                embedding_model_revision=corpus.corpus_sha256,
                embeddings={chunk.chunk_id: embedding for chunk in generation.chunks},
            )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
    return _InitializedKnowledge(rendered, compiled, bound)


def _verify_initialized_knowledge(
    dsn: str,
    initialized: _InitializedKnowledge,
) -> None:
    tenant_id = initialized.corpus.tenant_id
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
    with _connect_database(dsn) as connection:
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
            """SELECT generation_sha256, path_prefix, permission_sha256, policy
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
        raise RuntimeError("Coordinator compiled knowledge restart readback differs")


def _publish_curator_proposals(
    dsn_path: Path,
    corpus: CoordinatorCompiledQualificationCorpus,
    *,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
    qualification_run_id: str,
) -> dict[str, str]:
    connection_factory = private_postgres_connection_factory(dsn_path)
    auditor = PostgresCuratorResultAuditor(
        connection_factory,
        CuratorRuntimeAuditIdentity(
            candidate_id=profile.candidate_id,
            model=profile.expected_model,
            model_revision=profile.model_revision,
            runtime_id=profile.runtime_id,
            profile_sha256=profile.profile_sha256,
            candidate_lock_sha256=profile.candidate_lock_sha256,
        ),
    )
    publisher = PostgresCuratorPublisher(connection_factory, auditor)
    request_ids: dict[str, str] = {}
    for index, proposal in enumerate(corpus.corpus.proposals, start=1):
        seed = corpus.proposal_seeds_by_key[proposal.proposal_key]
        request_id = f"{qualification_run_id}-curator-{index}"
        started = time.monotonic()
        published = publisher.publish(
            principal=_owner_principal(corpus.tenant_id, seed.owner_id),
            request_id=request_id,
            request=seed.request,
            evidence=seed.evidence,
            provider_generation=provider_generation,
            started=started,
            deadline=started + 30.0,
            cancellation=threading.Event(),
        )
        if (
            published.proposal_id != seed.proposal_id
            or published.generation_sha256 != seed.evidence.generation_sha256
            or published.permission_hash != seed.proposal_permission_hash
            or published.authorization_hash != seed.proposal_authorization_hash
            or published.status != "proposed"
        ):
            raise RuntimeError("Coordinator Curator publication differs")
        request_ids[proposal.proposal_key] = request_id
    if set(request_ids) != set(corpus.proposal_seeds_by_key):
        raise RuntimeError("Coordinator Curator publication is incomplete")
    return request_ids


def _build_runtime(
    *,
    admission_socket_path: Path,
    profile_path: Path,
    candidate_lock_path: Path,
    dsn_path: Path,
) -> CoordinatorRuntime:
    runtime = build_coordinator_runtime(
        {
            COORDINATOR_RUNTIME: "warm_gemma",
            COORDINATOR_ADMISSION_SOCKET: str(admission_socket_path),
            COORDINATOR_PROFILE: str(profile_path),
            COORDINATOR_CANDIDATE_LOCK: str(candidate_lock_path),
            COORDINATOR_KNOWLEDGE_DSN_FILE: str(dsn_path),
        },
        authenticated_team_mode=True,
    )
    if (
        runtime is None
        or runtime.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS
        or runtime.maximum_input_tokens != _MAXIMUM_INPUT_TOKENS
    ):
        raise RuntimeError("Coordinator qualification runtime is unavailable")
    return runtime


def _build_coordinator_executor(
    *,
    runtime: CoordinatorRuntime,
    admission_socket_path: Path,
    dsn_path: Path,
    profile: AgentVllmServiceProfile,
    bound: CoordinatorBoundQualificationCorpus,
) -> tuple[
    Callable[[CoordinatorQualificationInvocation, threading.Event], CoordinatorJobView],
    _ControlledModeEvidence,
]:
    if not isinstance(runtime, CoordinatorRuntime) or not isinstance(
        bound, CoordinatorBoundQualificationCorpus
    ):
        raise TypeError("Coordinator qualification corpus is invalid")
    connection_factory = private_postgres_connection_factory(dsn_path)
    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    evidence_reader = PostgresCoordinatorEvidenceReader(connection_factory)
    auditor = PostgresCoordinatorResultAuditor(
        connection_factory,
        CoordinatorRuntimeAuditIdentity(
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
        invocation: CoordinatorQualificationInvocation,
        cancellation: threading.Event,
    ) -> CoordinatorJobView:
        if invocation.mode not in {
            "normal",
            "pre-cancelled",
            "client-cancelled",
            "deadline",
            "stale-generation",
            "invalid-output",
        }:
            raise ValueError("Coordinator qualification mode differs")
        principal = _owner_principal(invocation.tenant_id, invocation.owner_id)
        service = runtime.service
        if invocation.mode not in {"normal", "pre-cancelled"}:
            selected_reader = evidence_reader
            if invocation.mode == "stale-generation":
                selected_reader = _StaleGenerationReader(
                    evidence_reader,
                    connection_factory,
                    tenant_id=invocation.tenant_id,
                    predecessor_sha256=bound.generation_sha256s["predecessor"],
                    successor_sha256=bound.generation_sha256s["successor"],
                    evidence=controlled,
                )
            service = CoordinatorService(
                admission=admission,
                evidence_reader=selected_reader,
                model=_controlled_model(
                    invocation.mode,
                    client_cancellation=cancellation,
                    evidence=controlled,
                ),
                result_auditor=auditor,
            )
        view = service.coordinate(
            CoordinatorRequest(
                objective=invocation.objective,
                maximum_items=invocation.maximum_items,
                expected_generation_sha256=invocation.expected_generation_sha256,
            ),
            principal=principal,
            cancellation=cancellation,
        )
        if invocation.mode == "normal":
            controlled.record_synchronized_service_call()
        return view

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
        return _UnexpectedModel()
    raise ValueError("Coordinator controlled mode differs")


class _ClientCancelledModel:
    def __init__(
        self,
        client_cancellation: threading.Event,
        evidence: _ControlledModeEvidence,
    ) -> None:
        self._client_cancellation = client_cancellation
        self._evidence = evidence

    def select(
        self,
        request: CoordinatorRequest,
        evidence: CoordinatorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> CoordinatorDecision:
        del request, evidence
        self._client_cancellation.set()
        if not cancellation.wait(2.0):
            raise RuntimeError("Coordinator client cancellation was not forwarded")
        self._evidence.client_cancelled_after_service_call = True
        raise KnowledgeToolCancelled("Coordinator qualification client cancellation")


class _DeadlineModel:
    def __init__(self, evidence: _ControlledModeEvidence) -> None:
        self._evidence = evidence

    def select(
        self,
        request: CoordinatorRequest,
        evidence: CoordinatorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> CoordinatorDecision:
        del request, evidence
        if not cancellation.wait(COORDINATOR_OPERATION_DEADLINE_SECONDS + 2.0):
            raise RuntimeError("Coordinator operation deadline did not fire")
        self._evidence.deadline_after_service_call = True
        raise KnowledgeToolCancelled("Coordinator qualification operation deadline")


class _InvalidOutputModel:
    def __init__(self, evidence: _ControlledModeEvidence) -> None:
        self._evidence = evidence

    def select(
        self,
        request: CoordinatorRequest,
        evidence: CoordinatorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> CoordinatorDecision:
        del request, evidence, cancellation
        self._evidence.invalid_output_after_service_call = True
        raise ValueError("Coordinator qualification invalid output")


class _UnexpectedModel:
    def select(
        self,
        request: CoordinatorRequest,
        evidence: CoordinatorEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> CoordinatorDecision:
        del request, evidence, cancellation
        raise RuntimeError("Coordinator stale-generation case reached the model")


class _StaleGenerationReader:
    def __init__(
        self,
        delegate: PostgresCoordinatorEvidenceReader,
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

    def read(
        self,
        request: CoordinatorRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> CoordinatorEvidencePack:
        self._activate(self._predecessor_sha256)
        try:
            self._delegate.read(
                request,
                principal=principal,
                cancellation=cancellation,
            )
        except KnowledgeGenerationStale:
            self._evidence.stale_generation_reauthorization = True
            raise
        else:
            raise RuntimeError("Coordinator stale generation remained admissible")
        finally:
            self._activate(self._successor_sha256)

    def _activate(self, generation_sha256: str) -> None:
        with self._connection_factory() as connection:
            activate_complete_generation(
                connection,
                tenant_id=self._tenant_id,
                generation_sha256=generation_sha256,
            )


def _verify_coordinator_database_state(
    dsn: str,
    initialized: _InitializedKnowledge,
    bound: CoordinatorBoundQualificationCorpus,
    result: CoordinatorQualificationResult,
    *,
    acceptance: CoordinatorQualificationAcceptance,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
    curator_request_ids: Mapping[str, str],
) -> dict[str, bool]:
    tenant_id = bound.tenant_id
    predecessor = initialized.compiled["predecessor"]
    successor = initialized.compiled["successor"]
    with _connect_database(dsn) as connection:
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
        proposals = _proposal_rows(connection, tenant_id=tenant_id)
        curator_audits = _curator_result_rows(connection, tenant_id=tenant_id)
        coordinator_audits = _coordinator_result_rows(
            connection,
            tenant_id=tenant_id,
        )
        tool_audits = _tool_audit_rows(connection, tenant_id=tenant_id)

    expected_proposals = _expected_proposal_rows(bound)
    expected_curator = _expected_curator_rows(
        bound,
        profile=profile,
        provider_generation=provider_generation,
        curator_request_ids=curator_request_ids,
    )
    expected_coordinator, expected_tools = _expected_coordinator_rows(
        bound,
        result,
        acceptance=acceptance,
        profile=profile,
        provider_generation=provider_generation,
    )
    expected_builds = [
        (
            generation.generation_sha256,
            generation.source_revision,
            len(generation.concepts),
            len(generation.chunks),
            len(generation.relationships),
            len(generation.permissions),
            "coordinator-qualification",
            bound.corpus.corpus_sha256,
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
    expected_tool_rows = [
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
        *expected_tools,
    ]
    checks = {
        "successorGenerationActive": active == [(successor.generation_sha256,)],
        "twoGenerationsRetainedExact": _sorted_rows(builds)
        == _sorted_rows(expected_builds),
        "twoSourceAdmissionsRetainedExact": _sorted_rows(admissions)
        == _sorted_rows(expected_admissions),
        "staleControlActivationHistoryExact": activations
        == [
            (predecessor.generation_sha256, None, "publish"),
            (successor.generation_sha256, predecessor.generation_sha256, "publish"),
            (predecessor.generation_sha256, successor.generation_sha256, "publish"),
            (successor.generation_sha256, predecessor.generation_sha256, "publish"),
        ],
        "curatorProposalRowsExact": _sorted_rows(proposals)
        == _sorted_rows(expected_proposals),
        "curatorResultAuditExact": _sorted_rows(curator_audits)
        == _sorted_rows(expected_curator),
        "coordinatorResultAuditExact": _sorted_rows(coordinator_audits)
        == _sorted_rows(expected_coordinator),
        "knowledgeToolAuditExact": _sorted_rows(tool_audits)
        == _sorted_rows(expected_tool_rows),
        "auditCardinalityExact": (
            len(proposals) == 8
            and len(curator_audits) == 8
            and len(coordinator_audits) == 29
            and len(tool_audits) == 36
        ),
    }
    if not all(checks.values()):
        raise RuntimeError("Coordinator durable state differs after qualification")
    return checks


def _expected_proposal_rows(
    bound: CoordinatorBoundQualificationCorpus,
) -> list[tuple[object, ...]]:
    rows = []
    proposal_types = {
        proposal.proposal_key: proposal.proposal_type
        for proposal in bound.corpus.proposals
    }
    for key, seed in bound.proposal_seeds_by_key.items():
        rows.append(
            (
                seed.owner_id,
                seed.proposal_id,
                seed.evidence.generation_sha256,
                "curator",
                proposal_types[key],
                seed.request.reviewed_content,
                [
                    item.model_dump(mode="json")
                    for item in seed.request.source_citations
                ],
                seed.inherited_permission_sha256,
                "proposed",
            )
        )
    return rows


def _expected_curator_rows(
    bound: CoordinatorBoundQualificationCorpus,
    *,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
    curator_request_ids: Mapping[str, str],
) -> list[tuple[object, ...]]:
    return [
        (
            seed.owner_id,
            curator_request_ids[key],
            seed.request.submission_id,
            curator_request_sha256(seed.request),
            curator_work_sha256(seed.request, seed.evidence),
            "knowledge-propose",
            "complex-orchestration",
            "background-llm",
            provider_generation,
            profile.candidate_id,
            profile.expected_model,
            profile.model_revision,
            profile.runtime_id,
            profile.profile_sha256,
            profile.candidate_lock_sha256,
            seed.evidence.generation_sha256,
            seed.evidence.evidence_sha256,
            seed.evidence.permission_hash,
            seed.evidence.authorization_hash,
            seed.proposal_permission_hash,
            seed.proposal_authorization_hash,
            seed.proposal_id,
            "succeeded",
            None,
            1,
            True,
        )
        for key, seed in bound.proposal_seeds_by_key.items()
    ]


def _expected_coordinator_rows(
    bound: CoordinatorBoundQualificationCorpus,
    result: CoordinatorQualificationResult,
    *,
    acceptance: CoordinatorQualificationAcceptance,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    invocations = build_coordinator_qualification_invocations(
        bound.corpus,
        acceptance,
        tenant_id=bound.tenant_id,
        generation_sha256s=bound.generation_sha256s,
    )
    observations = {item.invocation.invocation_id: item for item in result.observations}
    if set(observations) != {item.invocation_id for item in invocations} or any(
        not item.exact_match for item in observations.values()
    ):
        raise RuntimeError("Coordinator qualification observations differ")
    rows: list[tuple[object, ...]] = []
    tools: list[tuple[object, ...]] = []
    for invocation in invocations:
        observation = observations[invocation.invocation_id]
        request_id = _required_request_id(observation.request_id)
        request = CoordinatorRequest(
            objective=invocation.objective,
            maximum_items=invocation.maximum_items,
            expected_generation_sha256=invocation.expected_generation_sha256,
        )
        evidence = (
            None
            if invocation.mode in {"pre-cancelled", "stale-generation"}
            else bound.evidence_by_case[invocation.case_id]
        )
        expected = bound.expected_views[invocation.expected_view_id]
        outcome = {
            "complete": "succeeded",
            "evidence-unavailable": "unavailable",
            "failed": "failed",
            "cancelled": "cancelled",
        }[expected.status]
        rows.append(
            (
                invocation.owner_id,
                request_id,
                coordinator_request_sha256(request),
                coordinator_work_sha256(request, evidence) if evidence else None,
                evidence.evidence_sha256 if evidence else None,
                expected.bundle.bundle_sha256 if expected.bundle else None,
                expected.bundle.citation_sha256 if expected.bundle else None,
                evidence.generation_sha256 if evidence else None,
                evidence.permission_hash if evidence else None,
                evidence.authorization_hash if evidence else None,
                "coordinator",
                "conversation-coordinate",
                "complex-orchestration",
                "background-llm",
                None if invocation.mode == "pre-cancelled" else provider_generation,
                profile.candidate_id,
                profile.expected_model,
                profile.model_revision,
                profile.runtime_id,
                profile.profile_sha256,
                profile.candidate_lock_sha256,
                outcome,
                expected.reason,
                len(expected.bundle.items) if expected.bundle else 0,
                True,
            )
        )
        if invocation.mode == "pre-cancelled":
            continue
        tool_evidence = bound.evidence_by_case[invocation.case_id]
        stale = invocation.mode == "stale-generation"
        tools.append(
            (
                invocation.owner_id,
                "coordinator",
                "open-proposal-evidence",
                "failed" if stale else "succeeded",
                0 if stale else len(tool_evidence.candidates),
                None if stale else tool_evidence.generation_sha256,
                None if stale else tool_evidence.permission_hash,
                None if stale else tool_evidence.authorization_hash,
                True,
            )
        )
    if len(rows) != 29 or len(tools) != 28:
        raise RuntimeError("Coordinator audit cardinality differs")
    return rows, tools


def _persistence_snapshot(
    dsn: str,
    *,
    tenant_id: str,
) -> tuple[tuple[tuple[object, ...], ...], ...]:
    with _connect_database(dsn) as connection:
        return (
            tuple(_proposal_rows(connection, tenant_id=tenant_id)),
            tuple(_curator_result_rows(connection, tenant_id=tenant_id)),
            tuple(_coordinator_result_rows(connection, tenant_id=tenant_id)),
            tuple(_tool_audit_rows(connection, tenant_id=tenant_id)),
            tuple(
                connection.execute(
                    """SELECT generation_sha256, previous_generation_sha256, reason
                       FROM yap_knowledge_activation_history
                       WHERE tenant_id = %s ORDER BY activation_id""",
                    (tenant_id,),
                ).fetchall()
            ),
        )


def _proposal_rows(connection, *, tenant_id: str) -> list[tuple[object, ...]]:
    return connection.execute(
        """SELECT proposer_subject_id, proposal_id, generation_sha256,
                  proposer_agent_id, proposal_type, proposed_content,
                  source_citations, inherited_permission_sha256, status
           FROM yap_knowledge_proposals
           WHERE tenant_id = %s ORDER BY proposer_subject_id, proposal_id""",
        (tenant_id,),
    ).fetchall()


def _curator_result_rows(connection, *, tenant_id: str) -> list[tuple[object, ...]]:
    return connection.execute(
        """SELECT subject_id, request_id, submission_id, request_sha256,
                  work_sha256, purpose, route, scheduling_class,
                  provider_generation, candidate_id, model, model_revision,
                  runtime_id, profile_sha256, candidate_lock_sha256,
                  generation_sha256, evidence_sha256, permission_hash,
                  authorization_hash, proposal_permission_hash,
                  proposal_authorization_hash, proposal_id, outcome, reason,
                  result_count, duration_milliseconds >= 0
           FROM yap_curator_result_audit
           WHERE tenant_id = %s ORDER BY subject_id, submission_id""",
        (tenant_id,),
    ).fetchall()


def _coordinator_result_rows(
    connection,
    *,
    tenant_id: str,
) -> list[tuple[object, ...]]:
    return connection.execute(
        """SELECT subject_id, request_id, request_sha256, work_sha256,
                  evidence_sha256, bundle_sha256, citation_sha256,
                  generation_sha256, permission_hash, authorization_hash,
                  agent_role, purpose, route, scheduling_class,
                  provider_generation, candidate_id, model, model_revision,
                  runtime_id, profile_sha256, candidate_lock_sha256,
                  outcome, reason, result_count, duration_milliseconds >= 0
           FROM yap_coordinator_result_audit
           WHERE tenant_id = %s ORDER BY subject_id, request_id""",
        (tenant_id,),
    ).fetchall()


def _tool_audit_rows(connection, *, tenant_id: str) -> list[tuple[object, ...]]:
    return connection.execute(
        """SELECT subject_id, agent_id, operation, outcome, result_count,
                  generation_sha256, permission_hash, authorization_hash,
                  duration_milliseconds >= 0
           FROM yap_knowledge_tool_audit
           WHERE tenant_id = %s AND agent_id IN ('curator', 'coordinator')
           ORDER BY agent_id, subject_id, audit_id""",
        (tenant_id,),
    ).fetchall()


def _workload_receipt(
    profile: AgentVllmServiceProfile,
    *,
    capacity_evidence: Mapping[str, object],
    broker_sha256: str,
    synchronized_service_calls: int,
) -> dict[str, object]:
    return {
        "route": "complex-orchestration",
        "schedulingClass": "background-llm",
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
        "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
        "admissionBrokerBinarySha256": broker_sha256,
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
        "synchronizedCoordinatorServiceCallCount": synchronized_service_calls,
        "synchronizedCoordinatorServiceCallsObserved": synchronized_service_calls == 24,
        "gpuMemoryUtilization": "0.70",
        "requestTimeModelLaunchAbsent": True,
        "requestTimeModelSwapAbsent": True,
    }


def _private_observations(
    result: CoordinatorQualificationResult,
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


def _owner_principal(tenant_id: str, owner_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=owner_id,
        client_id="coordinator-qualification",
        scopes=frozenset({"knowledge.read", "knowledge.propose"}),
    )


def _connect_database(dsn: str):
    return psycopg.connect(
        dsn,
        connect_timeout=3,
        options="-c statement_timeout=3000 -c lock_timeout=3000",
    )


def _provider_generation(value: Mapping[str, object]) -> int:
    generation = value.get("processGeneration")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise RuntimeError("Coordinator provider generation is invalid")
    return generation


def _required_request_id(value: object) -> str:
    if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
        raise RuntimeError("Coordinator request audit identity is invalid")
    return value


def _sorted_rows(rows) -> list[tuple[object, ...]]:
    return sorted((tuple(row) for row in rows), key=repr)


def _assert_empty_coordinator_state(connection, *, tenant_id: str) -> None:
    queries = (
        "SELECT count(*) FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_builds WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_active_builds WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_proposals WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_tool_audit WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_curator_result_audit WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_coordinator_result_audit WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_activation_history WHERE tenant_id = %s",
    )
    counts = tuple(
        connection.execute(query, (tenant_id,)).fetchone() for query in queries
    )
    if any(row != (0,) for row in counts):
        raise RuntimeError("Coordinator qualification tenant is not fresh")


def _restart_database(
    database: OwnedPostgresKnowledgeRuntime,
    current: StartedKnowledgeDatabase,
) -> StartedKnowledgeDatabase:
    restarted = database.restart(timeout_seconds=120)
    if (
        restarted.container_id != current.container_id
        or restarted.process_id == current.process_id
    ):
        raise RuntimeError("Coordinator database restart identity differs")
    return restarted


def _write_rendered_generation(root: Path, generation) -> None:
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
            raise ValueError("Coordinator rendered file is invalid")
        path = root.joinpath(*relative.parts)
        if path in seen:
            raise ValueError("Coordinator rendered file is duplicated")
        seen.add(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(item.body)
            output.flush()
            os.fsync(output.fileno())


def _require_exact_deadline_contract(maximum_p95_milliseconds: int) -> None:
    if (
        COORDINATOR_OPERATION_DEADLINE_SECONDS != 60.0
        or COORDINATOR_TERMINAL_AUDIT_DEADLINE_SECONDS != 64.0
        or COORDINATOR_WORKFLOW_DEADLINE_SECONDS != 66.0
        or MAXIMUM_COORDINATOR_INPUT_TOKENS != _MAXIMUM_INPUT_TOKENS
        or maximum_p95_milliseconds != 85_000
    ):
        raise ValueError("Coordinator qualification deadline contract differs")


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
        raise ValueError("Coordinator qualification requires the full complex profile")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "coordinator-acceptance.json",
        server / "coordinator-workload-fixtures.json",
        server / "agent-reasoning-candidates.lock.json",
        server / "agent-service-profiles/complex-orchestration.json",
        server / "agent-service-profiles/rapid-automation.json",
        server / "runtime/knowledge/postgres-pgvector.lock.json",
        server / "pyproject.toml",
        server / "uv.lock",
        server / "src/yap_server/private_artifact.py",
        server / "src/yap_server/private_postgres_connection.py",
        server / "src/yap_server/auth/principal.py",
        server / "src/yap_server/agents/admission_client.py",
        server / "src/yap_server/agents/admission_protocol.py",
        server / "src/yap_server/agents/coordinator.py",
        server / "src/yap_server/agents/coordinator_model.py",
        server / "src/yap_server/agents/coordinator_result_audit.py",
        server / "src/yap_server/agents/coordinator_runtime.py",
        server / "src/yap_server/agents/coordinator_service.py",
        server / "src/yap_server/agents/curator.py",
        server / "src/yap_server/agents/curator_publisher.py",
        server / "src/yap_server/agents/curator_result_audit.py",
        server / "src/yap_server/agents/librarian.py",
        server / "src/yap_server/agents/student.py",
        server / "src/yap_server/agents/student_model.py",
        server / "src/yap_server/evaluation/agent_admission_broker_observation.py",
        server / "src/yap_server/evaluation/agent_service_lifecycle_observation.py",
        server / "src/yap_server/evaluation/checked_candidate.py",
        server / "src/yap_server/evaluation/coordinator_qualification.py",
        server / "src/yap_server/evaluation/coordinator_qualification_gate.py",
        server / "src/yap_server/evaluation/librarian_qualification.py",
        server / "src/yap_server/evaluation/owned_postgres_knowledge_runtime.py",
        server / "src/yap_server/evaluation/private_json_evidence.py",
        server / "src/yap_server/evaluation/provider_runtime_observations.py",
        server / "src/yap_server/knowledge/agent_reasoning_routes.py",
        server / "src/yap_server/knowledge/cancellable_database_operation.py",
        server / "src/yap_server/knowledge/generation_ledger.py",
        server / "src/yap_server/knowledge/governed_answer_protocol.py",
        server / "src/yap_server/knowledge/governed_knowledge_tools.py",
        server / "src/yap_server/knowledge/knowledge_agent_authority.py",
        server / "src/yap_server/knowledge/knowledge_proposals.py",
        server / "src/yap_server/knowledge/knowledge_source_admission.py",
        server / "src/yap_server/knowledge/knowledge_tool_audit.py",
        server / "src/yap_server/knowledge/knowledge_tool_contract.py",
        server / "src/yap_server/knowledge/okf_compiler.py",
        server / "src/yap_server/knowledge/okf_profile.py",
        server / "src/yap_server/knowledge/okf_projection.py",
        server / "src/yap_server/knowledge/okf_source.py",
        server / "src/yap_server/knowledge/permission_policy.py",
        server / "src/yap_server/knowledge/postgres_knowledge_retrieval.py",
        server / "src/yap_server/knowledge/postgres_permission_view.py",
        server / "src/yap_server/knowledge/postgres_relationship_retrieval.py",
        server / "src/yap_server/knowledge/vllm_reasoning_client.py",
        server / "src/yap_server/pools/agent_vllm_launch_contract.py",
        server / "src/yap_server/pools/agent_vllm_service_profile.py",
        server / "src/yap_server/pools/agent_vllm_service_profile_cli.py",
        server / "src/yap_server/pools/numeric_loopback_endpoint.py",
        server / "tests/agents/test_agent_admission_client.py",
        server / "tests/agents/test_coordinator.py",
        server / "tests/agents/test_coordinator_postgres.py",
        server / "tests/agents/test_coordinator_result_audit.py",
        server / "tests/agents/test_coordinator_runtime.py",
        server / "tests/agents/test_coordinator_service.py",
        server / "tests/agents/test_curator.py",
        server / "tests/agents/test_curator_postgres.py",
        server / "tests/agents/test_librarian.py",
        server / "tests/evaluation/test_agent_admission_broker_observation.py",
        server / "tests/evaluation/test_agent_service_lifecycle_observation.py",
        server / "tests/evaluation/test_checked_candidate.py",
        server / "tests/evaluation/test_coordinator_qualification.py",
        server / "tests/evaluation/test_coordinator_qualification_gate.py",
        server / "tests/evaluation/test_librarian_qualification.py",
        server / "tests/evaluation/test_owned_postgres_knowledge_runtime.py",
        server / "tests/evaluation/test_private_json_evidence.py",
        server / "tests/evaluation/test_provider_runtime_observations.py",
        server / "tests/infra/test_agent_vllm_server.py",
        server / "tests/knowledge/test_agent_reasoning_routes.py",
        server / "tests/knowledge/test_cancellable_database_operation.py",
        server / "tests/knowledge/test_knowledge_proposals.py",
        server / "tests/knowledge/test_okf_compiler.py",
        server / "tests/knowledge/test_postgres_generation_ledger.py",
        server / "tests/knowledge/test_postgres_permission_safe_retrieval.py",
        server / "tests/knowledge/test_vllm_reasoning_client.py",
        server / "tests/pools/test_agent_vllm_service_profile.py",
        server / "orchestrator/Cargo.toml",
        server / "orchestrator/Cargo.lock",
        server / "orchestrator/src/lib.rs",
        server / "orchestrator/src/service_profile.rs",
        server / "orchestrator/tests/supervised_service.rs",
        server / "orchestrator/tests/support/mod.rs",
        repository_root / "infra/yap-server-node/agent-vllm-server.sh",
    )
    broker_sources = tuple(
        sorted(
            (
                *server.glob("orchestrator/src/agent_admission*.rs"),
                *server.glob("orchestrator/src/agent_admission/**/*.rs"),
                *server.glob("orchestrator/src/bin/yap-agent-admission-broker.rs"),
                *server.glob("orchestrator/tests/agent_admission*.rs"),
            ),
            key=lambda path: path.as_posix(),
        )
    )
    paths = (*fixed, *broker_sources)
    if len(set(paths)) != len(paths) or any(not path.is_file() for path in paths):
        raise ValueError("Coordinator qualification candidate inputs are incomplete")
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
            "Coordinator evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Coordinator evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Coordinator evidence destination must be new and outside the repository"
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
        raise ValueError("Coordinator private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _require_exact_teardown(value: Mapping[str, bool]) -> None:
    if set(value) != _TEARDOWN_KEYS or not all(value.values()):
        raise RuntimeError("Coordinator database teardown differs")


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Coordinator qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Coordinator on the already-warm full complex route",
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
    receipt = run_coordinator_qualification_gate(
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
        if receipt["outcome"] == "coordinator-proposal-bundle-selection-qualified"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_coordinator_qualification_gate"]
