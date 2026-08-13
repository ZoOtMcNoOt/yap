from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yap_server.knowledge.vllm_reasoning_client import BoundedVllmJsonClient
from yap_server.pools.agent_vllm_service_profile import (
    AgentVllmServiceProfile,
    load_complex_agent_vllm_service_profile,
)
from yap_server.private_postgres_connection import (
    private_postgres_connection_factory,
)

from .admission_client import AgentAdmissionClient
from .admission_protocol import UnixAgentAdmissionTransport
from .auditor import PostgresAuditorEvidenceReader
from .auditor_model import (
    MAXIMUM_AUDITOR_INPUT_TOKENS,
    AuditorEvidenceModel,
)
from .auditor_result_audit import (
    AuditorRuntimeAuditIdentity,
    PostgresAuditorResultAuditor,
)
from .auditor_service import AuditorAdmission, AuditorService


AUDITOR_RUNTIME = "YAP_AUDITOR_RUNTIME"
AUDITOR_ADMISSION_SOCKET = "YAP_AUDITOR_ADMISSION_SOCKET"
AUDITOR_PROFILE = "YAP_AUDITOR_PROFILE"
AUDITOR_CANDIDATE_LOCK = "YAP_AUDITOR_CANDIDATE_LOCK"
AUDITOR_KNOWLEDGE_DSN_FILE = "YAP_AUDITOR_KNOWLEDGE_DSN_FILE"

_WARM_GEMMA = "warm_gemma"
_DISABLED = "disabled"
_MODEL_TIMEOUT_SECONDS = 55
_MAXIMUM_RESPONSE_BYTES = 1_048_576
_MAXIMUM_OUTPUT_TOKENS = 512
_CONFIGURATION_PATHS = (
    AUDITOR_ADMISSION_SOCKET,
    AUDITOR_PROFILE,
    AUDITOR_CANDIDATE_LOCK,
    AUDITOR_KNOWLEDGE_DSN_FILE,
)


@dataclass(frozen=True, slots=True)
class AuditorRuntime:
    service: AuditorService
    profile_id: str
    model: str
    profile_sha256: str
    candidate_lock_sha256: str
    maximum_output_tokens: int
    maximum_input_tokens: int


def build_auditor_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
    admission: AuditorAdmission | None = None,
) -> AuditorRuntime | None:
    mode = environ.get(AUDITOR_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError("auditor configuration requires an explicit runtime mode")
        return None
    if (
        not isinstance(mode, str)
        or mode.strip() != mode
        or mode not in {_DISABLED, _WARM_GEMMA}
    ):
        raise ValueError("auditor runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError("disabled auditor cannot include runtime paths")
        return None
    if not authenticated_team_mode:
        raise ValueError("auditor requires organization authentication")

    socket_path = _absolute_path(environ, AUDITOR_ADMISSION_SOCKET)
    profile_path = _absolute_path(environ, AUDITOR_PROFILE)
    candidate_lock_path = _absolute_path(environ, AUDITOR_CANDIDATE_LOCK)
    knowledge_dsn_path = _absolute_path(environ, AUDITOR_KNOWLEDGE_DSN_FILE)
    profile = load_auditor_service_profile(profile_path, candidate_lock_path)

    resolved_admission = admission
    if resolved_admission is None:
        resolved_admission = AgentAdmissionClient(
            UnixAgentAdmissionTransport(socket_path)
        )
    transport = BoundedVllmJsonClient(
        endpoint=profile.endpoint,
        timeout_seconds=_MODEL_TIMEOUT_SECONDS,
        maximum_response_bytes=_MAXIMUM_RESPONSE_BYTES,
    )
    connection_factory = private_postgres_connection_factory(knowledge_dsn_path)
    result_auditor = PostgresAuditorResultAuditor(
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
    service = AuditorService(
        admission=resolved_admission,
        evidence_reader=PostgresAuditorEvidenceReader(connection_factory),
        model=AuditorEvidenceModel(
            transport=transport,
            model=profile.expected_model,
            maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        ),
        result_auditor=result_auditor,
    )
    return AuditorRuntime(
        service=service,
        profile_id=profile.profile_id,
        model=profile.expected_model,
        profile_sha256=profile.profile_sha256,
        candidate_lock_sha256=profile.candidate_lock_sha256,
        maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        maximum_input_tokens=MAXIMUM_AUDITOR_INPUT_TOKENS,
    )


def load_auditor_service_profile(
    profile_path: Path,
    candidate_lock_path: Path,
) -> AgentVllmServiceProfile:
    """Load the qualified already-warm complex route for Auditor."""

    return load_complex_agent_vllm_service_profile(
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
    "AUDITOR_ADMISSION_SOCKET",
    "AUDITOR_CANDIDATE_LOCK",
    "AUDITOR_KNOWLEDGE_DSN_FILE",
    "AUDITOR_PROFILE",
    "AUDITOR_RUNTIME",
    "AuditorRuntime",
    "build_auditor_runtime",
    "load_auditor_service_profile",
]
