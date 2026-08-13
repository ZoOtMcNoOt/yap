"""Run the exact checked Curator warm multi-owner qualification."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import tempfile
import threading
from typing import Callable, Mapping, Sequence

import psycopg

from yap_server.agents.curator import (
    CuratorEvidence,
    CuratorRequest,
    curator_request_sha256,
    curator_work_sha256,
    read_curator_evidence_in_transaction,
)
from yap_server.agents.curator_result_audit import (
    CuratorRuntimeAuditIdentity,
    PostgresCuratorResultAuditor,
    install_curator_result_audit_schema,
)
from yap_server.agents.curator_runtime import (
    CURATOR_ADMISSION_SOCKET,
    CURATOR_CANDIDATE_LOCK,
    CURATOR_KNOWLEDGE_DSN_FILE,
    CURATOR_PROFILE,
    CURATOR_RUNTIME,
    build_curator_runtime,
    load_curator_service_profile,
)
from yap_server.agents.curator_service import (
    CuratorJobView,
    CuratorServiceError,
)
from yap_server.agents.admission_client import AgentAdmissionClient
from yap_server.agents.admission_protocol import (
    AgentPurpose,
    AgentRole,
    AgentWorkSpec,
    ExecutionRoute,
    SchedulingClass,
    UnixAgentAdmissionTransport,
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
from yap_server.knowledge.okf_compiler import (
    CompiledKnowledgeGeneration,
    compile_okf_bundle,
)
from yap_server.pools.agent_vllm_service_profile import (
    RAPID_AUTOMATION_PROFILE_SHA256,
    AgentVllmServiceProfile,
)
from yap_server.private_postgres_connection import (
    private_postgres_connection_factory,
)

from .curator_qualification import (
    CuratorExpectedEvidence,
    CuratorExpectedEvidencePack,
    CuratorQualificationCase,
    CuratorQualificationCorpus,
    CuratorQualificationResult,
    build_curator_qualification_requests,
    evaluate_curator_qualification,
    load_curator_qualification_acceptance,
    load_curator_qualification_corpus,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_CURATOR_ID = "curator-qualification-curator"
_CROSS_OWNER_ID = "curator-cross-owner-probe"
_MAXIMUM_OUTPUT_TOKENS = 512
_MAXIMUM_INPUT_TOKENS = 7_680
_BROKER_ACTIVE_CAPACITY = 8
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TEARDOWN_KEYS = {
    "containerAbsent",
    "listenerAbsent",
    "networkAbsent",
    "ownedProcessAbsent",
    "sameLabelOwnersAbsent",
    "volumeAbsent",
}


def run_curator_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    complex_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Curator without launching, swapping, or reducing its model."""

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
    acceptance = load_curator_qualification_acceptance(
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
        acceptance.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS
        or acceptance.maximum_input_tokens != _MAXIMUM_INPUT_TOKENS
        or acceptance.broker_active_capacity != _BROKER_ACTIVE_CAPACITY
        or profile.maximum_sequences != acceptance.broker_active_capacity
    ):
        raise ValueError("Curator qualification capacity contract differs")
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)
    tenant_id = f"curator-q-{secrets.token_hex(8)}"
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
    result: CuratorQualificationResult | None = None
    generation: CompiledKnowledgeGeneration | None = None
    database_state: dict[str, bool] | None = None
    teardown: dict[str, bool] | None = None
    cross_owner_view: CuratorJobView | None = None
    replay_checks: dict[str, bool] | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(prefix="yap-curator-qualification-") as value:
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
            runtime = _build_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=first_dsn_path,
            )
            cross_request, cross_owner_view = _run_cross_owner_hidden(
                runtime.service,
                tenant_id=tenant_id,
                qualification_run_id=qualification_run_id,
                request=requests[corpus.cases[0].case_id],
            )
            result = evaluate_curator_qualification(
                service=runtime.service,
                corpus=corpus,
                acceptance=acceptance,
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
            before_restart = _curator_persistence_snapshot(
                restarted.dsn,
                tenant_id=tenant_id,
            )

            result_restarted = _restart_database(database, restarted)
            started = result_restarted
            second_dsn_path = private_runtime_root / "knowledge-results.dsn"
            _write_new_private_text(second_dsn_path, result_restarted.dsn)
            after_restart = _curator_persistence_snapshot(
                result_restarted.dsn,
                tenant_id=tenant_id,
            )
            if after_restart != before_restart:
                raise RuntimeError("Curator persistence changed across restart")
            restarted_runtime = _build_runtime(
                admission_socket_path=admission_socket_path,
                profile_path=profile_path,
                candidate_lock_path=candidate_lock_path,
                dsn_path=second_dsn_path,
            )
            replay_checks = _verify_replay_conflict_and_owner_isolation(
                restarted_runtime.service,
                dsn_path=second_dsn_path,
                tenant_id=tenant_id,
                corpus=corpus,
                requests=requests,
                result=result,
                cross_request=cross_request,
                cross_owner_view=cross_owner_view,
                profile=profile,
            )
            after_replay = _curator_persistence_snapshot(
                result_restarted.dsn,
                tenant_id=tenant_id,
            )
            if after_replay != after_restart:
                raise RuntimeError("Curator replay changed durable state")
            database_state = _verify_curator_database_state(
                result_restarted.dsn,
                tenant_id=tenant_id,
                corpus=corpus,
                generation_sha256=generation.generation_sha256,
                result=result,
                cross_request=cross_request,
                cross_owner_view=cross_owner_view,
                profile=profile,
                requests=requests,
                expected_packs=expected_packs,
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
        result is None
        or generation is None
        or database_state is None
        or teardown is None
        or cross_owner_view is None
        or replay_checks is None
    ):
        raise RuntimeError("Curator qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic = dict(result.public_evidence)
    semantic.pop("evidenceSha256", None)
    semantic["qualificationTenantSha256"] = hashlib.sha256(
        tenant_id.encode("utf-8")
    ).hexdigest()
    semantic["workload"] = {
        "candidateId": profile.candidate_id,
        "model": profile.expected_model,
        "modelRevision": profile.model_revision,
        "runtimeId": profile.runtime_id,
        "maximumOutputTokens": _MAXIMUM_OUTPUT_TOKENS,
        "maximumInputTokens": _MAXIMUM_INPUT_TOKENS,
        "maximumModelLength": 8_192,
        "maximumSequences": profile.maximum_sequences,
        "maximumBatchedTokens": 8_192,
        "batchInvariant": profile.batch_invariant,
        "prefixCachingEnabled": False,
        "requestSeed": 0,
        "brokerActiveCapacity": capacity_evidence["admittedOwnerCount"],
        "admissionBrokerBinarySha256": expected_broker_sha256,
        "brokerComplexProfileObserved": capacity_evidence["expectedRouteObserved"],
        "brokerExpectedCapacityObserved": capacity_evidence["expectedCapacityObserved"],
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
        **replay_checks,
        "runtimeLockSha256": database_lock.lock_sha256,
        "teardown": teardown,
    }
    receipt = bind_checked_candidate_evidence(semantic, candidate)
    private_qualification = dict(result.private_evidence)
    private_qualification["semanticEvidenceSha256"] = private_qualification.pop(
        "evidenceSha256"
    )
    write_new_private_json_evidence(
        private_evidence_destination,
        {
            "schemaVersion": 1,
            "privacyScope": "private-curator-qualification",
            "tenantId": tenant_id,
            "qualificationRunId": qualification_run_id,
            "publicEvidence": receipt,
            "qualification": private_qualification,
            "crossOwnerResult": cross_owner_view.to_wire(),
        },
    )
    return receipt


def _build_runtime(
    *,
    admission_socket_path: Path,
    profile_path: Path,
    candidate_lock_path: Path,
    dsn_path: Path,
):
    runtime = build_curator_runtime(
        {
            CURATOR_RUNTIME: "warm_gemma",
            CURATOR_ADMISSION_SOCKET: str(admission_socket_path),
            CURATOR_PROFILE: str(profile_path),
            CURATOR_CANDIDATE_LOCK: str(candidate_lock_path),
            CURATOR_KNOWLEDGE_DSN_FILE: str(dsn_path),
        },
        authenticated_team_mode=True,
    )
    if (
        runtime is None
        or runtime.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS
        or runtime.maximum_input_tokens != _MAXIMUM_INPUT_TOKENS
    ):
        raise RuntimeError("Curator qualification runtime is unavailable")
    return runtime


def _restart_database(
    database: OwnedPostgresKnowledgeRuntime,
    current: StartedKnowledgeDatabase,
) -> StartedKnowledgeDatabase:
    restarted = database.restart(timeout_seconds=120)
    if (
        restarted.container_id != current.container_id
        or restarted.process_id == current.process_id
    ):
        raise RuntimeError("Curator database restart identity differs")
    return restarted


def _initialize_curator_knowledge(
    dsn: str,
    corpus: CuratorQualificationCorpus,
    root: Path,
    *,
    tenant_id: str,
) -> CompiledKnowledgeGeneration:
    root.mkdir(mode=0o700)
    meetings = root / "meetings"
    permissions = root / "permissions"
    meetings.mkdir()
    permissions.mkdir()
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Curator qualification\n",
        encoding="utf-8",
    )
    for case in corpus.cases:
        (meetings / f"{case.case_id}.md").write_text(
            _concept_document(case, corpus.corpus_sha256, tenant_id=tenant_id),
            encoding="utf-8",
        )
        (permissions / f"{case.case_id}.yml").write_text(
            _permission_document(
                case.case_id,
                case.owner_id,
                tenant_id=tenant_id,
            ),
            encoding="utf-8",
        )
    generation = compile_okf_bundle(
        root,
        tenant_id=tenant_id,
        source_revision=corpus.corpus_sha256,
    )
    curator = AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=_CURATOR_ID,
        client_id="curator-qualification",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )
    with _connect_database(dsn) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_curator_result_audit_schema(connection)
        _assert_empty_curator_state(connection, tenant_id=tenant_id)
        admission = admit_curated_knowledge_generation(
            connection,
            principal=curator,
            repository_revision=generation.source_revision,
            source_path="server/curator-workload-fixtures.json",
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
            embedding_model_id="curator-qualification",
            embedding_model_revision=corpus.corpus_sha256,
            embeddings={chunk.chunk_id: embedding for chunk in generation.chunks},
        )
        activate_complete_generation(
            connection,
            tenant_id=tenant_id,
            generation_sha256=generation.generation_sha256,
        )
    return generation


