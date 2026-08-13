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
from .analyst import PostgresAnalystEvidenceVerifier
from .analyst_model import MAXIMUM_ANALYST_INPUT_TOKENS, AnalystEvidenceModel
from .analyst_result_audit import (
    AnalystRuntimeAuditIdentity,
    PostgresAnalystResultAuditor,
)
from .analyst_service import AnalystService
from .librarian import PostgresLibrarianEvidenceReader
from .librarian_result_audit import PostgresLibrarianResultAuditor
from .librarian_service import LibrarianService


ANALYST_RUNTIME = "YAP_ANALYST_RUNTIME"
ANALYST_ADMISSION_SOCKET = "YAP_ANALYST_ADMISSION_SOCKET"
ANALYST_PROFILE = "YAP_ANALYST_PROFILE"
ANALYST_CANDIDATE_LOCK = "YAP_ANALYST_CANDIDATE_LOCK"
ANALYST_KNOWLEDGE_DSN_FILE = "YAP_ANALYST_KNOWLEDGE_DSN_FILE"

_WARM_GEMMA = "warm_gemma"
_DISABLED = "disabled"
_MODEL_TIMEOUT_SECONDS = 55
_MAXIMUM_RESPONSE_BYTES = 1_048_576
_MAXIMUM_OUTPUT_TOKENS = 512
_CONFIGURATION_PATHS = (
    ANALYST_ADMISSION_SOCKET,
    ANALYST_PROFILE,
    ANALYST_CANDIDATE_LOCK,
    ANALYST_KNOWLEDGE_DSN_FILE,
)


@dataclass(frozen=True, slots=True)
class AnalystRuntime:
    service: AnalystService
    profile_id: str
    model: str
    profile_sha256: str
    candidate_lock_sha256: str
    maximum_output_tokens: int
    maximum_input_tokens: int


def build_analyst_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> AnalystRuntime | None:
    mode = environ.get(ANALYST_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError("analyst configuration requires an explicit runtime mode")
        return None
    if (
        not isinstance(mode, str)
        or mode.strip() != mode
        or mode not in {_DISABLED, _WARM_GEMMA}
    ):
        raise ValueError("analyst runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError("disabled analyst cannot include runtime paths")
        return None
    if not authenticated_team_mode:
        raise ValueError("analyst requires organization authentication")

    socket_path = _absolute_path(environ, ANALYST_ADMISSION_SOCKET)
    profile_path = _absolute_path(environ, ANALYST_PROFILE)
    candidate_lock_path = _absolute_path(environ, ANALYST_CANDIDATE_LOCK)
    knowledge_dsn_path = _absolute_path(environ, ANALYST_KNOWLEDGE_DSN_FILE)
    profile = load_analyst_service_profile(profile_path, candidate_lock_path)

    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(socket_path))
    transport = BoundedVllmJsonClient(
        endpoint=profile.endpoint,
        timeout_seconds=_MODEL_TIMEOUT_SECONDS,
        maximum_response_bytes=_MAXIMUM_RESPONSE_BYTES,
    )
    connection_factory = private_postgres_connection_factory(knowledge_dsn_path)
    librarian = LibrarianService(
        admission=admission,
        evidence_reader=PostgresLibrarianEvidenceReader(connection_factory),
        result_auditor=PostgresLibrarianResultAuditor(connection_factory),
    )
    evidence_verifier = PostgresAnalystEvidenceVerifier(connection_factory)
    result_auditor = PostgresAnalystResultAuditor(
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
    service = AnalystService(
        admission=admission,
        librarian=librarian,
        evidence_verifier=evidence_verifier,
        model=AnalystEvidenceModel(
            transport=transport,
            model=profile.expected_model,
            maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        ),
        result_auditor=result_auditor,
    )
    return AnalystRuntime(
        service=service,
        profile_id=profile.profile_id,
        model=profile.expected_model,
        profile_sha256=profile.profile_sha256,
        candidate_lock_sha256=profile.candidate_lock_sha256,
        maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        maximum_input_tokens=MAXIMUM_ANALYST_INPUT_TOKENS,
    )


def load_analyst_service_profile(
    profile_path: Path,
    candidate_lock_path: Path,
) -> AgentVllmServiceProfile:
    """Load the one qualified already-warm route Analyst may use."""

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
    "ANALYST_ADMISSION_SOCKET",
    "ANALYST_CANDIDATE_LOCK",
    "ANALYST_KNOWLEDGE_DSN_FILE",
    "ANALYST_PROFILE",
    "ANALYST_RUNTIME",
    "AnalystRuntime",
    "build_analyst_runtime",
    "load_analyst_service_profile",
]
