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
from .curator import PostgresCuratorEvidenceReader
from .curator_model import MAXIMUM_CURATOR_INPUT_TOKENS, CuratorProposalModel
from .curator_publisher import PostgresCuratorPublisher
from .curator_result_audit import (
    CuratorRuntimeAuditIdentity,
    PostgresCuratorResultAuditor,
)
from .curator_service import CuratorService


CURATOR_RUNTIME = "YAP_CURATOR_RUNTIME"
CURATOR_ADMISSION_SOCKET = "YAP_CURATOR_ADMISSION_SOCKET"
CURATOR_PROFILE = "YAP_CURATOR_PROFILE"
CURATOR_CANDIDATE_LOCK = "YAP_CURATOR_CANDIDATE_LOCK"
CURATOR_KNOWLEDGE_DSN_FILE = "YAP_CURATOR_KNOWLEDGE_DSN_FILE"

_WARM_GEMMA = "warm_gemma"
_DISABLED = "disabled"
_MODEL_TIMEOUT_SECONDS = 55
_MAXIMUM_RESPONSE_BYTES = 1_048_576
_MAXIMUM_OUTPUT_TOKENS = 512
_CONFIGURATION_PATHS = (
    CURATOR_ADMISSION_SOCKET,
    CURATOR_PROFILE,
    CURATOR_CANDIDATE_LOCK,
    CURATOR_KNOWLEDGE_DSN_FILE,
)


@dataclass(frozen=True, slots=True)
class CuratorRuntime:
    service: CuratorService
    profile_id: str
    model: str
    profile_sha256: str
    candidate_lock_sha256: str
    maximum_output_tokens: int
    maximum_input_tokens: int


def build_curator_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> CuratorRuntime | None:
    mode = environ.get(CURATOR_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError(
                "curator configuration requires an explicit runtime mode"
            )
        return None
    if not isinstance(mode, str) or mode.strip() != mode or mode not in {
        _DISABLED,
        _WARM_GEMMA,
    }:
        raise ValueError("curator runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError("disabled curator cannot include runtime paths")
        return None
    if not authenticated_team_mode:
        raise ValueError("curator requires organization authentication")

    socket_path = _absolute_path(environ, CURATOR_ADMISSION_SOCKET)
    profile_path = _absolute_path(environ, CURATOR_PROFILE)
    candidate_lock_path = _absolute_path(environ, CURATOR_CANDIDATE_LOCK)
    knowledge_dsn_path = _absolute_path(environ, CURATOR_KNOWLEDGE_DSN_FILE)
    profile = load_curator_service_profile(profile_path, candidate_lock_path)

    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(socket_path))
    transport = BoundedVllmJsonClient(
        endpoint=profile.endpoint,
        timeout_seconds=_MODEL_TIMEOUT_SECONDS,
        maximum_response_bytes=_MAXIMUM_RESPONSE_BYTES,
    )
    connection_factory = private_postgres_connection_factory(knowledge_dsn_path)
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
    service = CuratorService(
        admission=admission,
        evidence_reader=PostgresCuratorEvidenceReader(connection_factory),
        reviewer=CuratorProposalModel(
            transport=transport,
            model=profile.expected_model,
            maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        ),
        publisher=PostgresCuratorPublisher(connection_factory, auditor),
        result_auditor=auditor,
    )
    return CuratorRuntime(
        service=service,
        profile_id=profile.profile_id,
        model=profile.expected_model,
        profile_sha256=profile.profile_sha256,
        candidate_lock_sha256=profile.candidate_lock_sha256,
        maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
        maximum_input_tokens=MAXIMUM_CURATOR_INPUT_TOKENS,
    )


def load_curator_service_profile(
    profile_path: Path,
    candidate_lock_path: Path,
) -> AgentVllmServiceProfile:
    """Load the one qualified already-warm route Curator may use."""

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
    "CURATOR_ADMISSION_SOCKET",
    "CURATOR_CANDIDATE_LOCK",
    "CURATOR_KNOWLEDGE_DSN_FILE",
    "CURATOR_PROFILE",
    "CURATOR_RUNTIME",
    "CuratorRuntime",
    "build_curator_runtime",
    "load_curator_service_profile",
]
