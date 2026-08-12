"""Run the exact checked Student warm multi-owner qualification."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import threading
from typing import Callable, Sequence

import psycopg

from yap_server.agents.student import (
    StudentRequest,
    student_request_sha256,
    student_work_identity_sha256,
)
from yap_server.agents.student_result_audit import (
    install_student_result_audit_schema,
)
from yap_server.agents.student_service import StudentJobView
from yap_server.agents.student_runtime import (
    STUDENT_ADMISSION_SOCKET,
    STUDENT_CANDIDATE_LOCK,
    STUDENT_KNOWLEDGE_DSN_FILE,
    STUDENT_PROFILE,
    STUDENT_RUNTIME,
    build_student_runtime,
    load_student_service_profile,
)
from yap_server.auth import AuthenticatedPrincipal
from yap_server.evaluation.agent_admission_broker_observation import (
    build_checked_admission_broker,
    observe_admission_broker,
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
from yap_server.knowledge.okf_projection import CompiledChunk
from yap_server.pools.agent_vllm_service_profile import AgentVllmServiceProfile

from .student_qualification import (
    StudentQualificationCase,
    StudentQualificationCorpus,
    StudentExpectedEvidence,
    StudentQualificationResult,
    evaluate_student_qualification,
    load_student_qualification_acceptance,
    load_student_qualification_corpus,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_TENANT_ID = "student-qualification"
_CURATOR_ID = "student-qualification-curator"
_CROSS_OWNER_ID = "student-cross-owner-probe"
_MAXIMUM_OUTPUT_TOKENS = 512
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def run_student_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify Student without launching, swapping, or reducing its model."""

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
    acceptance = load_student_qualification_acceptance(
        root / "server/student-acceptance.json"
    )
    corpus = load_student_qualification_corpus(
        root / "server/student-workload-fixtures.json"
    )
    profile_path = root / "server/agent-service-profiles/rapid-automation.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_student_service_profile(profile_path, candidate_lock_path)
    _require_full_rapid_profile(profile.maximum_sequences, profile.launch_arguments)
    expected_broker_sha256 = build_checked_admission_broker(root, runner=runner)

    def observe_provider() -> dict[str, object]:
        value = read_service_state(rapid_state_path)
        validate_state_identity(value, profile)
        probe_exact_service(profile)
        return value

    def observe_admission() -> dict[str, object]:
        return observe_admission_broker(
            admission_socket_path,
            expected_binary_sha256=expected_broker_sha256,
            expected_candidate_lock_sha256=profile.candidate_lock_sha256,
            expected_rapid_profile_sha256=profile.profile_sha256,
            expected_rapid_state_path=rapid_state_path,
        )

    observe_provider()
    observe_admission()
    database_lock = load_knowledge_database_runtime_lock(root)
    database = OwnedPostgresKnowledgeRuntime(
        checked_head=checked_head,
        runtime_lock=database_lock,
        runner=runner,
    )
    started: StartedKnowledgeDatabase | None = None
    result: StudentQualificationResult | None = None
    teardown: dict[str, bool] | None = None
    generation: CompiledKnowledgeGeneration | None = None
    database_state: dict[str, bool] | None = None
    cross_owner_rejected = False
    cross_owner_view: StudentJobView | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(prefix="yap-student-qualification-") as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            generation = _initialize_student_knowledge(
                started.dsn,
                corpus,
                private_runtime_root / "okf",
            )
            restarted = database.restart(timeout_seconds=120)
            if (
                restarted.container_id != started.container_id
                or restarted.process_id == started.process_id
            ):
                raise RuntimeError("Student database restart identity differs")
            started = restarted
            dsn_path = private_runtime_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, restarted.dsn)
            runtime = build_student_runtime(
                {
                    STUDENT_RUNTIME: "warm_qwen",
                    STUDENT_ADMISSION_SOCKET: str(admission_socket_path),
                    STUDENT_PROFILE: str(profile_path),
                    STUDENT_CANDIDATE_LOCK: str(candidate_lock_path),
                    STUDENT_KNOWLEDGE_DSN_FILE: str(dsn_path),
                },
                authenticated_team_mode=True,
            )
            if runtime is None or runtime.maximum_output_tokens != _MAXIMUM_OUTPUT_TOKENS:
                raise RuntimeError("Student qualification runtime is unavailable")
            cross_owner_view = _run_cross_owner_hidden(
                runtime.service,
                corpus,
                generation.generation_sha256,
            )
            cross_owner_rejected = (
                cross_owner_view.status == "evidence-unavailable"
                and cross_owner_view.reason == "evidence-unavailable"
                and not cross_owner_view.questions
            )
            if not cross_owner_rejected:
                raise RuntimeError("Student cross-owner evidence was visible")
            expected_evidence = _expected_student_evidence(generation, corpus)
            result = evaluate_student_qualification(
                service=runtime.service,
                corpus=corpus,
                acceptance=acceptance,
                tenant_id=_TENANT_ID,
                generation_sha256=generation.generation_sha256,
                expected_evidence=expected_evidence,
                observe_warm_state=observe_provider,
                observe_admission_state=observe_admission,
            )
            database_state = _verify_student_database_state(
                restarted.dsn,
                corpus,
                generation.generation_sha256,
                result,
                cross_owner_view,
                profile,
                expected_evidence,
            )
        teardown = database.stop(timeout_seconds=15)
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
        or teardown is None
        or generation is None
        or database_state is None
    ):
        raise RuntimeError("Student qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic = dict(result.public_evidence)
    semantic.pop("evidenceSha256", None)
    semantic["workload"] = {
        "model": profile.expected_model,
        "maximumOutputTokens": _MAXIMUM_OUTPUT_TOKENS,
        "maximumSequences": profile.maximum_sequences,
        "gpuMemoryUtilization": "0.40",
        "requestTimeModelLaunchAbsent": True,
        "requestTimeModelSwapAbsent": True,
    }
    semantic["knowledge"] = {
        "generationRestartReadBackObserved": True,
        "crossOwnerEvidenceRejected": cross_owner_rejected,
        **database_state,
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
            "privacyScope": "private-student-qualification",
            "publicEvidence": receipt,
            "qualification": private_qualification,
        },
    )
    return receipt


