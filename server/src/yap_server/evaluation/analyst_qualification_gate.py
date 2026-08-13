"""Run the exact checked Analyst grounded cited-answer qualification."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
    UnixAgentAdmissionTransport,
)
from yap_server.agents.analyst import (
    AnalystEvidenceChanged,
    AnalystRequest,
    PostgresAnalystEvidenceVerifier,
    analyst_request_sha256,
    analyst_work_sha256,
)
from yap_server.agents.analyst_model import (
    MAXIMUM_ANALYST_INPUT_TOKENS,
    AnalystDecision,
)
from yap_server.agents.analyst_result_audit import (
    AnalystRuntimeAuditIdentity,
    PostgresAnalystResultAuditor,
    install_analyst_result_audit_schema,
)
from yap_server.agents.analyst_runtime import (
    ANALYST_ADMISSION_SOCKET,
    ANALYST_CANDIDATE_LOCK,
    ANALYST_KNOWLEDGE_DSN_FILE,
    ANALYST_PROFILE,
    ANALYST_RUNTIME,
    AnalystRuntime,
    build_analyst_runtime,
    load_analyst_service_profile,
)
from yap_server.agents.analyst_service import (
    ANALYST_OPERATION_DEADLINE_SECONDS,
    ANALYST_TERMINAL_AUDIT_DEADLINE_SECONDS,
    ANALYST_WORKFLOW_DEADLINE_SECONDS,
    AnalystJobView,
    AnalystService,
)
from yap_server.agents.librarian import (
    LibrarianEvidencePack,
    LibrarianRequest,
    PostgresLibrarianEvidenceReader,
    librarian_request_sha256,
    librarian_work_sha256,
)
from yap_server.agents.librarian_result_audit import (
    PostgresLibrarianResultAuditor,
    install_librarian_result_audit_schema,
)
from yap_server.agents.librarian_service import LibrarianService
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

from .analyst_qualification import (
    AnalystBoundQualificationCorpus,
    AnalystQualificationCorpus,
    AnalystQualificationInvocation,
    AnalystQualificationRenderedGeneration,
    AnalystQualificationResult,
    bind_analyst_compiled_corpus,
    build_analyst_qualification_invocations,
    evaluate_analyst_qualification,
    load_analyst_qualification_acceptance,
    load_analyst_qualification_corpus,
    render_analyst_qualification_generations,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_CURATOR_ID = "analyst-qualification-curator"
_SOURCE_PATH = "server/analyst-workload-fixtures.json"
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
    rendered: tuple[AnalystQualificationRenderedGeneration, ...]
    compiled: dict[str, CompiledKnowledgeGeneration]
    bound: AnalystBoundQualificationCorpus


@dataclass(slots=True)
class _ControlledModeEvidence:
    client_cancelled_after_admission: bool = False
    deadline_after_admission: bool = False
    invalid_output_after_admission: bool = False
    stale_generation_reauthorization: bool = False

    def require_complete(self) -> None:
        if not all(
            (
                self.client_cancelled_after_admission,
                self.deadline_after_admission,
                self.invalid_output_after_admission,
                self.stale_generation_reauthorization,
            )
        ):
            raise RuntimeError("Analyst controlled-mode evidence is incomplete")


def run_analyst_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Analyst on the already-warm full complex route."""

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
    acceptance = load_analyst_qualification_acceptance(
        root / "server/analyst-acceptance.json"
    )
    corpus = load_analyst_qualification_corpus(
        root / "server/analyst-workload-fixtures.json"
    )
    _require_exact_deadline_contract(acceptance.maximum_p95_milliseconds)

    profile_path = root / "server/agent-service-profiles/complex-orchestration.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_analyst_service_profile(profile_path, candidate_lock_path)
    _require_full_complex_profile(profile.maximum_sequences, profile.launch_arguments)
    if (
        acceptance.maximum_p95_milliseconds != _MAXIMUM_P95_MILLISECONDS
        or profile.maximum_sequences != _BROKER_ACTIVE_CAPACITY
    ):
        raise ValueError("Analyst qualification acceptance differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"analyst-q-{secrets.token_hex(8)}"
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
            role=AgentRole.ANALYST,
            purpose=AgentPurpose.KNOWLEDGE_ANSWER,
            route=ExecutionRoute.COMPLEX_ORCHESTRATION,
            scheduling_class=SchedulingClass.INTERACTIVE,
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
    result: AnalystQualificationResult | None = None
    database_state: dict[str, bool] | None = None
    teardown: dict[str, bool] | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(prefix="yap-analyst-qualification-") as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            initialized = _initialize_analyst_knowledge(
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
            runtime = _build_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=dsn_path,
            )
            provider_before_workload = observe_provider()
            broker_before_workload = observe_admission()
            executor, controlled_evidence = _build_analyst_executor(
                runtime=runtime,
                admission_socket_path=admission_socket_path,
                dsn_path=dsn_path,
                profile=profile,
                initialized=initialized,
            )
            result = evaluate_analyst_qualification(
                executor=executor,
                corpus=initialized.bound,
                acceptance=acceptance,
            )
            if result.public_evidence.get("qualified") is not True:
                raise RuntimeError("Analyst qualification did not meet acceptance")
            controlled_evidence.require_complete()
            if (
                observe_provider() != provider_before_workload
                or observe_admission() != broker_before_workload
            ):
                raise RuntimeError(
                    "Analyst workload changed provider or broker identity"
                )

            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            database_state = _verify_analyst_database_state(
                result_restarted.dsn,
                initialized,
                result,
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
        or database_state is None
        or teardown is None
    ):
        raise RuntimeError("Analyst qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic = dict(result.public_evidence)
    semantic["qualificationScope"] = "analyst-grounded-cited-answers"
    semantic["outcome"] = "analyst-grounded-cited-answers-qualified"
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
        "schedulingClass": "interactive",
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
            "privacyScope": "private-analyst-qualification",
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


def _initialize_analyst_knowledge(
    dsn: str,
    corpus: AnalystQualificationCorpus,
    root: Path,
    *,
    tenant_id: str,
) -> _InitializedKnowledge:
    root.mkdir(mode=0o700)
    rendered = render_analyst_qualification_generations(
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
    bound = bind_analyst_compiled_corpus(corpus, rendered, compiled)

    curator = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=_CURATOR_ID,
        client_id="analyst-qualification",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )
    order = tuple(item.generation_id for item in corpus.generations)
    if order != ("predecessor", "successor"):
        raise ValueError("Analyst qualification generation order differs")
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_librarian_result_audit_schema(connection)
        install_analyst_result_audit_schema(connection)
        _assert_empty_analyst_state(connection, tenant_id=tenant_id)
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
                embedding_model_id="analyst-qualification",
                embedding_model_revision=corpus.corpus_sha256,
                embeddings={chunk.chunk_id: embedding for chunk in generation.chunks},
            )
            activate_complete_generation(
                connection,
                tenant_id=tenant_id,
                generation_sha256=generation.generation_sha256,
            )
    return _InitializedKnowledge(rendered, compiled, bound)


def _write_rendered_generation(
    root: Path,
    generation: AnalystQualificationRenderedGeneration,
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
            raise ValueError("Analyst rendered file is invalid")
        path = root.joinpath(*relative.parts)
        if path in seen:
            raise ValueError("Analyst rendered file is duplicated")
        seen.add(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(item.body)
            output.flush()
            os.fsync(output.fileno())


def _assert_empty_analyst_state(connection, *, tenant_id: str) -> None:
    tables = (
        "yap_knowledge_builds",
        "yap_knowledge_source_admissions",
        "yap_knowledge_active_builds",
        "yap_knowledge_activation_history",
        "yap_knowledge_proposals",
        "yap_knowledge_tool_audit",
        "yap_librarian_result_audit",
        "yap_analyst_result_audit",
    )
    counts = tuple(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        for table in tables
    )
    if counts != ((0,),) * len(tables):
        raise RuntimeError("Analyst qualification tenant is not fresh")


def _restart_database(
    database: OwnedPostgresKnowledgeRuntime,
    started: StartedKnowledgeDatabase,
) -> StartedKnowledgeDatabase:
    restarted = database.restart(timeout_seconds=120)
    if (
        restarted.container_id != started.container_id
        or restarted.process_id == started.process_id
    ):
        raise RuntimeError("Analyst database restart identity differs")
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
        raise RuntimeError("Analyst compiled knowledge restart readback differs")


def _build_runtime(
    *,
    admission_socket_path: Path,
    profile_path: Path,
    candidate_lock_path: Path,
    dsn_path: Path,
) -> AnalystRuntime:
    runtime = build_analyst_runtime(
        {
            ANALYST_RUNTIME: "warm_gemma",
            ANALYST_ADMISSION_SOCKET: str(admission_socket_path),
            ANALYST_PROFILE: str(profile_path),
            ANALYST_CANDIDATE_LOCK: str(candidate_lock_path),
            ANALYST_KNOWLEDGE_DSN_FILE: str(dsn_path),
        },
        authenticated_team_mode=True,
    )
    if (
        runtime is None
        or runtime.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS
        or runtime.maximum_input_tokens != _MAXIMUM_INPUT_TOKENS
    ):
        raise RuntimeError("Analyst qualification runtime is unavailable")
    return runtime


def _build_analyst_executor(
    *,
    runtime: AnalystRuntime,
    admission_socket_path: Path,
    dsn_path: Path,
    profile: AgentVllmServiceProfile,
    initialized: _InitializedKnowledge,
) -> tuple[
    Callable[[AnalystQualificationInvocation, threading.Event], AnalystJobView],
    _ControlledModeEvidence,
]:
    if not isinstance(runtime, AnalystRuntime) or not isinstance(
        initialized, _InitializedKnowledge
    ):
        raise TypeError("Analyst qualification knowledge is invalid")
    connection_factory = private_postgres_connection_factory(dsn_path)
    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(admission_socket_path))
    librarian = LibrarianService(
        admission=admission,
        evidence_reader=PostgresLibrarianEvidenceReader(connection_factory),
        result_auditor=PostgresLibrarianResultAuditor(connection_factory),
    )
    verifier = PostgresAnalystEvidenceVerifier(connection_factory)
    auditor = PostgresAnalystResultAuditor(
        connection_factory,
        AnalystRuntimeAuditIdentity(
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
        invocation: AnalystQualificationInvocation,
        cancellation: threading.Event,
    ) -> AnalystJobView:
        if invocation.mode not in {
            "normal",
            "pre-cancelled",
            "client-cancelled",
            "deadline",
            "stale-generation",
            "invalid-output",
        }:
            raise ValueError("Analyst qualification mode differs")
        principal = AuthenticatedPrincipal(
            tenant_id=invocation.tenant_id,
            subject_id=invocation.owner_id,
            client_id="analyst-qualification",
            scopes=frozenset(),
            roles=frozenset(),
        )
        service = runtime.service
        if invocation.mode not in {"normal", "pre-cancelled"}:
            selected_verifier = verifier
            if invocation.mode == "stale-generation":
                selected_verifier = _StaleGenerationVerifier(
                    verifier,
                    connection_factory,
                    tenant_id=invocation.tenant_id,
                    predecessor_sha256=initialized.bound.generation_sha256s[
                        "predecessor"
                    ],
                    successor_sha256=initialized.bound.generation_sha256s["successor"],
                    evidence=controlled,
                )
            service = AnalystService(
                admission=admission,
                librarian=librarian,
                evidence_verifier=selected_verifier,
                model=_controlled_model(
                    invocation.mode,
                    client_cancellation=cancellation,
                    evidence=controlled,
                ),
                result_auditor=auditor,
            )
        return service.answer(
            AnalystRequest(
                question=invocation.question,
                maximum_results=invocation.maximum_results,
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
        return _UnexpectedModel()
    raise ValueError("Analyst controlled mode differs")


class _ClientCancelledModel:
    def __init__(
        self,
        client_cancellation: threading.Event,
        evidence: _ControlledModeEvidence,
    ) -> None:
        self._client_cancellation = client_cancellation
        self._evidence = evidence

    def answer(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AnalystDecision:
        del request, evidence
        self._client_cancellation.set()
        if not cancellation.wait(2.0):
            raise RuntimeError("Analyst client cancellation was not forwarded")
        self._evidence.client_cancelled_after_admission = True
        raise KnowledgeToolCancelled("Analyst qualification client cancellation")


class _DeadlineModel:
    def __init__(self, evidence: _ControlledModeEvidence) -> None:
        self._evidence = evidence

    def answer(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AnalystDecision:
        del request, evidence
        if not cancellation.wait(ANALYST_OPERATION_DEADLINE_SECONDS + 2.0):
            raise RuntimeError("Analyst operation deadline did not fire")
        self._evidence.deadline_after_admission = True
        raise KnowledgeToolCancelled("Analyst qualification operation deadline")


class _InvalidOutputModel:
    def __init__(self, evidence: _ControlledModeEvidence) -> None:
        self._evidence = evidence

    def answer(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AnalystDecision:
        del request, evidence, cancellation
        self._evidence.invalid_output_after_admission = True
        raise ValueError("Analyst qualification invalid output")


class _UnexpectedModel:
    def answer(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        cancellation: threading.Event,
    ) -> AnalystDecision:
        del request, evidence, cancellation
        raise RuntimeError("Analyst stale-generation case reached the model")


class _StaleGenerationVerifier:
    def __init__(
        self,
        delegate: PostgresAnalystEvidenceVerifier,
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

    def verify(
        self,
        request: AnalystRequest,
        evidence: LibrarianEvidencePack,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> None:
        self._activate(self._predecessor_sha256)
        try:
            self._delegate.verify(
                request,
                evidence,
                principal=principal,
                cancellation=cancellation,
            )
        except (KnowledgeGenerationStale, AnalystEvidenceChanged):
            self._evidence.stale_generation_reauthorization = True
            raise
        else:
            raise RuntimeError("Analyst stale generation remained admissible")
        finally:
            self._activate(self._successor_sha256)

    def _activate(self, generation_sha256: str) -> None:
        with self._connection_factory() as connection:
            activate_complete_generation(
                connection,
                tenant_id=self._tenant_id,
                generation_sha256=generation_sha256,
            )


def _verify_analyst_database_state(
    dsn: str,
    initialized: _InitializedKnowledge,
    result: AnalystQualificationResult,
    *,
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
            """SELECT subject_id, request_id, librarian_request_id,
                      request_sha256, work_sha256, evidence_sha256,
                      answer_sha256, citation_sha256, generation_sha256,
                      permission_hash, authorization_hash, agent_role,
                      purpose, route, scheduling_class, provider_generation,
                      candidate_id, model, model_revision, runtime_id,
                      profile_sha256, candidate_lock_sha256, outcome, reason,
                      result_count, duration_milliseconds >= 0
               FROM yap_analyst_result_audit WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        librarian_rows = connection.execute(
            """SELECT subject_id, request_id, request_sha256, work_sha256,
                      evidence_sha256, generation_sha256, permission_hash,
                      authorization_hash, agent_role, purpose, route,
                      scheduling_class, outcome, reason, result_count,
                      duration_milliseconds >= 0
               FROM yap_librarian_result_audit WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        tool_rows = connection.execute(
            """SELECT subject_id, agent_id, operation, outcome, result_count,
                      generation_sha256, permission_hash, authorization_hash,
                      duration_milliseconds >= 0
               FROM yap_knowledge_tool_audit
               WHERE tenant_id = %s AND agent_id = 'librarian'""",
            (tenant_id,),
        ).fetchall()
    expected_result_rows, expected_librarian_rows, expected_tool_rows = (
        _expected_audit_rows(
            initialized,
            result,
            profile=profile,
            provider_generation=provider_generation,
            actual_result_rows=result_rows,
        )
    )
    expected_builds = [
        (
            generation.generation_sha256,
            generation.source_revision,
            len(generation.concepts),
            len(generation.chunks),
            len(generation.relationships),
            len(generation.permissions),
            "analyst-qualification",
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
        "analystResultAuditExact": _sorted_rows(result_rows)
        == _sorted_rows(expected_result_rows),
        "librarianResultAuditExact": _sorted_rows(librarian_rows)
        == _sorted_rows(expected_librarian_rows),
        "knowledgeToolAuditExact": _sorted_rows(tool_rows)
        == _sorted_rows(expected_tool_rows),
    }
    if not all(checks.values()):
        raise RuntimeError("Analyst durable state differs after qualification")
    return checks


def _expected_audit_rows(
    initialized: _InitializedKnowledge,
    result: AnalystQualificationResult,
    *,
    profile: AgentVllmServiceProfile,
    provider_generation: int,
    actual_result_rows: Sequence[Sequence[object]],
) -> tuple[
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    list[tuple[object, ...]],
]:
    bound = initialized.bound
    invocations = build_analyst_qualification_invocations(
        bound.corpus,
        tenant_id=bound.tenant_id,
        generation_sha256s=bound.generation_sha256s,
    )
    observations = {item.invocation.invocation_id: item for item in result.observations}
    if set(observations) != {item.invocation_id for item in invocations} or any(
        not item.exact_match for item in observations.values()
    ):
        raise RuntimeError("Analyst qualification observations differ")
    result_by_request_id: dict[str, tuple[object, ...]] = {}
    for row in actual_result_rows:
        item = tuple(row)
        request_id = item[1] if len(item) == 26 else None
        if (
            not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or request_id in result_by_request_id
        ):
            raise RuntimeError("Analyst durable request identity is invalid")
        result_by_request_id[request_id] = item

    result_rows: list[tuple[object, ...]] = []
    librarian_rows: list[tuple[object, ...]] = []
    tool_rows: list[tuple[object, ...]] = []
    for invocation in invocations:
        observation = observations[invocation.invocation_id]
        request_id = observation.request_id
        if (
            not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or request_id not in result_by_request_id
        ):
            raise RuntimeError("Analyst request audit identity is invalid")
        request = AnalystRequest(
            question=invocation.question,
            maximum_results=invocation.maximum_results,
            expected_generation_sha256=invocation.expected_generation_sha256,
        )
        expected = bound.expected_views[invocation.invocation_id]
        analyst_pack = (
            None
            if invocation.mode == "pre-cancelled"
            else bound.evidence_by_case.get(invocation.case_id)
        )
        librarian_pack = analyst_pack
        if analyst_pack is None and expected.reason == "empty-result":
            librarian_pack = _empty_librarian_evidence(
                tenant_id=bound.tenant_id,
                owner_id=invocation.owner_id,
                generation_sha256=invocation.expected_generation_sha256,
            )
        elif analyst_pack is None and invocation.mode != "pre-cancelled":
            raise RuntimeError("Analyst expected evidence binding is absent")
        actual = result_by_request_id[request_id]
        librarian_request_id = actual[2]
        if invocation.mode == "pre-cancelled":
            if librarian_request_id is not None:
                raise RuntimeError("Pre-cancelled Analyst reached Librarian")
        elif (
            not isinstance(librarian_request_id, str)
            or _REQUEST_ID.fullmatch(librarian_request_id) is None
        ):
            raise RuntimeError("Analyst Librarian audit identity is invalid")
        if expected.status == "complete":
            outcome = "succeeded"
        elif expected.status == "evidence-unavailable":
            outcome = "unavailable"
        elif expected.status == "failed":
            outcome = "failed"
        elif expected.status == "cancelled":
            outcome = "cancelled"
        else:
            raise RuntimeError("Analyst expected terminal audit differs")
        answer = expected.answer
        result_count = 1 if expected.status == "complete" else 0
        result_rows.append(
            (
                invocation.owner_id,
                request_id,
                librarian_request_id,
                analyst_request_sha256(request),
                (
                    analyst_work_sha256(request, analyst_pack)
                    if analyst_pack is not None
                    else None
                ),
                analyst_pack.evidence_sha256 if analyst_pack is not None else None,
                answer.answer_sha256 if answer is not None else None,
                answer.citation_sha256 if answer is not None else None,
                analyst_pack.generation_sha256 if analyst_pack is not None else None,
                analyst_pack.permission_hash if analyst_pack is not None else None,
                analyst_pack.authorization_hash if analyst_pack is not None else None,
                "analyst",
                "knowledge-answer",
                "complex-orchestration",
                "interactive",
                provider_generation if analyst_pack is not None else None,
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
        assert librarian_pack is not None
        assert isinstance(librarian_request_id, str)
        librarian_request = LibrarianRequest(
            search_text=invocation.question,
            maximum_results=invocation.maximum_results,
            expected_generation_sha256=invocation.expected_generation_sha256,
        )
        librarian_rows.append(
            (
                invocation.owner_id,
                librarian_request_id,
                librarian_request_sha256(librarian_request),
                librarian_work_sha256(librarian_request, librarian_pack),
                librarian_pack.evidence_sha256,
                librarian_pack.generation_sha256,
                librarian_pack.permission_hash,
                librarian_pack.authorization_hash,
                "librarian",
                "knowledge-read",
                "server-io",
                "interactive",
                "unavailable" if expected.reason == "empty-result" else "succeeded",
                "empty-result" if expected.reason == "empty-result" else None,
                len(librarian_pack.items),
                True,
            )
        )
        tool_rows.append(
            (
                invocation.owner_id,
                "librarian",
                "search",
                "succeeded",
                len(librarian_pack.items),
                librarian_pack.generation_sha256,
                librarian_pack.permission_hash,
                librarian_pack.authorization_hash,
                True,
            )
        )
    if len(result_rows) != 13 or len(librarian_rows) != 12 or len(tool_rows) != 12:
        raise RuntimeError("Analyst audit cardinality differs")
    return result_rows, librarian_rows, tool_rows


def _empty_librarian_evidence(
    *,
    tenant_id: str,
    owner_id: str,
    generation_sha256: str,
) -> LibrarianEvidencePack:
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
    return LibrarianEvidencePack.create(
        generation_sha256=generation_sha256,
        permission_hash=permission_hash,
        authorization_hash=authorization_hash,
        items=(),
        output_budget_exhausted=False,
    )


def _private_observations(
    result: AnalystQualificationResult,
) -> list[dict[str, object]]:
    return [
        {
            "invocationId": item.invocation.invocation_id,
            "caseId": item.invocation.case_id,
            "runId": item.invocation.run_id,
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
        raise RuntimeError("Analyst provider generation is invalid")
    return generation


def _sorted_rows(rows) -> list[tuple[object, ...]]:
    return sorted((tuple(row) for row in rows), key=repr)


def _require_exact_deadline_contract(maximum_p95_milliseconds: int) -> None:
    if (
        ANALYST_OPERATION_DEADLINE_SECONDS != 80.0
        or ANALYST_TERMINAL_AUDIT_DEADLINE_SECONDS != 84.0
        or ANALYST_WORKFLOW_DEADLINE_SECONDS != 86.0
        or MAXIMUM_ANALYST_INPUT_TOKENS != _MAXIMUM_INPUT_TOKENS
        or maximum_p95_milliseconds != _MAXIMUM_P95_MILLISECONDS
    ):
        raise ValueError("Analyst qualification deadline contract differs")


def _require_full_complex_profile(
    maximum_sequences: int,
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
        or arguments.get("--gpu-memory-utilization") != "0.70"
        or arguments.get("--max-model-len") != "8192"
        or arguments.get("--max-num-seqs") != "8"
        or arguments.get("--max-num-batched-tokens") != "8192"
    ):
        raise ValueError("Analyst qualification requires the full complex profile")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "analyst-acceptance.json",
        server / "analyst-workload-fixtures.json",
        server / "agent-reasoning-candidates.lock.json",
        server / "agent-service-profiles/rapid-automation.json",
        server / "agent-service-profiles/complex-orchestration.json",
        server / "runtime/knowledge/postgres-pgvector.lock.json",
        server / "pyproject.toml",
        server / "uv.lock",
        server / "src/yap_server/private_artifact.py",
        server / "src/yap_server/private_postgres_connection.py",
        server / "src/yap_server/auth/principal.py",
        server / "src/yap_server/agents/admission_client.py",
        server / "src/yap_server/agents/admission_protocol.py",
        server / "src/yap_server/agents/analyst.py",
        server / "src/yap_server/agents/analyst_model.py",
        server / "src/yap_server/agents/analyst_result_audit.py",
        server / "src/yap_server/agents/analyst_runtime.py",
        server / "src/yap_server/agents/analyst_service.py",
        server / "src/yap_server/agents/librarian.py",
        server / "src/yap_server/agents/librarian_result_audit.py",
        server / "src/yap_server/agents/librarian_service.py",
        server / "src/yap_server/evaluation/agent_admission_broker_observation.py",
        server / "src/yap_server/evaluation/agent_service_lifecycle_observation.py",
        server / "src/yap_server/evaluation/checked_candidate.py",
        server / "src/yap_server/evaluation/analyst_qualification.py",
        server / "src/yap_server/evaluation/analyst_qualification_gate.py",
        server / "src/yap_server/evaluation/librarian_qualification.py",
        server / "src/yap_server/evaluation/owned_postgres_knowledge_runtime.py",
        server / "src/yap_server/evaluation/private_json_evidence.py",
        server / "src/yap_server/evaluation/provider_runtime_observations.py",
        server / "src/yap_server/knowledge/agent_reasoning_routes.py",
        server / "src/yap_server/knowledge/cancellable_database_operation.py",
        server / "src/yap_server/knowledge/generation_ledger.py",
        server / "src/yap_server/knowledge/governed_answer_protocol.py",
        server / "src/yap_server/knowledge/governed_knowledge_proposals.py",
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
        server / "src/yap_server/pools/numeric_loopback_endpoint.py",
        server / "tests/agents/test_agent_admission_client.py",
        server / "tests/agents/test_analyst_model.py",
        server / "tests/agents/test_analyst_postgres.py",
        server / "tests/agents/test_analyst_result_audit.py",
        server / "tests/agents/test_analyst_runtime.py",
        server / "tests/agents/test_analyst_service.py",
        server / "tests/agents/test_librarian.py",
        server / "tests/agents/test_librarian_result_audit.py",
        server / "tests/agents/test_librarian_postgres.py",
        server / "tests/evaluation/test_agent_admission_broker_observation.py",
        server / "tests/evaluation/test_agent_service_lifecycle_observation.py",
        server / "tests/evaluation/test_checked_candidate.py",
        server / "tests/evaluation/test_analyst_qualification.py",
        server / "tests/evaluation/test_analyst_qualification_gate.py",
        server / "tests/evaluation/test_librarian_qualification.py",
        server / "tests/evaluation/test_owned_postgres_knowledge_runtime.py",
        server / "tests/evaluation/test_private_json_evidence.py",
        server / "tests/evaluation/test_provider_runtime_observations.py",
        server / "tests/knowledge/test_cancellable_database_operation.py",
        server / "tests/knowledge/test_agent_reasoning_routes.py",
        server / "tests/knowledge/test_governed_answer_protocol.py",
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
        raise ValueError("Analyst qualification candidate inputs are incomplete")
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
            "Analyst evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Analyst evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Analyst evidence destination must be new and outside the repository"
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
        raise ValueError("Analyst private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _require_exact_teardown(value: Mapping[str, bool]) -> None:
    if set(value) != _TEARDOWN_KEYS or not all(value.values()):
        raise RuntimeError("Analyst database teardown differs")


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Analyst qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Analyst on the already-warm full complex route",
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
    receipt = run_analyst_qualification_gate(
        repository_root=options.repository_root,
        checked_head=options.checked_head,
        evidence_destination=options.evidence_destination,
        admission_socket_path=options.admission_socket,
        rapid_state_path=options.rapid_state,
        complex_state_path=options.complex_state,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True), flush=True)
    return 0 if receipt["outcome"] == "analyst-grounded-cited-answers-qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_analyst_qualification_gate"]
