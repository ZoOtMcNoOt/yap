from __future__ import annotations

import hashlib
from typing import Mapping, Sequence


def receipt_hash(marker: str) -> str:
    return hashlib.sha256(marker.encode("utf-8")).hexdigest()


def transcript_reference_review_fixture(
    *,
    case_id: str = "europarl-es-001",
    corpus_id: str = "european-parliament-plenary",
    corpus_release: str = "2026-07-08",
    corpus_split: str = "post-freeze-reality",
    source_item_id: str = "speech-2026-07-08-es-001",
    corpus_source_uri: str = "https://example.invalid/speech",
    attribution_uri: str | None = None,
    suite_ids: Sequence[str] = ("asr-runtime-promotion",),
    condition_labels: Sequence[str] = ("clean", "closeTalk", "readSpeech"),
    audio_byte_length: int = 1_920_044,
    audio_codec: str = "pcm_s16le",
    reference_tier: str = "yapAdjudicated",
    reference_revision: str = "reference-1",
    speaker_count: int = 1,
    timing_kind: str = "none",
    recorded_at_utc: str | None = "2026-07-08T10:00:00Z",
    retrieved_at_utc: str = "2026-07-20T12:00:00Z",
    language_bcp47: str = "es-ES",
    audio_sha256: str | None = None,
    decoded_pcm_sha256: str | None = None,
    reference_sha256: str | None = None,
    evaluation_policy_sha256: str | None = None,
    license_text_sha256: str | None = None,
    license_id: str = "eu-parliament-legal-notice-2026-07-20",
    audio_rights_decision: str = "approved",
    reference_rights_decision: str = "approved",
    commercial_use: str = "allowed",
    redistribution: str = "allowed",
    reidentification_prohibited: bool = True,
    known_defect_codes: Sequence[str] = (),
    trim_start_sample: int = 480_000,
    trim_duration_samples: int = 960_000,
    assignment_sha256: str | None = None,
    first_review_receipt_sha256: str | None = None,
    second_review_receipt_sha256: str | None = None,
    adjudication_receipt_sha256: str | None = None,
    locale_basis_receipt_sha256: str | None = None,
    rights_owner_receipt_sha256: str | None = None,
    attribution_receipt_sha256: str | None = None,
    source_identity_receipt_sha256: str | None = None,
    preprocessing_receipt_sha256: str | None = None,
    locale_basis_kind: str = "humanLocaleAdjudication",
    model_exposures: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, object]:
    assignment_sha256 = assignment_sha256 or receipt_hash(
        f"{case_id}:blind-assignment"
    )
    trimmed_audio_sha256 = audio_sha256 or receipt_hash(f"{case_id}:trimmed-wav")
    final_pcm_sha256 = decoded_pcm_sha256 or receipt_hash(f"{case_id}:final-pcm")
    upstream_reference_sha256 = receipt_hash(f"{case_id}:upstream-reference")
    final_reference_sha256 = reference_sha256 or receipt_hash(
        f"{case_id}:final-reference"
    )
    legal_sha256 = license_text_sha256 or receipt_hash(f"{case_id}:legal-notice")
    first_review_receipt = first_review_receipt_sha256 or receipt_hash(
        f"{case_id}:review-a-receipt"
    )
    second_review_receipt = second_review_receipt_sha256 or receipt_hash(
        f"{case_id}:review-b-receipt"
    )
    if model_exposures is None:
        model_exposures = (
            {
                "modelId": "cohere/cohere-transcribe",
                "modelRevision": "cohere-03-2026",
                "candidateLockSha256": receipt_hash("cohere-lock"),
                "status": "created_after_model_freeze",
                "freezeEvidenceSha256": receipt_hash("cohere-freeze-evidence"),
            },
            {
                "modelId": "nvidia/nemotron-3.5-asr-streaming-0.6b",
                "modelRevision": "nemotron-3.5-streaming-0.6b",
                "candidateLockSha256": receipt_hash("nemotron-lock"),
                "status": "created_after_model_freeze",
                "freezeEvidenceSha256": receipt_hash("nemotron-freeze-evidence"),
            },
        )
    return {
        "schemaVersion": 1,
        "caseId": case_id,
        "packetRevision": "transcript-reference-review-v1",
        "disposition": "pass",
        "evaluationPolicySha256": evaluation_policy_sha256
        or receipt_hash(f"{case_id}:evaluation-policy"),
        "corpus": {
            "corpusId": corpus_id,
            "release": corpus_release,
            "split": corpus_split,
        },
        "coverage": {
            "suiteIds": list(suite_ids),
            "conditionLabels": list(condition_labels),
            "audioByteLength": audio_byte_length,
            "durationSamples": trim_duration_samples,
            "audioCodec": audio_codec,
            "referenceTier": reference_tier,
            "referenceRevision": reference_revision,
            "speakerCount": speaker_count,
            "timingKind": timing_kind,
        },
        "selection": {
            "sourceItemId": source_item_id,
            "indexSnapshotSha256": receipt_hash(f"{case_id}:index-snapshot"),
            "sourceLanguageCode": language_bcp47.split("-", 1)[0],
            "languageBcp47": language_bcp47,
            "recordedAtUtc": recorded_at_utc,
            "retrievedAtUtc": retrieved_at_utc,
        },
        "source": {
            "audioUri": "https://example.invalid/original.mpg",
            "referenceUri": "https://example.invalid/reference.docx",
            "legalNoticeUri": "https://example.invalid/legal-notice",
            "attributionUri": attribution_uri or corpus_source_uri,
            "corpusSourceUri": corpus_source_uri,
            "originalAudioSha256": receipt_hash(f"{case_id}:original-audio"),
            "upstreamReferenceSha256": upstream_reference_sha256,
            "legalNoticeSha256": legal_sha256,
            "sourceIdentityReceiptSha256": source_identity_receipt_sha256
            or receipt_hash(f"{case_id}:source-identity-receipt"),
            "attributionReceiptSha256": attribution_receipt_sha256
            or receipt_hash(f"{case_id}:attribution-receipt"),
        },
        "preparation": {
            "recipeRevision": "exact-source-trim-v1",
            "decodedAudioSha256": receipt_hash(f"{case_id}:decoded-source"),
            "trimStartSample": trim_start_sample,
            "trimDurationSamples": trim_duration_samples,
            "sampleRateHz": 16_000,
            "channels": 1,
            "trimmedAudioSha256": trimmed_audio_sha256,
            "finalPcmSha256": final_pcm_sha256,
            "preprocessingReceiptSha256": preprocessing_receipt_sha256
            or receipt_hash(f"{case_id}:preprocessing-receipt"),
            "assignmentSha256": assignment_sha256,
        },
        "reviews": [
            {
                "reviewerId": "reviewer-a",
                "assignmentSha256": assignment_sha256,
                "audioSha256": trimmed_audio_sha256,
                "upstreamReferenceSha256": upstream_reference_sha256,
                "completedAtUtc": "2026-07-20T13:00:00Z",
                "decision": "pass",
                "reviewedReferenceSha256": final_reference_sha256,
                "receiptSha256": first_review_receipt,
            },
            {
                "reviewerId": "reviewer-b",
                "assignmentSha256": assignment_sha256,
                "audioSha256": trimmed_audio_sha256,
                "upstreamReferenceSha256": upstream_reference_sha256,
                "completedAtUtc": "2026-07-20T14:00:00Z",
                "decision": "pass",
                "reviewedReferenceSha256": final_reference_sha256,
                "receiptSha256": second_review_receipt,
            },
        ],
        "adjudication": {
            "adjudicatorId": "adjudicator-c",
            "reviewReceiptSha256s": [first_review_receipt, second_review_receipt],
            "finalReferenceSha256": final_reference_sha256,
            "decision": "pass",
            "languageBcp47": language_bcp47,
            "localeReviewerId": "locale-reviewer-d",
            "localeBasisKind": locale_basis_kind,
            "localeBasisReceiptSha256": locale_basis_receipt_sha256
            or receipt_hash(f"{case_id}:locale-basis-receipt"),
            "knownDefectCodes": list(known_defect_codes),
            "overrideReasonCodes": [],
            "completedAtUtc": "2026-07-20T15:00:00Z",
            "receiptSha256": adjudication_receipt_sha256
            or receipt_hash(f"{case_id}:adjudication-receipt"),
        },
        "rights": {
            "licenseId": license_id,
            "licenseTextSha256": legal_sha256,
            "audioDecision": audio_rights_decision,
            "referenceDecision": reference_rights_decision,
            "commercialUse": commercial_use,
            "redistribution": redistribution,
            "reidentificationProhibited": reidentification_prohibited,
            "decisionOwnerId": "rights-owner-d",
            "decisionOwnerReceiptSha256": rights_owner_receipt_sha256
            or receipt_hash(f"{case_id}:rights-owner-receipt"),
        },
        "modelExposure": [dict(exposure) for exposure in model_exposures],
    }