def _assert_empty_curator_state(connection, *, tenant_id: str) -> None:
    queries = (
        "SELECT count(*) FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_builds WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_active_builds WHERE tenant_id = %s",
        "SELECT count(*) FROM yap_knowledge_proposals WHERE tenant_id = %s",
        """SELECT count(*) FROM yap_knowledge_tool_audit
           WHERE tenant_id = %s AND agent_id = 'curator'""",
        "SELECT count(*) FROM yap_curator_result_audit WHERE tenant_id = %s",
    )
    counts = tuple(
        connection.execute(query, (tenant_id,)).fetchone() for query in queries
    )
    if any(row != (0,) for row in counts):
        raise RuntimeError("Curator qualification tenant is not fresh")


def _expected_curator_evidence(
    generation: CompiledKnowledgeGeneration,
    corpus: CuratorQualificationCorpus,
) -> dict[str, tuple[CuratorExpectedEvidence, ...]]:
    concepts = {concept.concept_id: concept for concept in generation.concepts}
    expected: dict[str, tuple[CuratorExpectedEvidence, ...]] = {}
    for case in corpus.cases:
        concept = concepts.get(case.concept_id)
        if concept is None or concept.body.count(case.body) != 1:
            raise RuntimeError("Curator qualification compiled body differs")
        start = concept.body.index(case.body)
        end = start + len(case.body)
        covering = tuple(
            chunk
            for chunk in generation.chunks
            if chunk.concept_id == case.concept_id
            and chunk.char_start <= start
            and end <= chunk.char_end
            and chunk.text[start - chunk.char_start : end - chunk.char_start]
            == case.body
        )
        if len(covering) != 1:
            raise RuntimeError("Curator qualification compiled span differs")
        expected[case.case_id] = (
            CuratorExpectedEvidence(
                concept_id=case.concept_id,
                source_revision=generation.source_revision,
                content_sha256=concept.content_sha256,
                char_start=start,
                char_end=end,
                text=case.body,
            ),
        )
    return expected