def _initialize_student_knowledge(
    dsn: str,
    corpus: StudentQualificationCorpus,
    root: Path,
) -> CompiledKnowledgeGeneration:
    root.mkdir(mode=0o700)
    meetings = root / "meetings"
    permissions = root / "permissions"
    meetings.mkdir()
    permissions.mkdir()
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Student qualification\n",
        encoding="utf-8",
    )
    for case in corpus.cases:
        (meetings / f"{case.case_id}.md").write_text(
            _concept_document(case, corpus.corpus_sha256),
            encoding="utf-8",
        )
        (permissions / f"{case.case_id}.yml").write_text(
            _permission_document(case.case_id, case.owner_id),
            encoding="utf-8",
        )
    generation = compile_okf_bundle(
        root,
        tenant_id=_TENANT_ID,
        source_revision=corpus.corpus_sha256,
    )
    curator = AuthenticatedPrincipal(
        tenant_id=_TENANT_ID,
        subject_id=_CURATOR_ID,
        client_id="student-qualification",
        scopes=frozenset(),
        roles=frozenset({"knowledge.curator"}),
    )
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        install_knowledge_schema(connection)
        install_knowledge_tool_audit_schema(connection)
        install_student_result_audit_schema(connection)
        admission = admit_curated_knowledge_generation(
            connection,
            principal=curator,
            repository_revision=generation.source_revision,
            source_path="server/student-workload-fixtures.json",
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
            tenant_id=_TENANT_ID,
            generation_sha256=generation.generation_sha256,
            embedding_model_id="student-qualification",
            embedding_model_revision=corpus.corpus_sha256,
            embeddings={chunk.chunk_id: embedding for chunk in generation.chunks},
        )
        activate_complete_generation(
            connection,
            tenant_id=_TENANT_ID,
            generation_sha256=generation.generation_sha256,
        )
    return generation


def _expected_student_evidence(
    generation: CompiledKnowledgeGeneration,
    corpus: StudentQualificationCorpus,
) -> dict[str, tuple[StudentExpectedEvidence, ...]]:
    concepts = {concept.concept_id: concept for concept in generation.concepts}
    chunks_by_concept: dict[str, list[CompiledChunk]] = {}
    for chunk in generation.chunks:
        chunks_by_concept.setdefault(chunk.concept_id, []).append(chunk)
    expected: dict[str, tuple[StudentExpectedEvidence, ...]] = {}
    for case in corpus.cases:
        concept = concepts.get(case.concept_id)
        chunks = chunks_by_concept.get(case.concept_id, [])
        if concept is None or not 1 <= len(chunks) <= 8:
            raise RuntimeError("Student qualification compiled evidence differs")
        ordered = tuple(sorted(chunks, key=lambda item: (item.char_start, item.chunk_id)))
        if any(chunk.text not in case.body for chunk in ordered):
            raise RuntimeError("Student qualification compiled body differs")
        expected[case.case_id] = tuple(
            StudentExpectedEvidence(
                concept_id=case.concept_id,
                source_revision=generation.source_revision,
                content_sha256=concept.content_sha256,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                text=chunk.text,
            )
            for chunk in ordered
        )
    return expected


