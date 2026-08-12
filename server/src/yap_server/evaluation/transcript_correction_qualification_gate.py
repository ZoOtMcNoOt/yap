"""Run the exact checked Scribe quality and warm multi-user qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
from typing import Callable, Sequence

import psycopg

from yap_server.agents.transcript_correction_runtime import (
    TRANSCRIPT_CORRECTION_ADMISSION_SOCKET,
    TRANSCRIPT_CORRECTION_CANDIDATE_LOCK,
    TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE,
    TRANSCRIPT_CORRECTION_PROFILE,
    TRANSCRIPT_CORRECTION_RUNTIME,
    build_transcript_correction_runtime,
    load_transcript_correction_service_profile,
)
from yap_server.auth import PrincipalKey
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
from yap_server.knowledge.terminology_authorization import (
    TerminologyAuthorization,
)
from yap_server.knowledge.terminology_ledger import (
    append_terminology_record,
    install_terminology_schema,
)
from yap_server.knowledge.terminology_snapshot import TerminologyRecord

from .transcript_correction_corpus import (
    TranscriptCorrectionQualificationCorpus,
    load_private_transcript_correction_corpus,
)
from .transcript_correction_qualification import (
    TranscriptCorrectionQualificationResult,
    evaluate_transcript_correction_qualification,
    load_transcript_correction_acceptance,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
_TENANT_ID = "scribe-qualification"
_MAXIMUM_BROKER_BINARY_BYTES = 64 * 1024 * 1024
_MAXIMUM_BROKER_DOCUMENT_BYTES = 1024 * 1024
_BROKER_BINARY = "yap-agent-admission-broker"
_BROKER_ARGUMENTS = frozenset(
    {
        "--socket-path",
        "--candidate-lock",
        "--rapid-profile",
        "--rapid-profile-sha256",
        "--rapid-state-path",
        "--complex-profile",
        "--complex-profile-sha256",
        "--complex-state-path",
    }
)


def run_transcript_correction_qualification_gate(
    *,
    repository_root: Path,
    checked_head: str,
    corpus_path: Path,
    corpus_sha256: str,
    source_evidence_paths: Sequence[Path],
    evidence_destination: Path,
    admission_socket_path: Path,
    rapid_state_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Qualify one clean Scribe candidate without launching or swapping its model."""

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
    acceptance = load_transcript_correction_acceptance(
        root / "server/transcript-correction-acceptance.json"
    )
    corpus = load_private_transcript_correction_corpus(
        corpus_path,
        expected_sha256=corpus_sha256,
        repository_root=root,
        source_evidence_paths=source_evidence_paths,
    )
    profile_path = root / "server/agent-service-profiles/rapid-automation.json"
    candidate_lock_path = root / "server/agent-reasoning-candidates.lock.json"
    profile = load_transcript_correction_service_profile(
        profile_path,
        candidate_lock_path,
    )
    expected_broker_sha256 = _build_admission_broker(root, runner=runner)

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
    correction_runtime = None
    teardown: dict[str, bool] | None = None
    result: TranscriptCorrectionQualificationResult | None = None
    try:
        started = database.start(timeout_seconds=120)
        with tempfile.TemporaryDirectory(prefix="yap-scribe-qualification-") as value:
            private_runtime_root = Path(value)
            if os.name == "posix":
                private_runtime_root.chmod(0o700)
            dsn_path = private_runtime_root / "knowledge.dsn"
            _write_new_private_text(dsn_path, started.dsn)
            _initialize_terminology(started.dsn, corpus)
            correction_runtime = build_transcript_correction_runtime(
                {
                    TRANSCRIPT_CORRECTION_RUNTIME: "warm_qwen",
                    TRANSCRIPT_CORRECTION_ADMISSION_SOCKET: str(
                        admission_socket_path
                    ),
                    TRANSCRIPT_CORRECTION_PROFILE: str(profile_path),
                    TRANSCRIPT_CORRECTION_CANDIDATE_LOCK: str(
                        candidate_lock_path
                    ),
                    TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE: str(dsn_path),
                },
                authenticated_team_mode=True,
            )
            if correction_runtime is None:
                raise RuntimeError("Scribe qualification runtime is unavailable")
            result = evaluate_transcript_correction_qualification(
                service=correction_runtime.service,
                corpus=corpus,
                acceptance=acceptance,
                observe_warm_state=observe_provider,
                observe_admission_state=observe_admission,
            )
            _require_no_durable_job_bindings(started.dsn)
            correction_runtime.close()
            correction_runtime = None
        teardown = database.stop(timeout_seconds=15)
        started = None
    except BaseException as error:
        cleanup_error: BaseException | None = None
        if correction_runtime is not None:
            try:
                correction_runtime.close()
            except BaseException as close_error:
                cleanup_error = close_error
        if started is not None:
            try:
                database.contain_failed_run()
            except BaseException as database_error:
                cleanup_error = cleanup_error or database_error
        if cleanup_error is not None:
            raise cleanup_error from error
        raise

    if result is None or teardown is None:
        raise RuntimeError("Scribe qualification evidence is incomplete")
    candidate.verify_unchanged(runner=runner)
    semantic = dict(result.public_evidence)
    semantic.pop("evidenceSha256", None)
    semantic["database"] = {
        "runtimeLockSha256": database_lock.lock_sha256,
        "durableJobBindingsAbsent": True,
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
            "privacyScope": "private-transcript-correction-qualification",
            "publicEvidence": receipt,
            "qualification": private_qualification,
        },
    )
    return receipt


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
        raise ValueError("Scribe evidence destination must be new and outside the repository")
    existing = requested.parent
    while not existing.exists():
        if existing.is_symlink() or existing.parent == existing:
            raise ValueError(
                "Scribe evidence destination must be new and outside the repository"
            )
        existing = existing.parent
    if existing.is_symlink() or existing.resolve(strict=True) != existing:
        raise ValueError("Scribe evidence destination must be new and outside the repository")
    return requested