def _read_back_compiled_evidence(
    dsn: str,
    *,
    tenant_id: str,
    generation: CompiledKnowledgeGeneration,
    corpus: CuratorQualificationCorpus,
    qualification_run_id: str,
    expected_evidence: Mapping[str, tuple[CuratorExpectedEvidence, ...]],
) -> tuple[dict[str, CuratorRequest], dict[str, CuratorEvidence]]:
    expected_concepts = sorted(
        (
            concept.concept_id,
            generation.source_revision,
            concept.content_sha256,
            concept.body,
        )
        for concept in generation.concepts
    )
    expected_chunks = sorted(
        (
            chunk.concept_id,
            chunk.chunk_id,
            chunk.char_start,
            chunk.char_end,
            chunk.text,
        )
        for chunk in generation.chunks
    )
    requests = build_curator_qualification_requests(
        corpus,
        qualification_run_id=qualification_run_id,
        generation_sha256=generation.generation_sha256,
        expected_evidence=expected_evidence,
    )
    packs: dict[str, CuratorEvidence] = {}
    with _connect_database(dsn) as connection:
        active = connection.execute(
            """SELECT generation_sha256 FROM yap_knowledge_active_builds
               WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchall()
        concepts = connection.execute(
            """SELECT c.concept_id, b.source_revision, c.content_sha256, c.body
               FROM yap_knowledge_concepts c
               JOIN yap_knowledge_builds b
                 ON b.tenant_id = c.tenant_id
                AND b.generation_sha256 = c.generation_sha256
               WHERE c.tenant_id = %s AND c.generation_sha256 = %s
               ORDER BY c.concept_id""",
            (tenant_id, generation.generation_sha256),
        ).fetchall()
        chunks = connection.execute(
            """SELECT concept_id, chunk_id, char_start, char_end, body
               FROM yap_knowledge_chunks
               WHERE tenant_id = %s AND generation_sha256 = %s
               ORDER BY concept_id, chunk_id""",
            (tenant_id, generation.generation_sha256),
        ).fetchall()
        if (
            active != [(generation.generation_sha256,)]
            or concepts != expected_concepts
            or chunks != expected_chunks
        ):
            raise RuntimeError("Curator compiled evidence restart readback differs")
        for case in corpus.cases:
            principal = _owner_principal(tenant_id, case.owner_id)
            with connection.transaction():
                pack = read_curator_evidence_in_transaction(
                    connection,
                    requests[case.case_id],
                    principal=principal,
                )
            expected = expected_evidence[case.case_id]
            actual = tuple(
                (
                    item.citation.concept_id,
                    item.citation.source_revision,
                    item.citation.content_sha256,
                    item.citation.char_start,
                    item.citation.char_end,
                    item.text,
                )
                for item in pack.items
            )
            wanted = tuple(
                (
                    item.concept_id,
                    item.source_revision,
                    item.content_sha256,
                    item.char_start,
                    item.char_end,
                    item.text,
                )
                for item in expected
            )
            if (
                actual != wanted
                or pack.generation_sha256 != generation.generation_sha256
            ):
                raise RuntimeError("Curator exact evidence readback differs")
            packs[case.case_id] = pack
    if set(packs) != {case.case_id for case in corpus.cases}:
        raise RuntimeError("Curator expected evidence packs are incomplete")
    return requests, packs


def _run_cross_owner_hidden(
    service: object,
    *,
    tenant_id: str,
    qualification_run_id: str,
    request: CuratorRequest,
) -> tuple[CuratorRequest, CuratorJobView]:
    cross_request = replace(
        request,
        submission_id=f"{qualification_run_id}-cross-owner",
    )
    propose = getattr(service, "propose", None)
    if not callable(propose):
        raise RuntimeError("Curator qualification service contract differs")
    view = propose(
        cross_request,
        principal=_owner_principal(tenant_id, _CROSS_OWNER_ID),
        cancellation=threading.Event(),
    )
    if (
        not isinstance(view, CuratorJobView)
        or view.status != "failed"
        or view.reason != "evidence-unavailable"
        or view.evidence_sha256 is not None
        or view.proposal_id is not None
        or view.generation_sha256 != request.expected_generation_sha256
    ):
        raise RuntimeError("Curator cross-owner evidence was visible")
    return cross_request, view


def _verify_replay_conflict_and_owner_isolation(
    service: object,
    *,
    dsn_path: Path,
    tenant_id: str,
    corpus: CuratorQualificationCorpus,
    requests: Mapping[str, CuratorRequest],
    result: CuratorQualificationResult,
    cross_request: CuratorRequest,
    cross_owner_view: CuratorJobView,
    profile: AgentVllmServiceProfile,
) -> dict[str, bool]:
    private_cases = _private_cases_by_id(result, corpus)
    propose = getattr(service, "propose", None)
    if not callable(propose):
        raise RuntimeError("Curator qualification service contract differs")
    for case in corpus.cases:
        item = private_cases[case.case_id]
        expected = CuratorJobView(
            request_id=_required_request_id(item.get("requestId")),
            submission_id=requests[case.case_id].submission_id,
            status=str(item["status"]),
            generation_sha256=requests[case.case_id].expected_generation_sha256,
            evidence_sha256=_required_sha256(item.get("evidenceSha256")),
            proposal_id=(
                _required_sha256(item.get("proposalId"))
                if item.get("proposalId") is not None
                else None
            ),
            reason=(str(item["reason"]) if item.get("reason") is not None else None),
        )
        replayed = propose(
            requests[case.case_id],
            principal=_owner_principal(tenant_id, case.owner_id),
            cancellation=threading.Event(),
        )
        if replayed != expected:
            raise RuntimeError("Curator stored result replay differs")

    cross_replay = propose(
        cross_request,
        principal=_owner_principal(tenant_id, _CROSS_OWNER_ID),
        cancellation=threading.Event(),
    )
    if cross_replay != cross_owner_view:
        raise RuntimeError("Curator cross-owner result replay differs")

    first = corpus.cases[0]
    conflict = replace(
        requests[first.case_id],
        reviewed_content=requests[first.case_id].reviewed_content + " Conflict.",
    )
    try:
        propose(
            conflict,
            principal=_owner_principal(tenant_id, first.owner_id),
            cancellation=threading.Event(),
        )
    except CuratorServiceError as error:
        conflict_rejected = (
            error.status == 409
            and error.code == "CURATOR_SUBMISSION_CONFLICT"
            and not error.retryable
        )
    else:
        conflict_rejected = False
    if not conflict_rejected:
        raise RuntimeError("Curator conflicting replay was accepted")

    auditor = PostgresCuratorResultAuditor(
        private_postgres_connection_factory(dsn_path),
        CuratorRuntimeAuditIdentity(
            candidate_id=profile.candidate_id,
            model=profile.expected_model,
            model_revision=profile.model_revision,
            runtime_id=profile.runtime_id,
            profile_sha256=profile.profile_sha256,
            candidate_lock_sha256=profile.candidate_lock_sha256,
        ),
    )
    hidden = auditor.read(
        principal=_owner_principal(tenant_id, _CROSS_OWNER_ID),
        submission_id=requests[first.case_id].submission_id,
    )
    if hidden is not None:
        raise RuntimeError("Curator stored result crossed owner authority")
    return {
        "exactStoredReplayObserved": True,
        "conflictingReplayRejected": True,
        "crossOwnerEvidenceRejected": True,
        "crossOwnerStoredResultHidden": True,
    }


def _verify_curator_database_state(
    dsn: str,
    *,
    tenant_id: str,
    corpus: CuratorQualificationCorpus,
    generation_sha256: str,
    result: CuratorQualificationResult,
    cross_request: CuratorRequest,
    cross_owner_view: CuratorJobView,
    profile: AgentVllmServiceProfile,
    requests: Mapping[str, CuratorRequest],
    expected_packs: Mapping[str, CuratorEvidence],
) -> dict[str, bool]:
    private_cases = _private_cases_by_id(result, corpus)
    provider_generation = _provider_generation(result)
    expected_proposals: list[tuple[object, ...]] = []
    expected_tool_audits: list[tuple[object, ...]] = []
    expected_result_audits: list[tuple[object, ...]] = []
    proposed_owners: set[str] = set()
    rejected_owners: set[str] = set()
    for case in corpus.cases:
        item = private_cases[case.case_id]
        request = requests[case.case_id]
        evidence = expected_packs[case.case_id]
        request_id = _required_request_id(item.get("requestId"))
        evidence_sha256 = _required_sha256(item.get("evidenceSha256"))
        if evidence_sha256 != evidence.evidence_sha256:
            raise RuntimeError("Curator result evidence identity differs")
        expected_tool_audits.append(
            (
                case.owner_id,
                "reviewed-source-evidence",
                "succeeded",
                1,
                generation_sha256,
                evidence.permission_hash,
                evidence.authorization_hash,
                True,
            )
        )
        if item.get("status") == "proposed":
            if item.get("reason") is not None:
                raise RuntimeError("Curator proposed case result differs")
            proposed_owners.add(case.owner_id)
            policy = _proposal_policy(tenant_id, case.owner_id)
            inherited_permission_sha256 = _json_sha256(policy)
            source_citations = [
                citation.model_dump(mode="json")
                for citation in request.source_citations
            ]
            proposal_id = _json_sha256(
                {
                    "tenantId": tenant_id,
                    "generationSha256": generation_sha256,
                    "proposerSubjectId": case.owner_id,
                    "proposerAgentId": "curator",
                    "proposalType": "summary",
                    "proposedContent": case.reviewed_content,
                    "sourceCitations": source_citations,
                    "inheritedPermissionSha256": inherited_permission_sha256,
                }
            )
            if item.get("proposalId") != proposal_id:
                raise RuntimeError("Curator proposal identity differs")
            proposal_authorization_hash = _authorization_hash(
                evidence.permission_hash,
                "knowledge.propose",
            )
            expected_proposals.append(
                (
                    case.owner_id,
                    proposal_id,
                    generation_sha256,
                    "curator",
                    "summary",
                    case.reviewed_content,
                    source_citations,
                    policy,
                    inherited_permission_sha256,
                    "proposed",
                )
            )
            expected_tool_audits.append(
                (
                    case.owner_id,
                    "propose",
                    "succeeded",
                    1,
                    generation_sha256,
                    evidence.permission_hash,
                    proposal_authorization_hash,
                    True,
                )
            )
            outcome = "succeeded"
            reason = None
            result_count = 1
            proposal_permission_hash = evidence.permission_hash
        elif item.get("status") == "rejected":
            if (
                item.get("status") != "rejected"
                or item.get("reason") != "model-rejected"
                or item.get("proposalId") is not None
            ):
                raise RuntimeError("Curator rejected case result differs")
            proposal_id = None
            rejected_owners.add(case.owner_id)
            outcome = "rejected"
            reason = "model-rejected"
            result_count = 0
            proposal_permission_hash = None
            proposal_authorization_hash = None
        else:
            raise RuntimeError("Curator qualification case was not model-terminal")
        expected_result_audits.append(
            (
                case.owner_id,
                request_id,
                request.submission_id,
                curator_request_sha256(request),
                curator_work_sha256(request, evidence),
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
                generation_sha256,
                evidence.evidence_sha256,
                evidence.permission_hash,
                evidence.authorization_hash,
                proposal_permission_hash,
                proposal_authorization_hash,
                proposal_id,
                outcome,
                reason,
                result_count,
                True,
            )
        )

    cross_request_id = _required_request_id(cross_owner_view.request_id)
    expected_tool_audits.append(
        (
            _CROSS_OWNER_ID,
            "reviewed-source-evidence",
            "failed",
            0,
            None,
            None,
            None,
            True,
        )
    )
    expected_result_audits.append(
        (
            _CROSS_OWNER_ID,
            cross_request_id,
            cross_request.submission_id,
            curator_request_sha256(cross_request),
            None,
            "knowledge-propose",
            "complex-orchestration",
            "background-llm",
            None,
            profile.candidate_id,
            profile.expected_model,
            profile.model_revision,
            profile.runtime_id,
            profile.profile_sha256,
            profile.candidate_lock_sha256,
            generation_sha256,
            None,
            None,
            None,
            None,
            None,
            None,
            "failed",
            "evidence-unavailable",
            0,
            True,
        )
    )

    with _connect_database(dsn) as connection:
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
        proposals = _proposal_rows(connection, tenant_id=tenant_id)
        tool_audits = _tool_audit_rows(connection, tenant_id=tenant_id)
        result_audits = _result_audit_rows(connection, tenant_id=tenant_id)
    proposal_owners = {str(row[0]) for row in proposals}
    successful_propose_owners = {
        str(row[0]) for row in tool_audits if row[1:4] == ("propose", "succeeded", 1)
    }
    checks = {
        "activeGenerationUnchanged": active == [(generation_sha256,)],
        "singleGenerationRetained": build_count == (1,),
        "singleSourceAdmissionRetained": admission_count == (1,),
        "proposalRowsExact": sorted(proposals) == sorted(expected_proposals),
        "genericReadAndProposeAuditsExact": sorted(tool_audits)
        == sorted(expected_tool_audits),
        "curatorResultAuditIdentitiesExact": sorted(result_audits)
        == sorted(expected_result_audits),
        "rejectedProposalAndSuccessRowsAbsent": (
            proposal_owners == proposed_owners
            and successful_propose_owners == proposed_owners
            and proposal_owners.isdisjoint(rejected_owners)
        ),
    }
    if not all(checks.values()):
        raise RuntimeError("Curator durable state differs after qualification")
    return checks


def _curator_persistence_snapshot(
    dsn: str,
    *,
    tenant_id: str,
) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...]]:
    with _connect_database(dsn) as connection:
        return (
            tuple(_proposal_rows(connection, tenant_id=tenant_id)),
            tuple(_tool_audit_rows(connection, tenant_id=tenant_id)),
            tuple(_result_audit_rows(connection, tenant_id=tenant_id)),
        )


def _proposal_rows(connection, *, tenant_id: str) -> list[tuple[object, ...]]:
    return connection.execute(
        """SELECT proposer_subject_id, proposal_id, generation_sha256,
                  proposer_agent_id, proposal_type, proposed_content,
                  source_citations, inherited_policy,
                  inherited_permission_sha256, status
           FROM yap_knowledge_proposals
           WHERE tenant_id = %s
           ORDER BY proposer_subject_id, proposal_id""",
        (tenant_id,),
    ).fetchall()


def _tool_audit_rows(connection, *, tenant_id: str) -> list[tuple[object, ...]]:
    return connection.execute(
        """SELECT subject_id, operation, outcome, result_count,
                  generation_sha256, permission_hash, authorization_hash,
                  duration_milliseconds >= 0
           FROM yap_knowledge_tool_audit
           WHERE tenant_id = %s AND agent_id = 'curator'
           ORDER BY subject_id, operation, audit_id""",
        (tenant_id,),
    ).fetchall()


def _result_audit_rows(connection, *, tenant_id: str) -> list[tuple[object, ...]]:
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
           WHERE tenant_id = %s
           ORDER BY subject_id, submission_id""",
        (tenant_id,),
    ).fetchall()