def _expected_evidence_read_audits(
    corpus: StudentQualificationCorpus,
    expected_evidence: dict[str, tuple[StudentExpectedEvidence, ...]],
) -> list[tuple[object, ...]]:
    if set(expected_evidence) != {case.case_id for case in corpus.cases}:
        raise RuntimeError("Student expected evidence audit identity differs")
    return [
        (
            case.owner_id,
            "conversation-evidence",
            "succeeded",
            len(expected_evidence[case.case_id]),
        )
        for case in corpus.cases
    ]


def _run_cross_owner_hidden(
    service: object,
    corpus: StudentQualificationCorpus,
    generation_sha256: str,
) -> StudentJobView:
    case = corpus.cases[0]
    principal = AuthenticatedPrincipal(
        tenant_id=_TENANT_ID,
        subject_id=_CROSS_OWNER_ID,
        client_id="student-qualification",
        scopes=frozenset({"knowledge.read"}),
    )
    create_questions = getattr(service, "create_questions", None)
    if not callable(create_questions):
        raise RuntimeError("Student qualification service contract differs")
    view = create_questions(
        StudentRequest(
            conversation_concept_id=case.concept_id,
            expected_generation_sha256=generation_sha256,
            topic=case.topic,
        ),
        principal=principal,
        cancellation=threading.Event(),
    )
    if not isinstance(view, StudentJobView):
        raise RuntimeError("Student cross-owner result type differs")
    return view