def observe_admission_broker(
    socket_path: Path,
    *,
    expected_binary_sha256: str,
    expected_candidate_lock_sha256: str,
    expected_rapid_profile_sha256: str,
    expected_rapid_state_path: Path,
) -> dict[str, object]:
    """Bind the owner-private socket to one exact running broker executable."""

    if (
        len(expected_binary_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_binary_sha256)
    ):
        raise ValueError("admission broker binary digest is invalid")
    requested = Path(os.path.abspath(socket_path))
    resolved = socket_path.resolve(strict=True)
    before = resolved.lstat()
    if (
        requested != resolved
        or not stat.S_ISSOCK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.geteuid()
        or not hasattr(socket, "SO_PEERCRED")
    ):
        raise ValueError("admission broker socket identity is invalid")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(resolved))
        credentials = client.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("3i"),
        )
    process_id, user_id, _group_id = struct.unpack("3i", credentials)
    after = resolved.lstat()
    if (
        process_id < 2
        or user_id != os.geteuid()
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
    ):
        raise ValueError("admission broker process identity is invalid")
    actual_binary_sha256 = _process_binary_sha256(process_id)
    if actual_binary_sha256 != expected_binary_sha256:
        raise ValueError("admission broker executable differs from the checked build")
    _validate_broker_command_line(
        process_id,
        socket_path=resolved,
        expected_candidate_lock_sha256=expected_candidate_lock_sha256,
        expected_rapid_profile_sha256=expected_rapid_profile_sha256,
        expected_rapid_state_path=expected_rapid_state_path,
    )
    return {
        "processId": process_id,
        "processStartTicks": _process_start_ticks(process_id),
        "binarySha256": actual_binary_sha256,
        "socketDevice": int(after.st_dev),
        "socketInode": int(after.st_ino),
    }