def _private_cases_by_id(
    result: CuratorQualificationResult,
    corpus: CuratorQualificationCorpus,
) -> dict[str, dict[str, object]]:
    raw = result.private_evidence.get("cases")
    if not isinstance(raw, list) or len(raw) != len(corpus.cases):
        raise RuntimeError("Curator private case evidence is incomplete")
    cases: dict[str, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("caseId"), str):
            raise RuntimeError("Curator private case evidence is invalid")
        case_id = str(item["caseId"])
        if case_id in cases:
            raise RuntimeError("Curator private case evidence is duplicated")
        cases[case_id] = item
    if set(cases) != {case.case_id for case in corpus.cases}:
        raise RuntimeError("Curator private case identities differ")
    return cases


def _provider_generation(result: CuratorQualificationResult) -> int:
    warm_state = result.private_evidence.get("warmState")
    before = warm_state.get("before") if isinstance(warm_state, dict) else None
    value = before.get("processGeneration") if isinstance(before, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError("Curator provider generation is invalid")
    return value


def _owner_principal(tenant_id: str, owner_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        subject_id=owner_id,
        client_id="curator-qualification",
        scopes=frozenset({"knowledge.read", "knowledge.propose"}),
    )


def _connect_database(dsn: str):
    return psycopg.connect(
        dsn,
        connect_timeout=3,
        options="-c statement_timeout=3000 -c lock_timeout=3000",
    )


def _required_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RuntimeError("Curator private SHA-256 identity is invalid")
    return value


def _required_request_id(value: object) -> str:
    if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
        raise RuntimeError("Curator private request identity is invalid")
    return value


def _proposal_policy(tenant_id: str, owner_id: str) -> dict[str, object]:
    return {
        "audience": [{"tenantId": tenant_id, "subjectId": owner_id}],
        "denials": [],
        "purposes": ["knowledge.read"],
        "classification": "internal",
        "canonical": False,
    }


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _authorization_hash(permission_hash: str, capability: str) -> str:
    return _json_sha256(
        {
            "permissionHash": permission_hash,
            "requiredCapability": capability,
        }
    )


def _concept_document(
    case: CuratorQualificationCase,
    source_revision: str,
    *,
    tenant_id: str,
) -> str:
    return f"""---
type: Meeting
title: {case.title}
resource: yap://tenant/{tenant_id}/meeting/{case.case_id}
timestamp: 2026-08-12T16:00:00Z
yap_schema: 1
provenance: {{source: curator-public-synthetic, source_revision: {source_revision}}}
---
# {case.title}

{case.body}
"""


def _permission_document(
    case_id: str,
    owner_id: str,
    *,
    tenant_id: str,
) -> str:
    return f"""path_prefix: meetings/{case_id}
audience: {{users: [{{tenant_id: {tenant_id}, subject_id: {owner_id}}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
"""


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
        raise ValueError("Curator qualification requires the full complex profile")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "curator-acceptance.json",
        server / "curator-workload-fixtures.json",
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
        server / "src/yap_server/agents/curator.py",
        server / "src/yap_server/agents/curator_model.py",
        server / "src/yap_server/agents/curator_publisher.py",
        server / "src/yap_server/agents/curator_result_audit.py",
        server / "src/yap_server/agents/curator_runtime.py",
        server / "src/yap_server/agents/curator_service.py",
        server / "src/yap_server/agents/student.py",
        server / "src/yap_server/agents/student_model.py",
        server / "src/yap_server/evaluation/agent_admission_broker_observation.py",
        server / "src/yap_server/evaluation/agent_service_lifecycle_observation.py",
        server / "src/yap_server/evaluation/checked_candidate.py",
        server / "src/yap_server/evaluation/curator_qualification.py",
        server / "src/yap_server/evaluation/curator_qualification_gate.py",
        server / "src/yap_server/evaluation/owned_postgres_knowledge_runtime.py",
        server / "src/yap_server/evaluation/private_json_evidence.py",
        server / "src/yap_server/evaluation/provider_runtime_observations.py",
        server / "src/yap_server/knowledge/agent_reasoning_routes.py",
        server / "src/yap_server/knowledge/cancellable_database_operation.py",
        server / "src/yap_server/knowledge/generation_ledger.py",
        server / "src/yap_server/knowledge/knowledge_proposals.py",
        server / "src/yap_server/knowledge/knowledge_source_admission.py",
        server / "src/yap_server/knowledge/knowledge_tool_audit.py",
        server / "src/yap_server/knowledge/knowledge_tool_contract.py",
        server / "src/yap_server/knowledge/governed_answer_protocol.py",
        server / "src/yap_server/knowledge/okf_compiler.py",
        server / "src/yap_server/knowledge/okf_profile.py",
        server / "src/yap_server/knowledge/okf_projection.py",
        server / "src/yap_server/knowledge/okf_source.py",
        server / "src/yap_server/knowledge/permission_policy.py",
        server / "src/yap_server/knowledge/postgres_knowledge_retrieval.py",
        server / "src/yap_server/knowledge/postgres_permission_view.py",
        server / "src/yap_server/knowledge/vllm_reasoning_client.py",
        server / "src/yap_server/pools/agent_vllm_launch_contract.py",
        server / "src/yap_server/pools/agent_vllm_service_profile.py",
        server / "src/yap_server/pools/agent_vllm_service_profile_cli.py",
        server / "src/yap_server/pools/numeric_loopback_endpoint.py",
        server / "tests/agents/test_agent_admission_client.py",
        server / "tests/agents/test_curator.py",
        server / "tests/agents/test_curator_postgres.py",
        server / "tests/agents/test_curator_runtime.py",
        server / "tests/evaluation/test_agent_admission_broker_observation.py",
        server / "tests/evaluation/test_agent_service_lifecycle_observation.py",
        server / "tests/evaluation/test_checked_candidate.py",
        server / "tests/evaluation/test_curator_qualification.py",
        server / "tests/evaluation/test_curator_qualification_gate.py",
        server / "tests/evaluation/test_owned_postgres_knowledge_runtime.py",
        server / "tests/infra/test_agent_vllm_server.py",
        server / "tests/evaluation/test_private_json_evidence.py",
        server / "tests/pools/test_agent_vllm_service_profile.py",
        server / "orchestrator/Cargo.toml",
        server / "orchestrator/Cargo.lock",
        server / "orchestrator/src/lib.rs",
        server / "orchestrator/src/service_profile.rs",
        server / "orchestrator/tests/supervised_service.rs",
        repository_root / "infra/yap-server-node/agent-vllm-server.sh",
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
        raise ValueError("Curator qualification candidate inputs are incomplete")
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
            "Curator evidence destination must be new and outside the repository"
        )
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Curator evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError(
            "Curator evidence destination must be new and outside the repository"
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
        raise ValueError("Curator private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _require_exact_teardown(value: Mapping[str, bool]) -> None:
    if set(value) != _TEARDOWN_KEYS or not all(value.values()):
        raise RuntimeError("Curator database teardown differs")


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Curator qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Curator on the already-warm full complex route",
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
    receipt = run_curator_qualification_gate(
        repository_root=options.repository_root,
        checked_head=options.checked_head,
        evidence_destination=options.evidence_destination,
        admission_socket_path=options.admission_socket,
        rapid_state_path=options.rapid_state,
        complex_state_path=options.complex_state,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True), flush=True)
    return 0 if receipt["outcome"] == "curator-knowledge-proposals-qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_curator_qualification_gate"]
