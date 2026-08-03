"""Explicit startup configuration for the candidate Tiron meeting runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yap_server.config.runtime_environment import (
    TIRON_ECAPA_DIR_ENV,
    TIRON_MODEL_DIR_ENV,
    TIRON_PREPARATION_RECEIPT_ENV,
    TIRON_PREPARATION_RECEIPT_SHA256_ENV,
    TIRON_RUNTIME_LOCK_ENV,
    TIRON_WORKER_IMAGE_ENV,
)
from yap_server.evaluation.meeting_runtime_provenance import (
    verify_meeting_runtime_repository_files,
    verify_repository_source_directory,
)

from .contract import MEETING_TRANSCRIPTION_POOL_ID
from .result_revisions import MeetingResultAuthority, load_meeting_result_authority


@dataclass(frozen=True, slots=True)
class MeetingAsrCapabilityIdentity:
    """Capability-catalog identity derived from the verified Tiron lock."""

    pool_id: str
    model_id: str
    model_revision: str
    model_license: str
    model_source: str
    supported_languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeetingTranscriptionRuntimeConfiguration:
    """Verified files required to start the candidate meeting worker."""

    model_dir: Path
    speaker_encoder_dir: Path
    runtime_lock_path: Path
    authority: MeetingResultAuthority
    capability_identity: MeetingAsrCapabilityIdentity


def load_meeting_transcription_runtime_configuration(
    source: Mapping[str, str],
    server_root: Path,
) -> MeetingTranscriptionRuntimeConfiguration | None:
    """Load Tiron only when both candidate model roots are explicit."""

    model_value = source.get(TIRON_MODEL_DIR_ENV, "").strip()
    speaker_encoder_value = source.get(TIRON_ECAPA_DIR_ENV, "").strip()
    runtime_lock_value = source.get(TIRON_RUNTIME_LOCK_ENV, "").strip()
    worker_image_value = source.get(TIRON_WORKER_IMAGE_ENV, "").strip()
    preparation_receipt_value = source.get(
        TIRON_PREPARATION_RECEIPT_ENV,
        "",
    ).strip()
    preparation_receipt_sha256_value = source.get(
        TIRON_PREPARATION_RECEIPT_SHA256_ENV,
        "",
    ).strip()
    if not model_value and not speaker_encoder_value:
        if (
            runtime_lock_value
            or worker_image_value
            or preparation_receipt_value
            or preparation_receipt_sha256_value
        ):
            raise ValueError(
                f"{TIRON_MODEL_DIR_ENV} and {TIRON_ECAPA_DIR_ENV} are required "
                "when the Tiron runtime is configured"
            )
        return None
    if not model_value or not speaker_encoder_value:
        raise ValueError(
            f"{TIRON_MODEL_DIR_ENV} and {TIRON_ECAPA_DIR_ENV} must be set together"
        )

    root = server_root.resolve(strict=True)
    runtime_lock_path = Path(
        runtime_lock_value or root / "meeting-transcription-runtime.lock.json"
    ).resolve(strict=True)
    authority = load_meeting_result_authority(runtime_lock_path)
    verify_meeting_runtime_repository_files(
        authority.provenance,
        repository_root=root.parent,
    )
    model_dir = verify_repository_source_directory(
        authority.provenance.model,
        Path(model_value),
    )
    speaker_encoder_dir = verify_repository_source_directory(
        authority.provenance.speaker_encoder,
        Path(speaker_encoder_value),
    )
    model = authority.provenance.model
    return MeetingTranscriptionRuntimeConfiguration(
        model_dir=model_dir,
        speaker_encoder_dir=speaker_encoder_dir,
        runtime_lock_path=runtime_lock_path,
        authority=authority,
        capability_identity=MeetingAsrCapabilityIdentity(
            pool_id=MEETING_TRANSCRIPTION_POOL_ID,
            model_id=model.identifier,
            model_revision=model.revision,
            model_license=model.license_spdx,
            model_source=model.source,
            supported_languages=("en",),
        ),
    )