def _candidate_input_paths(repository_root: Path) -> tuple[Path, ...]:
    server = repository_root / "server"
    fixed = (
        server / "transcript-correction-acceptance.json",
        server / "transcript-correction-source-evidence.lock.json",
        server / "fleurs-cohere-comparator.plan.json",
        server / "fleurs-en-us-cohere-comparator.plan.json",
        server / "fleurs-en-us-test.lock.json",
        server / "fleurs-es-419-test.lock.json",
        server / "model-pools.lock.json",
        server / "agent-reasoning-candidates.lock.json",
        server / "agent-service-profiles/rapid-automation.json",
        server / "runtime/knowledge/postgres-pgvector.lock.json",
        server / "pyproject.toml",
        server / "uv.lock",
        server / "src/yap_server/agents/admission_client.py",
        server / "src/yap_server/agents/admission_protocol.py",
        server / "src/yap_server/agents/transcript_correction.py",
        server / "src/yap_server/agents/transcript_correction_masking.py",
        server / "src/yap_server/agents/transcript_correction_model.py",
        server / "src/yap_server/agents/transcript_correction_runtime.py",
        server / "src/yap_server/agents/transcript_correction_service.py",
        server / "src/yap_server/agents/transcript_correction_terminology.py",
        server / "src/yap_server/evaluation/agent_service_lifecycle_observation.py",
        server / "src/yap_server/evaluation/checked_candidate.py",
        server / "src/yap_server/evaluation/private_json_evidence.py",
        server / "src/yap_server/evaluation/fleurs_cohere_comparator.py",
        server / "src/yap_server/evaluation/fleurs_cohere_result.py",
        server / "src/yap_server/evaluation/fleurs_comparator_plan.py",
        server / "src/yap_server/evaluation/fleurs_corpus.py",
        server / "src/yap_server/evaluation/transcript_correction_corpus.py",
        server / "src/yap_server/evaluation/transcript_correction_source_evidence.py",
        server / "src/yap_server/evaluation/transcript_correction_qualification.py",
        server / "src/yap_server/evaluation/transcript_correction_qualification_gate.py",
        server / "src/yap_server/evaluation/transcript_scoring.py",
        server / "src/yap_server/knowledge/terminology_authorization.py",
        server / "src/yap_server/knowledge/terminology_ledger.py",
        server / "src/yap_server/knowledge/terminology_projections.py",
        server / "src/yap_server/knowledge/terminology_snapshot.py",
        server / "src/yap_server/knowledge/vllm_reasoning_client.py",
        server / "tests/agents/test_agent_admission_client.py",
        server / "tests/agents/test_transcript_correction.py",
        server / "tests/agents/test_transcript_correction_model.py",
        server / "tests/agents/test_transcript_correction_runtime.py",
        server / "tests/agents/test_transcript_correction_service.py",
        server / "tests/agents/test_transcript_correction_terminology.py",
        server / "tests/evaluation/test_transcript_correction_qualification.py",
        server / "tests/evaluation/test_transcript_correction_qualification_gate.py",
        server / "tests/evaluation/test_transcript_correction_source_evidence.py",
        server / "tests/evaluation/test_fleurs_cohere_comparator.py",
        server / "tests/evaluation/test_fleurs_corpus.py",
        server / "tests/knowledge/test_terminology_ledger.py",
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
        raise ValueError("Scribe qualification candidate inputs are incomplete")
    return paths


def _build_admission_broker(repository_root: Path, *, runner: Runner) -> str:
    cargo = shutil.which("cargo")
    if cargo is None:
        cargo = str(Path.home() / ".cargo/bin/cargo")
    completed = runner(
        [cargo, "build", "--locked", "--release", "--bin", _BROKER_BINARY],
        cwd=repository_root / "server/orchestrator",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=1_800,
    )
    if completed.returncode != 0:
        raise RuntimeError("admission broker checked build failed")
    binary = (
        repository_root
        / "server/orchestrator/target/release"
        / _BROKER_BINARY
    )
    if binary.is_symlink() or not binary.is_file():
        raise RuntimeError("admission broker checked build is unavailable")
    return hashlib.sha256(binary.read_bytes()).hexdigest()


def _initialize_terminology(
    dsn: str,
    corpus: TranscriptCorrectionQualificationCorpus,
) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        install_terminology_schema(connection)
        for term in corpus.terminology:
            principal = PrincipalKey(_TENANT_ID, term.owner_id)
            append_terminology_record(
                connection,
                TerminologyRecord(
                    record_id=term.record_id,
                    tenant_id=_TENANT_ID,
                    scope="personal",
                    owner_id=term.owner_id,
                    locale=term.locale,
                    canonical_form=term.canonical_form,
                    variants=term.variants,
                    sensitivity="internal",
                    version=1,
                    deleted=False,
                    audit_revision=f"scribe-{term.record_id}",
                    changed_at="2026-08-11T00:00:00+00:00",
                ),
                authorization=TerminologyAuthorization(
                    principal=principal,
                    team_ids=(),
                    may_manage_organization=False,
                ),
            )


def _require_no_durable_job_bindings(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        row = connection.execute(
            "SELECT count(*) FROM yap_terminology_job_bindings"
        ).fetchone()
    if row is None or tuple(row) != (0,):
        raise RuntimeError("Scribe qualification created durable job bindings")


def _write_new_private_text(path: Path, value: str) -> None:
    if path.exists() or path.is_symlink() or not value or "\n" in value or "\r" in value:
        raise ValueError("Scribe private runtime credential is invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def _process_binary_sha256(process_id: int) -> str:
    descriptor = os.open(Path(f"/proc/{process_id}/exe"), os.O_RDONLY)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not (
            1 <= metadata.st_size <= _MAXIMUM_BROKER_BINARY_BYTES
        ):
            raise ValueError("admission broker executable identity is invalid")
        digest = hashlib.sha256()
        remaining = _MAXIMUM_BROKER_BINARY_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise ValueError("admission broker executable exceeds its byte bound")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _process_start_ticks(process_id: int) -> int:
    value = Path(f"/proc/{process_id}/stat").read_text(encoding="ascii")
    end = value.rfind(")")
    fields = value[end + 2 :].split() if end > 0 else []
    if len(fields) <= 19 or not fields[19].isdigit() or int(fields[19]) < 1:
        raise ValueError("admission broker process start identity is invalid")
    return int(fields[19])


def _validate_broker_command_line(
    process_id: int,
    *,
    socket_path: Path,
    expected_candidate_lock_sha256: str,
    expected_rapid_profile_sha256: str,
    expected_rapid_state_path: Path,
) -> None:
    try:
        raw = Path(f"/proc/{process_id}/cmdline").read_bytes()
        values = [part.decode("utf-8") for part in raw.split(b"\0") if part]
    except (OSError, UnicodeError) as error:
        raise ValueError("admission broker command line is unavailable") from error
    if (
        not values
        or len(raw) > 16 * 1024
        or len(values[1:]) != len(_BROKER_ARGUMENTS) * 2
    ):
        raise ValueError("admission broker command line differs")
    arguments: dict[str, str] = {}
    for index in range(1, len(values), 2):
        name = values[index]
        if name not in _BROKER_ARGUMENTS or name in arguments:
            raise ValueError("admission broker command line differs")
        arguments[name] = values[index + 1]
    if set(arguments) != _BROKER_ARGUMENTS:
        raise ValueError("admission broker command line differs")
    if (
        _resolved_path(arguments["--socket-path"]) != socket_path
        or _resolved_path(arguments["--rapid-state-path"])
        != expected_rapid_state_path.resolve(strict=True)
        or _sha256_regular_file(Path(arguments["--candidate-lock"]))
        != expected_candidate_lock_sha256
        or _sha256_regular_file(Path(arguments["--rapid-profile"]))
        != expected_rapid_profile_sha256
        or arguments["--rapid-profile-sha256"]
        != expected_rapid_profile_sha256
    ):
        raise ValueError("admission broker checked configuration differs")
    complex_profile_sha256 = _sha256_regular_file(
        Path(arguments["--complex-profile"])
    )
    if arguments["--complex-profile-sha256"] != complex_profile_sha256:
        raise ValueError("admission broker complex profile identity differs")
    _resolved_path(arguments["--complex-state-path"])


def _resolved_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("admission broker configured path is invalid")
    return path.resolve(strict=True)


def _sha256_regular_file(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("admission broker configured file is invalid")
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not 1 <= metadata.st_size <= _MAXIMUM_BROKER_DOCUMENT_BYTES
    ):
        raise ValueError("admission broker configured file is invalid")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_private_arm64_host() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise RuntimeError("Scribe qualification requires the private ARM64 host")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify Scribe on the already-warm rapid route",
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checked-head", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--corpus-sha256", required=True)
    parser.add_argument(
        "--source-evidence",
        action="append",
        type=Path,
        required=True,
    )
    parser.add_argument("--evidence-destination", type=Path, required=True)
    parser.add_argument("--admission-socket", type=Path, required=True)
    parser.add_argument("--rapid-state", type=Path, required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    receipt = run_transcript_correction_qualification_gate(
        repository_root=options.repository_root,
        checked_head=options.checked_head,
        corpus_path=options.corpus,
        corpus_sha256=options.corpus_sha256,
        source_evidence_paths=tuple(options.source_evidence),
        evidence_destination=options.evidence_destination,
        admission_socket_path=options.admission_socket,
        rapid_state_path=options.rapid_state,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True), flush=True)
    return 0 if receipt["outcome"] == "scribe-transcript-correction-qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "main",
    "observe_admission_broker",
    "run_transcript_correction_qualification_gate",
]
