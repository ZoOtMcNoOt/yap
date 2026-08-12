from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yap_server.knowledge.vllm_reasoning_client import BoundedVllmJsonClient
from yap_server.pools.agent_vllm_service_profile import (
    AgentVllmServiceProfile,
    load_rapid_agent_vllm_service_profile,
)
from yap_server.private_postgres_connection import (
    private_postgres_connection_factory,
)

from .admission_client import AgentAdmissionClient
from .admission_protocol import UnixAgentAdmissionTransport
from .student import PostgresStudentEvidenceReader
from .student_model import StudentQuestionModel
from .student_result_audit import (
    PostgresStudentResultAuditor,
    StudentRuntimeAuditIdentity,
)
from .student_service import StudentService


STUDENT_RUNTIME = "YAP_STUDENT_RUNTIME"
STUDENT_ADMISSION_SOCKET = "YAP_STUDENT_ADMISSION_SOCKET"
STUDENT_PROFILE = "YAP_STUDENT_PROFILE"
STUDENT_CANDIDATE_LOCK = "YAP_STUDENT_CANDIDATE_LOCK"
STUDENT_KNOWLEDGE_DSN_FILE = "YAP_STUDENT_KNOWLEDGE_DSN_FILE"

_WARM_QWEN = "warm_qwen"
_DISABLED = "disabled"
_MODEL_TIMEOUT_SECONDS = 55
_MAXIMUM_RESPONSE_BYTES = 1_048_576
_MAXIMUM_OUTPUT_TOKENS = 512
_CONFIGURATION_PATHS = (
    STUDENT_ADMISSION_SOCKET,
    STUDENT_PROFILE,
    STUDENT_CANDIDATE_LOCK,
    STUDENT_KNOWLEDGE_DSN_FILE,
)


@dataclass(frozen=True, slots=True)
class StudentRuntime:
    service: StudentService
    profile_id: str
    model: str
    profile_sha256: str
    candidate_lock_sha256: str
    maximum_output_tokens: int


def build_student_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> StudentRuntime | None:
    mode = environ.get(STUDENT_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError(
                "student configuration requires an explicit runtime mode"
            )
        return None
    if not isinstance(mode, str) or mode.strip() != mode or mode not in {
        _DISABLED,
        _WARM_QWEN,
    }:
        raise ValueError("student runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError("disabled student cannot include runtime paths")
        return None
    if not authenticated_team_mode:
        raise ValueError("student requires organization authentication")

    socket_path = _absolute_path(environ, STUDENT_ADMISSION_SOCKET)
    profile_path = _absolute_path(environ, STUDENT_PROFILE)
    candidate_lock_path = _absolute_path(environ, STUDENT_CANDIDATE_LOCK)
    knowledge_dsn_path = _absolute_path(environ, STUDENT_KNOWLEDGE_DSN_FILE)
    profile = load_student_service_profile(profile_path, candidate_lock_path)

    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(socket_path))
    transport = BoundedVllmJsonClient(
        endpoint=profile.endpoint,
        timeout_seconds=_MODEL_TIMEOUT_SECONDS,
        maximum_response_bytes=_MAXIMUM_RESPONSE_BYTES,
    )
    connection_factory = private_postgres_connection_factory(knowledge_dsn_path)
    service = StudentService(
        admission=admission,
        evidence_reader=PostgresStudentEvidenceReader(connection_factory),
        question_generator=StudentQuestionModel(
            transport=transport,
            model=profile.expected_model,
            maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        ),
        result_auditor=PostgresStudentResultAuditor(
            connection_factory,
            StudentRuntimeAuditIdentity(
                candidate_id=profile.candidate_id,
                model=profile.expected_model,
                model_revision=profile.model_revision,
                runtime_id=profile.runtime_id,
                profile_sha256=profile.profile_sha256,
                candidate_lock_sha256=profile.candidate_lock_sha256,
            ),
        ),
    )
    return StudentRuntime(
        service=service,
        profile_id=profile.profile_id,
        model=profile.expected_model,
        profile_sha256=profile.profile_sha256,
        candidate_lock_sha256=profile.candidate_lock_sha256,
        maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
    )


def load_student_service_profile(
    profile_path: Path,
    candidate_lock_path: Path,
) -> AgentVllmServiceProfile:
    """Load the one qualified already-warm route Student may use."""

    return load_rapid_agent_vllm_service_profile(
        profile_path,
        candidate_lock_path,
    )


def _absolute_path(environ: Mapping[str, str], variable: str) -> Path:
    value = environ.get(variable)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{variable} is required")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return path


__all__ = [
    "STUDENT_ADMISSION_SOCKET",
    "STUDENT_CANDIDATE_LOCK",
    "STUDENT_KNOWLEDGE_DSN_FILE",
    "STUDENT_PROFILE",
    "STUDENT_RUNTIME",
    "StudentRuntime",
    "build_student_runtime",
    "load_student_service_profile",
]
