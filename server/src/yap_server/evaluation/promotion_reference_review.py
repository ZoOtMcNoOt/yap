"""Bind a human transcript-review receipt to one promotion case and model set."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from yap_server.evaluation.transcript_reference_review import (
    TranscriptReferenceReviewReceipt,
)


ModelIdentity = tuple[str, str]


def validate_promotion_reference_review(
    receipt: TranscriptReferenceReviewReceipt,
    *,
    case_id: str,
    corpus_id: str,
    corpus_release: str,
    corpus_split: str,
    source_item_id: str,
    source_uri: str,
    suite_ids: Sequence[str],
    condition_labels: Sequence[str],
    audio_sha256: str,
    audio_byte_length: int,
    decoded_pcm_sha256: str,
    duration_samples: int,
    sample_rate_hz: int,
    channels: int,
    audio_codec: str,
    reference_sha256: str,
    evaluation_policy_sha256: str,
    language_bcp47: str,
    reference_tier: str,
    reference_revision: str,
    speaker_count: int,
    timing_kind: str,
    recorded_at: datetime | None,
    retrieved_at: datetime,
    license_id: str,
    license_text_sha256: str,
    audio_rights_decision: str,
    reference_rights_decision: str,
    commercial_use: str,
    redistribution: str,
    reidentification_prohibited: bool,
    known_defect_codes: Sequence[str],
    candidate_models: Mapping[ModelIdentity, tuple[str, str]],
    exposure_statuses: Mapping[ModelIdentity, str],
) -> None:
    """Require one independently reviewed reference for every promotion case."""

    if not isinstance(receipt, TranscriptReferenceReviewReceipt):
        raise ValueError("independent promotion requires a human review receipt")
    if receipt.disposition != "pass":
        raise ValueError(
            "independent promotion requires a passing human review receipt"
        )
    if (
        receipt.case_id != case_id
        or receipt.corpus_id != corpus_id
        or receipt.corpus_release != corpus_release
        or receipt.corpus_split != corpus_split
        or receipt.source_item_id != source_item_id
        or receipt.corpus_source_uri != source_uri
        or receipt.suite_ids != tuple(suite_ids)
        or receipt.condition_labels != tuple(condition_labels)
        or receipt.audio_sha256 != audio_sha256
        or receipt.audio_byte_length != audio_byte_length
        or receipt.decoded_pcm_sha256 != decoded_pcm_sha256
        or receipt.duration_samples != duration_samples
        or receipt.sample_rate_hz != sample_rate_hz
        or receipt.channels != channels
        or receipt.audio_codec != audio_codec
        or receipt.reference_sha256 != reference_sha256
        or receipt.evaluation_policy_sha256 != evaluation_policy_sha256
        or receipt.language_bcp47 != language_bcp47
        or receipt.reference_tier != reference_tier
        or receipt.reference_revision != reference_revision
        or receipt.speaker_count != speaker_count
        or receipt.timing_kind != timing_kind
        or receipt.recorded_at_utc != recorded_at
        or receipt.retrieved_at_utc != retrieved_at
    ):
        raise ValueError("human review receipt does not match the promotion case")

    reviewed_rights = receipt.rights
    if (
        reviewed_rights.license_id != license_id
        or reviewed_rights.license_text_sha256 != license_text_sha256
        or reviewed_rights.audio_decision != audio_rights_decision
        or reviewed_rights.reference_decision != reference_rights_decision
        or reviewed_rights.commercial_use != commercial_use
        or reviewed_rights.redistribution != redistribution
        or reviewed_rights.reidentification_prohibited
        is not reidentification_prohibited
    ):
        raise ValueError("reviewed rights do not match the promotion case")
    if receipt.known_defect_codes != tuple(known_defect_codes):
        raise ValueError("reviewed known defects do not match the promotion case")

    reviewed_models = {
        (exposure.model_id, exposure.model_revision): (
            exposure.candidate_lock_sha256,
            exposure.freeze_evidence_sha256,
            exposure.status,
        )
        for exposure in receipt.model_exposures
    }
    if set(reviewed_models) != set(candidate_models):
        raise ValueError("human review receipt omits a frozen candidate model")
    if set(exposure_statuses) != set(candidate_models):
        raise ValueError(
            "promotion case does not classify every frozen candidate model"
        )
    for identity, (
        candidate_lock_sha256,
        freeze_evidence_sha256,
    ) in candidate_models.items():
        reviewed_lock, reviewed_freeze, reviewed_status = reviewed_models[identity]
        if (
            reviewed_lock != candidate_lock_sha256
            or reviewed_freeze != freeze_evidence_sha256
            or reviewed_status != exposure_statuses[identity]
        ):
            raise ValueError(
                "human review receipt model exposure differs from the freeze"
            )