def _verify_student_database_state(
    dsn: str,
    corpus: StudentQualificationCorpus,
    generation_sha256: str,
    result: StudentQualificationResult,
    cross_owner_view: StudentJobView,
    profile: AgentVllmServiceProfile,
    expected_evidence: dict[str, tuple[StudentExpectedEvidence, ...]],
) -> dict[str, bool]:
    private_cases = result.private_evidence.get("cases")
    if not isinstance(private_cases, list) or len(private_cases) != len(corpus.cases):
        raise RuntimeError("Student private case evidence is incomplete")
    warm_state = result.private_evidence.get("warmState")
    warm_before = warm_state.get("before") if isinstance(warm_state, dict) else None
    provider_generation = (
        warm_before.get("processGeneration")
        if isinstance(warm_before, dict)
        else None
    )
    if (
        isinstance(provider_generation, bool)
        or not isinstance(provider_generation, int)
        or provider_generation < 1
    ):
        raise RuntimeError("Student private provider generation is invalid")
    expected_workflow_audits: list[tuple[object, ...]] = []
    expected_terminal_audits: list[tuple[object, ...]] = []
    outcome_by_status = {
        "complete": "succeeded",
        "cancelled": "cancelled",
        "evidence-unavailable": "unavailable",
        "failed": "failed",
    }
    private_by_owner: dict[str, dict[str, object]] = {}
    for item in private_cases:
        if not isinstance(item, dict):
            raise RuntimeError("Student private case evidence is invalid")
        owner = item.get("ownerId")
        status = item.get("status")
        reason = item.get("reason")
        request_id = item.get("requestId")
        evidence_sha256 = item.get("evidenceSha256")
        questions = item.get("questions")
        if (
            not isinstance(owner, str)
            or status not in outcome_by_status
            or (reason is not None and not isinstance(reason, str))
            or not isinstance(request_id, str)
            or _REQUEST_ID.fullmatch(request_id) is None
            or not isinstance(evidence_sha256, str)
            or _SHA256.fullmatch(evidence_sha256) is None
            or not isinstance(questions, list)
        ):
            raise RuntimeError("Student private case evidence is invalid")
        private_by_owner[owner] = item
    if set(private_by_owner) != {case.owner_id for case in corpus.cases}:
        raise RuntimeError("Student private case ownership differs")

    expected_evidence_audits = _expected_evidence_read_audits(
        corpus,
        expected_evidence,
    )
    for case in corpus.cases:
        item = private_by_owner[case.owner_id]
        request = StudentRequest(
            conversation_concept_id=case.concept_id,
            expected_generation_sha256=generation_sha256,
            topic=case.topic,
        )
        outcome = outcome_by_status[item["status"]]
        count = len(item["questions"])
        expected_terminal_audits.append(
            (case.owner_id, outcome, item["reason"], count)
        )
        expected_workflow_audits.append(
            (
                case.owner_id,
                item["requestId"],
                student_request_sha256(request),
                request.conversation_concept_id,
                student_work_identity_sha256(request, item["evidenceSha256"]),
                "learning-questions",
                "rapid-automation",
                "background-llm",
                provider_generation,
                profile.candidate_id,
                profile.expected_model,
                profile.model_revision,
                profile.runtime_id,
                profile.profile_sha256,
                profile.candidate_lock_sha256,
                generation_sha256,
                item["evidenceSha256"],
                True,
                True,
                outcome,
                item["reason"],
                count,
            )
        )
    expected_evidence_audits.append(
        (_CROSS_OWNER_ID, "conversation-evidence", "succeeded", 0)
    )
    cross_case = corpus.cases[0]
    cross_request = StudentRequest(
        conversation_concept_id=cross_case.concept_id,
        expected_generation_sha256=generation_sha256,
        topic=cross_case.topic,
    )
    if (
        _REQUEST_ID.fullmatch(cross_owner_view.request_id) is None
        or not isinstance(cross_owner_view.evidence_sha256, str)
        or _SHA256.fullmatch(cross_owner_view.evidence_sha256) is None
    ):
        raise RuntimeError("Student cross-owner audit identity is invalid")
    expected_terminal_audits.append(
        (_CROSS_OWNER_ID, "unavailable", "evidence-unavailable", 0)
    )
    expected_workflow_audits.append(
        (
            _CROSS_OWNER_ID,
            cross_owner_view.request_id,
            student_request_sha256(cross_request),
            cross_request.conversation_concept_id,
            student_work_identity_sha256(
                cross_request,
                cross_owner_view.evidence_sha256,
            ),
            "learning-questions",
            "rapid-automation",
            "background-llm",
            None,
            profile.candidate_id,
            profile.expected_model,
            profile.model_revision,
            profile.runtime_id,
            profile.profile_sha256,
            profile.candidate_lock_sha256,
            generation_sha256,
            cross_owner_view.evidence_sha256,
            True,
            True,
            "unavailable",
            "evidence-unavailable",
            0,
        )
    )
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        active = connection.execute(
            "SELECT generation_sha256 FROM yap_knowledge_active_builds WHERE tenant_id = %s",
            (_TENANT_ID,),
        ).fetchall()
        build_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_builds WHERE tenant_id = %s",
            (_TENANT_ID,),
        ).fetchone()
        admission_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_source_admissions WHERE tenant_id = %s",
            (_TENANT_ID,),
        ).fetchone()
        proposal_count = connection.execute(
            "SELECT count(*) FROM yap_knowledge_proposals WHERE tenant_id = %s",
            (_TENANT_ID,),
        ).fetchone()
        evidence_audits = connection.execute(
            """SELECT subject_id, operation, outcome, result_count
               FROM yap_knowledge_tool_audit
               WHERE tenant_id = %s AND agent_id = 'student'""",
            (_TENANT_ID,),
        ).fetchall()
        workflow_audits = connection.execute(
            """SELECT subject_id, request_id, request_sha256,
                      conversation_concept_id, work_sha256,
                      purpose, route, scheduling_class, provider_generation,
                      candidate_id, model, model_revision, runtime_id,
                      profile_sha256, candidate_lock_sha256, generation_sha256,
                      evidence_sha256,
                      permission_hash ~ '^[0-9a-f]{64}$',
                      authorization_hash ~ '^[0-9a-f]{64}$',
                      outcome, reason, result_count
               FROM yap_student_result_audit
               WHERE tenant_id = %s""",
            (_TENANT_ID,),
        ).fetchall()
    actual_terminal_audits = [
        (row[0], row[19], row[20], row[21]) for row in workflow_audits
    ]
    checks = {
        "activeGenerationUnchanged": active == [(generation_sha256,)],
        "singleGenerationRetained": build_count == (1,),
        "singleSourceAdmissionRetained": admission_count == (1,),
        "proposalWritesAbsent": proposal_count == (0,),
        "evidenceReadAuditExact": sorted(evidence_audits)
        == sorted(expected_evidence_audits),
        "terminalOutcomeAuditExact": sorted(actual_terminal_audits)
        == sorted(expected_terminal_audits),
        "workflowIdentityAuditExact": sorted(workflow_audits)
        == sorted(expected_workflow_audits),
    }
    if not all(checks.values()):
        raise RuntimeError("Student durable state differs after qualification")
    return checks


