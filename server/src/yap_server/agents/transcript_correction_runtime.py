from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yap_server.knowledge.vllm_reasoning_client import BoundedVllmJsonClient
from yap_server.pools.agent_vllm_service_profile import (
    AgentVllmServiceProfile,
    load_agent_vllm_service_profile,
)

from .admission_client import AgentAdmissionClient
from .admission_protocol import UnixAgentAdmissionTransport
from .transcript_correction_model import TranscriptCorrectionModel
from .transcript_correction_service import TranscriptCorrectionService
from .transcript_correction_terminology import (
    PersonalOrganizationTerminologyMemberships,
    PostgresTranscriptCorrectionTerminologyResolver,
    postgres_connection_factory_from_private_dsn,
)


TRANSCRIPT_CORRECTION_RUNTIME = "YAP_TRANSCRIPT_CORRECTION_RUNTIME"
TRANSCRIPT_CORRECTION_ADMISSION_SOCKET = (
    "YAP_TRANSCRIPT_CORRECTION_ADMISSION_SOCKET"
)
TRANSCRIPT_CORRECTION_PROFILE = "YAP_TRANSCRIPT_CORRECTION_PROFILE"
TRANSCRIPT_CORRECTION_CANDIDATE_LOCK = (
    "YAP_TRANSCRIPT_CORRECTION_CANDIDATE_LOCK"
)
TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE = (
    "YAP_TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE"
)

_WARM_QWEN = "warm_qwen"
_DISABLED = "disabled"
_RAPID_PROFILE_SHA256 = (
    "14712e6951802daaae323a3a7d69e78a8b3d5ac32ad52cbd0f546df327649da8"
)
_MODEL_TIMEOUT_SECONDS = 55
_MAXIMUM_RESPONSE_BYTES = 1_048_576
_MAXIMUM_OUTPUT_TOKENS = 512
_CONFIGURATION_PATHS = (
    TRANSCRIPT_CORRECTION_ADMISSION_SOCKET,
    TRANSCRIPT_CORRECTION_PROFILE,
    TRANSCRIPT_CORRECTION_CANDIDATE_LOCK,
    TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE,
)


@dataclass(slots=True)
class TranscriptCorrectionRuntime:
    service: TranscriptCorrectionService
    profile_id: str
    model: str
    profile_sha256: str
    candidate_lock_sha256: str
    maximum_output_tokens: int

    def close(self) -> None:
        self.service.close()


def build_transcript_correction_runtime(
    environ: Mapping[str, str],
    *,
    authenticated_team_mode: bool,
) -> TranscriptCorrectionRuntime | None:
    mode = environ.get(TRANSCRIPT_CORRECTION_RUNTIME)
    configured_paths = [name for name in _CONFIGURATION_PATHS if name in environ]
    if mode is None:
        if configured_paths:
            raise ValueError(
                "transcript correction configuration requires an explicit runtime mode"
            )
        return None
    if not isinstance(mode, str) or mode.strip() != mode or mode not in {
        _DISABLED,
        _WARM_QWEN,
    }:
        raise ValueError("transcript correction runtime mode is invalid")
    if mode == _DISABLED:
        if configured_paths:
            raise ValueError(
                "disabled transcript correction cannot include runtime paths"
            )
        return None
    if not authenticated_team_mode:
        raise ValueError(
            "transcript correction requires organization authentication"
        )

    socket_path = _absolute_path(
        environ,
        TRANSCRIPT_CORRECTION_ADMISSION_SOCKET,
    )
    profile_path = _absolute_path(environ, TRANSCRIPT_CORRECTION_PROFILE)
    candidate_lock_path = _absolute_path(
        environ,
        TRANSCRIPT_CORRECTION_CANDIDATE_LOCK,
    )
    knowledge_dsn_path = _absolute_path(
        environ,
        TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE,
    )
    profile = load_transcript_correction_service_profile(
        profile_path,
        candidate_lock_path,
    )

    admission = AgentAdmissionClient(UnixAgentAdmissionTransport(socket_path))
    transport = BoundedVllmJsonClient(
        endpoint=profile.endpoint,
        timeout_seconds=_MODEL_TIMEOUT_SECONDS,
        maximum_response_bytes=_MAXIMUM_RESPONSE_BYTES,
    )
    model = TranscriptCorrectionModel(
        transport=transport,
        model=profile.expected_model,
        maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
    )
    terminology = PostgresTranscriptCorrectionTerminologyResolver(
        connection_factory=postgres_connection_factory_from_private_dsn(
            knowledge_dsn_path
        ),
        memberships=PersonalOrganizationTerminologyMemberships(),
    )
    service = TranscriptCorrectionService(
        admission=admission,
        model=model,
        terminology=terminology,
    )
    return TranscriptCorrectionRuntime(
        service=service,
        profile_id=profile.profile_id,
        model=profile.expected_model,
        profile_sha256=profile.profile_sha256,
        candidate_lock_sha256=profile.candidate_lock_sha256,
        maximum_output_tokens=_MAXIMUM_OUTPUT_TOKENS,
    )


def load_transcript_correction_service_profile(
    profile_path: Path,
    candidate_lock_path: Path,
) -> AgentVllmServiceProfile:
    """Load the one qualified already-warm route Scribe is allowed to use."""

    profile = load_agent_vllm_service_profile(
        profile_path,
        candidate_lock_path,
        expected_profile_sha256=_RAPID_PROFILE_SHA256,
    )
    if profile.profile_id != "rapid-automation":
        raise ValueError("transcript correction requires the rapid automation route")
    return profile


def _absolute_path(environ: Mapping[str, str], variable: str) -> Path:
    value = environ.get(variable)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{variable} is required")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return path


__all__ = [
    "TRANSCRIPT_CORRECTION_ADMISSION_SOCKET",
    "TRANSCRIPT_CORRECTION_CANDIDATE_LOCK",
    "TRANSCRIPT_CORRECTION_KNOWLEDGE_DSN_FILE",
    "TRANSCRIPT_CORRECTION_PROFILE",
    "TRANSCRIPT_CORRECTION_RUNTIME",
    "TranscriptCorrectionRuntime",
    "build_transcript_correction_runtime",
    "load_transcript_correction_service_profile",
]
