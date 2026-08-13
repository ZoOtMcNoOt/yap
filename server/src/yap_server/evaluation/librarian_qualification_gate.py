"""Run the exact checked Librarian permission-safe qualification."""

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
    PostgresLibrarianEvidenceReader,
    librarian_request_sha256,
    librarian_work_sha256,
)
from yap_server.agents.librarian_result_audit import (
    PostgresLibrarianResultAuditor,
    install_librarian_result_audit_schema,
)
from yap_server.agents.librarian_service import (
    LIBRARIAN_OPERATION_DEADLINE_SECONDS,
    LIBRARIAN_TERMINAL_AUDIT_DEADLINE_SECONDS,
    LIBRARIAN_WORKFLOW_DEADLINE_SECONDS,
    LibrarianJobView,
    LibrarianService,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.evaluation.agent_admission_broker_observation import (
    build_checked_admission_broker,
    observe_admission_broker,
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
from yap_server.knowledge.okf_compiler import (
    CompiledKnowledgeGeneration,
    compile_okf_bundle,
)
from yap_server.pools.agent_vllm_service_profile import (
    load_complex_agent_vllm_service_profile,
    load_rapid_agent_vllm_service_profile,
)
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
    private_postgres_connection_factory,
)

from .librarian_qualification import (
    LibrarianBoundQualificationCorpus,
    LibrarianQualificationCorpus,
    LibrarianQualificationInvocation,
    LibrarianQualificationRenderedGeneration,
    LibrarianQualificationResult,
    bind_librarian_compiled_corpus,
    build_librarian_qualification_invocations,
    evaluate_librarian_qualification,
    load_librarian_qualification_acceptance,
    load_librarian_qualification_corpus,
    render_librarian_qualification_generations,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_CURATOR_ID = "librarian-qualification-curator"
_SOURCE_PATH = "server/librarian-workload-fixtures.json"
_BROKER_ACTIVE_CAPACITY = 1
_MAXIMUM_P95_MILLISECONDS = 16_000
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
    rendered: tuple[LibrarianQualificationRenderedGeneration, ...]
    compiled: dict[str, CompiledKnowledgeGeneration]
    bound: LibrarianBoundQualificationCorpus


def run_librarian_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Librarian without invoking either model provider."""

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
    acceptance = load_librarian_qualification_acceptance(
        root / "server/librarian-acceptance.json"
    )
    corpus = load_librarian_qualification_corpus(
        root / "server/librarian-workload-fixtures.json"
    )
    _require_exact_deadline_contract(acceptance.maximum_p95_milliseconds)

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
        raise ValueError("Librarian broker candidate lock identity differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"librarian-q-{secrets.token_hex(8)}"
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
    initialized: _InitializedKnowledge | None = None
    result: LibrarianQualificationResult | None = None
    database_state: dict[str, bool] | None = None
    teardown: dict[str, bool] | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(prefix="yap-librarian-qualification-") as value:
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
            connection_factory = private_postgres_connection_factory(dsn_path)
            result = evaluate_librarian_qualification(
                executor=_build_librarian_executor(
                    admission_socket_path,
                    connection_factory,
                ),
                corpus=initialized.bound,
                acceptance=acceptance,
            )
            if result.public_evidence.get("qualified") is not True:
                raise RuntimeError("Librarian qualification did not meet acceptance")

            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            database_state = _verify_librarian_database_state(
                result_restarted.dsn,
                initialized,
                result,
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
        raise RuntimeError("Librarian qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic = dict(result.public_evidence)
    semantic["qualificationScope"] = "librarian-permission-safe-evidence"
    semantic["outcome"] = "librarian-permission-safe-evidence-qualified"
    semantic["acceptancePlanSha256"] = acceptance.plan_sha256
    semantic["corpusSha256"] = corpus.corpus_sha256
    semantic["qualificationTenantSha256"] = hashlib.sha256(
        tenant_id.encode("utf-8")
    ).hexdigest()
    semantic["qualificationRunSha256"] = hashlib.sha256(
        qualification_run_id.encode("utf-8")
    ).hexdigest()
    semantic["workload"] = {
        "route": "server-io",
        "schedulingClass": "interactive",
        "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
        "admissionBrokerBinarySha256": expected_broker_sha256,
        "brokerExpectedCapacityObserved": capacity_evidence[
            "expectedCapacityObserved"
        ],
        "secondOwnerQueued": capacity_evidence["overflowOwnerQueued"],
        "queuedCancellationCompleted": capacity_evidence[
            "queuedCancellationCompleted"
        ],
        "activeCancellationRequested": capacity_evidence[
            "activeCancellationRequested"
        ],
        "activeCancellationAcknowledged": capacity_evidence[
            "activeCancellationAcknowledged"
        ],
        "capacityProbeContained": capacity_evidence["contained"],
        "capacityProbeBrokerIdentityUnchanged": capacity_evidence[
            "brokerIdentityUnchanged"
        ],
        "librarianModelRouteLeaseRequestsAbsent": True,
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
            "privacyScope": "private-librarian-qualification",
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


def _initialize_librarian_knowledge(
    dsn: str,
    corpus: LibrarianQualificationCorpus,
    root: Path,
    *,
    tenant_id: str,
) -> _InitializedKnowledge:
    root.mkdir(mode=0o700)
    rendered = render_librarian_qualification_generations(
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
    bound = bind_librarian_compiled_corpus(corpus, rendered, compiled)

    curator = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=_CURATOR_ID,
        client_id="librarian-qualification",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )
    order = tuple(item.generation_id for item in corpus.generations)
    if order != ("predecessor", "successor"):
        raise ValueError("Librarian qualification generation order differs")
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_librarian_result_audit_schema(connection)
        _assert_empty_librarian_state(connection, tenant_id=tenant_id)
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
                embedding_model_id="librarian-qualification",
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
    generation: LibrarianQualificationRenderedGeneration,
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
            raise ValueError("Librarian rendered file is invalid")
        path = root.joinpath(*relative.parts)
        if path in seen:
            raise ValueError("Librarian rendered file is duplicated")
        seen.add(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(item.body)
            output.flush()
            os.fsync(output.fileno())


def _assert_empty_librarian_state(connection, *, tenant_id: str) -> None:
    tables = (
        "yap_knowledge_builds",
        "yap_knowledge_source_admissions",
        "yap_knowledge_active_builds",
        "yap_knowledge_activation_history",
        "yap_knowledge_proposals",
        "yap_knowledge_tool_audit",
        "yap_librarian_result_audit",
    )
    counts = tuple(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        for table in tables
    )
    if counts != ((0,),) * len(tables):
        raise RuntimeError("Librarian qualification tenant is not fresh")


def _restart_database(
    database: OwnedPostgresKnowledgeRuntime,
    started: StartedKnowledgeDatabase,
) -> StartedKnowledgeDatabase:
    restarted = database.restart(timeout_seconds=120)
    if (
        restarted.container_id != started.container_id
        or restarted.process_id == started.process_id
    ):
        raise RuntimeError("Librarian database restart identity differs")
    return restarted


def _build_librarian_executor(
    admission_socket_path: Path,
    connection_factory: PrivatePostgresConnectionFactory,
):
    reader = PostgresLibrarianEvidenceReader(connection_factory)
    auditor = PostgresLibrarianResultAuditor(connection_factory)

    def execute(
        invocation: LibrarianQualificationInvocation,
        cancellation: threading.Event,
    ) -> LibrarianJobView:
        if invocation.purpose != "knowledge.read":
            raise ValueError("Librarian qualification purpose differs")
        selected_reader = (
            _DeadlineEvidenceReader(reader)
            if invocation.mode == "deadline"
            else reader
        )
        service = LibrarianService(
            admission=AgentAdmissionClient(
                UnixAgentAdmissionTransport(admission_socket_path)
            ),
            evidence_reader=selected_reader,
            result_auditor=auditor,
        )
        principal = AuthenticatedPrincipal(
            tenant_id=invocation.tenant_id,
            subject_id=invocation.owner_id,
            client_id="librarian-qualification",
            scopes=frozenset({"knowledge.read"}),
        )
        return service.query(
            LibrarianRequest(
                search_text=invocation.search_text,
                maximum_results=invocation.maximum_results,
                expected_generation_sha256=(
                    invocation.expected_generation_sha256
                ),
            ),
            principal=principal,
            cancellation=cancellation,
        )

    return execute


class _DeadlineEvidenceReader:
    def __init__(self, delegate: PostgresLibrarianEvidenceReader) -> None:
        self._delegate = delegate

    def read(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> LibrarianEvidencePack:
        if not cancellation.wait(LIBRARIAN_WORKFLOW_DEADLINE_SECONDS):
            raise TimeoutError("Librarian qualification deadline did not fire")
        return self._delegate.read(
            request,
            principal=principal,
            cancellation=cancellation,
        )


def _probe_server_io_capacity(
    client: AgentAdmissionClient,
    *,
    tenant_id: str,
    run_scope: str,
    observe_broker_state: Callable[[], Mapping[str, object]],
) -> dict[str, object]:
    if (
        not isinstance(client, AgentAdmissionClient)
        or not tenant_id
        or not run_scope
        or not callable(observe_broker_state)
    ):
        raise ValueError("Librarian Server-IO capacity probe is invalid")
    work = AgentWorkSpec(
        role=AgentRole.LIBRARIAN,
        purpose=AgentPurpose.KNOWLEDGE_READ,
        route=ExecutionRoute.SERVER_IO,
        scheduling_class=SchedulingClass.INTERACTIVE,
    )
    before = dict(observe_broker_state())
    tickets: list[AgentAdmissionTicket] = []
    admissions = []
    queued_cancelled = False
    active_requested = False
    active_acknowledged = False
    body_error: BaseException | None = None
    try:
        for index in range(2):
            ticket = client.new_ticket()
            tickets.append(ticket)
            principal = AuthenticatedPrincipal(
                tenant_id=tenant_id,
                subject_id=f"capacity-{run_scope}-{index}",
                client_id="librarian-capacity-probe",
                scopes=frozenset(),
            )
            source_sha256 = hashlib.sha256(
                f"{tenant_id}\0{run_scope}\0{index}".encode("utf-8")
            ).hexdigest()
            admissions.append(
                client.submit(
                    ticket,
                    principal=principal,
                    work=work,
                    source_sha256=source_sha256,
                    remaining_deadline_ms=60_000,
                )
            )
        first, second = admissions
        if (
            first.outcome != "admitted"
            or first.route != ExecutionRoute.SERVER_IO
            or first.provider_generation is not None
            or second.outcome != "queued"
        ):
            raise RuntimeError("Librarian broker Server-IO capacity differs")
    except BaseException as error:
        body_error = error
    finally:
        cleanup_error: BaseException | None = None
        if len(tickets) >= 2:
            try:
                queued, queued_acknowledged = _cancel_capacity_ticket(
                    client,
                    tickets[1],
                )
                queued_cancelled = (
                    queued.outcome == "cancelled" and not queued_acknowledged
                )
            except BaseException as error:
                cleanup_error = error
        if tickets:
            try:
                active, active_acknowledged = _cancel_capacity_ticket(
                    client,
                    tickets[0],
                )
                active_requested = (
                    active.outcome == "cancellation-requested"
                    and active.cancellation_reason == "client-requested"
                )
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise RuntimeError(
                "Librarian Server-IO capacity probe was not contained"
            ) from cleanup_error
    after = dict(observe_broker_state())
    if before != after:
        identity_error = RuntimeError(
            "Librarian capacity probe changed broker identity"
        )
        if body_error is not None:
            raise identity_error from body_error
        raise identity_error
    if body_error is not None:
        raise body_error
    return {
        "admittedOwnerCount": sum(
            item.outcome == "admitted" for item in admissions
        ),
        "expectedCapacityObserved": admissions[0].outcome == "admitted",
        "overflowOwnerQueued": admissions[1].outcome == "queued",
        "queuedCancellationCompleted": queued_cancelled,
        "activeCancellationRequested": active_requested,
        "activeCancellationAcknowledged": active_acknowledged,
        "contained": queued_cancelled and active_acknowledged,
        "brokerIdentityUnchanged": True,
    }


def _cancel_capacity_ticket(
    client: AgentAdmissionClient,
    ticket: AgentAdmissionTicket,
) -> tuple[object, bool]:
    cancelled = client.cancel(ticket)
    if cancelled.outcome == "cancelled":
        return cancelled, False
    if (
        cancelled.outcome != "cancellation-requested"
        or cancelled.cancellation_reason != "client-requested"
    ):
        raise RuntimeError("Librarian capacity cancellation identity differs")
    acknowledged = client.acknowledge_cancellation(ticket)
    if acknowledged.outcome != "cancelled":
        raise RuntimeError("Librarian capacity cancellation was not acknowledged")
    return cancelled, True


def _verify_librarian_database_state(
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
    }
    if not all(checks.values()):
        raise RuntimeError("Librarian durable state differs after qualification")
    return checks


def _expected_audit_rows(
    initialized: _InitializedKnowledge,
    result: LibrarianQualificationResult,
) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    bound = initialized.bound
    invocations = build_librarian_qualification_invocations(
        bound.corpus,
        tenant_id=bound.tenant_id,
        generation_sha256s=bound.generation_sha256s,
    )
    observations = {
        item.invocation.invocation_id: item for item in result.observations
    }
    if (
        set(observations) != {item.invocation_id for item in invocations}
        or any(not item.exact_match for item in observations.values())
    ):
        raise RuntimeError("Librarian qualification observations differ")
    result_rows: list[tuple[object, ...]] = []
    tool_rows: list[tuple[object, ...]] = []
    for invocation in invocations:
        observation = observations[invocation.invocation_id]
        request_id = observation.request_id
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            raise RuntimeError("Librarian request audit identity is invalid")
        request = LibrarianRequest(
            search_text=invocation.search_text,
            maximum_results=invocation.maximum_results,
            expected_generation_sha256=invocation.expected_generation_sha256,
        )
        expected = bound.expected_views[invocation.invocation_id]
        pack = _expected_audit_pack(initialized, invocation)
        if expected.status == "complete":
            outcome = "succeeded"
        elif expected.status == "evidence-unavailable":
            outcome = "unavailable"
        elif expected.status == "failed" and expected.reason == "stale-generation":
            outcome = "unavailable"
        elif expected.status == "cancelled":
            outcome = "cancelled"
        else:
            raise RuntimeError("Librarian expected terminal audit differs")
        result_count = len(pack.items) if expected.status == "complete" and pack else 0
        result_rows.append(
            (
                invocation.owner_id,
                request_id,
                librarian_request_sha256(request),
                librarian_work_sha256(request, pack) if pack is not None else None,
                pack.evidence_sha256 if pack is not None else None,
                (
                    pack.generation_sha256
                    if pack is not None
                    else request.expected_generation_sha256
                ),
                pack.permission_hash if pack is not None else None,
                pack.authorization_hash if pack is not None else None,
                "librarian",
                "knowledge-read",
                "server-io",
                "interactive",
                outcome,
                expected.reason,
                result_count,
            )
        )
        if invocation.mode == "pre-cancelled":
            continue
        if pack is not None:
            tool_rows.append(
                (
                    invocation.owner_id,
                    "search",
                    "succeeded",
                    len(pack.items),
                    pack.generation_sha256,
                    pack.permission_hash,
                    pack.authorization_hash,
                )
            )
        else:
            tool_rows.append(
                (
                    invocation.owner_id,
                    "search",
                    "cancelled" if invocation.mode == "deadline" else "failed",
                    0,
                    None,
                    None,
                    None,
                )
            )
    return result_rows, tool_rows


def _expected_audit_pack(
    initialized: _InitializedKnowledge,
    invocation: LibrarianQualificationInvocation,
) -> LibrarianEvidencePack | None:
    bound = initialized.bound
    corpus = bound.corpus
    case = next(item for item in corpus.cases if item.case_id == invocation.case_id)
    active_sha256 = bound.generation_sha256s[case.active_generation_id]
    if invocation.mode != "normal" or invocation.expected_generation_sha256 != active_sha256:
        return None
    fixture_generation = next(
        item for item in corpus.generations if item.generation_id == case.active_generation_id
    )
    compiled = initialized.compiled[case.active_generation_id]
    visible = {
        source.concept_id
        for source in fixture_generation.sources
        if case.owner_id in source.visible_to_owner_ids
    }
    concepts = {item.concept_id: item for item in compiled.concepts}
    permissions = {item.path_prefix: item for item in compiled.permissions}
    try:
        permission_sha256s = sorted(
            {
                permissions[concepts[concept_id].permission_path_prefix].permission_sha256
                for concept_id in visible
            }
        )
    except KeyError as error:
        raise RuntimeError("Librarian compiled audit permission differs") from error
    permission_hash = _json_sha256(
        {
            "tenantId": bound.tenant_id,
            "subjectId": case.owner_id,
            "purpose": case.request.purpose,
            "generationSha256": active_sha256,
            "permissionSha256s": permission_sha256s,
            "visibleConceptIds": sorted(visible),
        }
    )
    authorization_hash = _json_sha256(
        {
            "permissionHash": permission_hash,
            "requiredCapability": "knowledge.search.lexical",
        }
    )
    expected = bound.expected_views[invocation.invocation_id]
    items = tuple(
        LibrarianEvidenceItem(
            concept_id=item.concept_id,
            source_revision=item.source_revision,
            content_sha256=item.content_sha256,
            char_start=item.char_start,
            char_end=item.char_end,
            text=item.text,
        )
        for item in expected.items
    )
    return LibrarianEvidencePack.create(
        generation_sha256=active_sha256,
        permission_hash=permission_hash,
        authorization_hash=authorization_hash,
        items=items,
        output_budget_exhausted=False,
    )


def _private_observations(
    result: LibrarianQualificationResult,
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
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sorted_rows(rows) -> list[tuple[object, ...]]:
    return sorted((tuple(row) for row in rows), key=repr)


def _require_exact_deadline_contract(maximum_p95_milliseconds: int) -> None:
    if (
        LIBRARIAN_OPERATION_DEADLINE_SECONDS != 15.0
        or LIBRARIAN_TERMINAL_AUDIT_DEADLINE_SECONDS != 19.0
        or LIBRARIAN_WORKFLOW_DEADLINE_SECONDS != 21.0
        or maximum_p95_milliseconds != _MAXIMUM_P95_MILLISECONDS
    ):
        raise ValueError("Librarian qualification deadline contract differs")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "librarian-acceptance.json",
        server / "librarian-workload-fixtures.json",
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
        server / "src/yap_server/agents/librarian.py",
        server / "src/yap_server/agents/librarian_result_audit.py",
        server / "src/yap_server/agents/librarian_service.py",
        server / "src/yap_server/evaluation/agent_admission_broker_observation.py",
        server / "src/yap_server/evaluation/checked_candidate.py",
        server / "src/yap_server/evaluation/librarian_qualification.py",
        server / "src/yap_server/evaluation/librarian_qualification_gate.py",
        server / "src/yap_server/evaluation/owned_postgres_knowledge_runtime.py",
        server / "src/yap_server/evaluation/private_json_evidence.py",
        server / "src/yap_server/evaluation/provider_runtime_observations.py",
        server / "src/yap_server/knowledge/cancellable_database_operation.py",
        server / "src/yap_server/knowledge/generation_ledger.py",
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
        server / "src/yap_server/pools/agent_vllm_launch_contract.py",
        server / "src/yap_server/pools/agent_vllm_service_profile.py",
        server / "src/yap_server/pools/numeric_loopback_endpoint.py",
        server / "tests/agents/test_agent_admission_client.py",
        server / "tests/agents/test_librarian.py",
        server / "tests/agents/test_librarian_postgres.py",
        server / "tests/agents/test_librarian_result_audit.py",
        server / "tests/evaluation/test_agent_admission_broker_observation.py",
        server / "tests/evaluation/test_checked_candidate.py",
        server / "tests/evaluation/test_librarian_qualification.py",
        server / "tests/evaluation/test_librarian_qualification_gate.py",
        server / "tests/evaluation/test_owned_postgres_knowledge_runtime.py",
        server / "tests/evaluation/test_private_json_evidence.py",
        server / "tests/knowledge/test_cancellable_database_operation.py",
        server / "tests/knowledge/test_okf_compiler.py",
        server / "tests/knowledge/test_postgres_generation_ledger.py",
        server / "tests/knowledge/test_postgres_permission_safe_retrieval.py",
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
        raise ValueError("Librarian qualification candidate inputs are incomplete")
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
            "Librarian evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Librarian evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Librarian evidence destination must be new and outside the repository"
        )
    return requested


def _write_new_private_text(path: Path, value: str) -> None:
    if path.exists() or path.is_symlink() or not value or "\n" in value or "\r" in value:
        raise ValueError("Librarian private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _require_exact_teardown(value: Mapping[str, bool]) -> None:
    if set(value) != _TEARDOWN_KEYS or not all(value.values()):
        raise RuntimeError("Librarian database teardown differs")


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Librarian qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Librarian on the fixed Server-IO route",
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
    receipt = run_librarian_qualification_gate(
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
        == "librarian-permission-safe-evidence-qualified"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_librarian_qualification_gate"]