def _concept_document(case: StudentQualificationCase, source_revision: str) -> str:
    case_id = case.case_id
    title = case.title
    body = case.body
    return f"""---
type: Meeting
title: {title}
resource: yap://tenant/{_TENANT_ID}/meeting/{case_id}
timestamp: 2026-08-12T16:00:00Z
yap_schema: 1
provenance: {{source: student-public-synthetic, source_revision: {source_revision}}}
---
# {title}

{body}
"""


def _permission_document(case_id: str, owner_id: str) -> str:
    return f"""path_prefix: meetings/{case_id}
audience: {{users: [{{tenant_id: {_TENANT_ID}, subject_id: {owner_id}}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
"""


def _require_full_rapid_profile(
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
        maximum_sequences != 4
        or arguments.get("--gpu-memory-utilization") != "0.40"
        or arguments.get("--max-num-seqs") != "4"
        or arguments.get("--max-num-batched-tokens") != "8192"
    ):
        raise ValueError("Student qualification requires the full rapid profile")


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "student-acceptance.json",
        server / "student-workload-fixtures.json",
        server / "agent-reasoning-candidates.lock.json",
        server / "agent-service-profiles/rapid-automation.json",
        server / "runtime/knowledge/postgres-pgvector.lock.json",
        server / "pyproject.toml",
        server / "uv.lock",
        server / "src/yap_server/private_artifact.py",
        server / "src/yap_server/private_postgres_connection.py",
        server / "src/yap_server/auth/principal.py",
        server / "src/yap_server/agents/admission_client.py",
        server / "src/yap_server/agents/admission_protocol.py",
        server / "src/yap_server/agents/student.py",
        server / "src/yap_server/agents/student_model.py",
        server / "src/yap_server/agents/student_runtime.py",
        server / "src/yap_server/agents/student_result_audit.py",
        server / "src/yap_server/agents/student_service.py",
        server / "src/yap_server/evaluation/agent_admission_broker_observation.py",
        server / "src/yap_server/evaluation/agent_service_lifecycle_observation.py",
        server / "src/yap_server/evaluation/checked_candidate.py",
        server / "src/yap_server/evaluation/owned_postgres_knowledge_runtime.py",
        server / "src/yap_server/evaluation/private_json_evidence.py",
        server / "src/yap_server/evaluation/student_qualification.py",
        server / "src/yap_server/evaluation/student_qualification_gate.py",
        server / "src/yap_server/knowledge/cancellable_database_operation.py",
        server / "src/yap_server/knowledge/generation_ledger.py",
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
        server / "src/yap_server/knowledge/vllm_reasoning_client.py",
        server / "src/yap_server/pools/agent_vllm_service_profile.py",
        server / "tests/agents/test_student.py",
        server / "tests/agents/test_student_postgres.py",
        server / "tests/agents/test_student_runtime.py",
        server / "tests/evaluation/test_agent_admission_broker_observation.py",
        server / "tests/evaluation/test_student_qualification.py",
        server / "tests/evaluation/test_student_qualification_gate.py",
        server / "orchestrator/Cargo.toml",
        server / "orchestrator/Cargo.lock",
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
        raise ValueError("Student qualification candidate inputs are incomplete")
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
        raise ValueError("Student evidence destination must be new and outside the repository")
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Student evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError("Student evidence destination must be new and outside the repository")
    return requested


def _write_new_private_text(path: Path, value: str) -> None:
    if path.exists() or path.is_symlink() or not value or "\n" in value or "\r" in value:
        raise ValueError("Student private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Student qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Student on the already-warm full rapid route",
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--evidence-destination", type=Path, required=True)
    parser.add_argument("--admission-socket", type=Path, required=True)
    parser.add_argument("--rapid-state", type=Path, required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    receipt = run_student_qualification_gate(
        repository_root=options.repository_root,
        checked_head=options.checked_head,
        evidence_destination=options.evidence_destination,
        admission_socket_path=options.admission_socket,
        rapid_state_path=options.rapid_state,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True), flush=True)
    return 0 if receipt["outcome"] == "student-learning-questions-qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_student_qualification_gate"]
