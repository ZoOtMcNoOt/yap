"""Transcript-free proof that a private ASR reference was independently reviewed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from yap_server.json_contract import (
    bounded_identifiers,
    enum_value,
    exact_object,
    https_uri,
    identifier,
    nonnegative_int,
    positive_int,
    sha256,
    utc,
)
from yap_server.evaluation.human_reference_adjudication import (
    DISPOSITIONS,
    ReviewedModelExposure,
    ReviewedListener,
    ReviewedRights,
    validate_human_reference_adjudication,
)
from yap_server.private_artifact import (
    decode_json_object_with_identity,
    read_bounded_regular_file,
)
from yap_server.language_tags import canonical_bcp47


_MAX_RECEIPT_BYTES = 512 * 1024
_SOURCE_LANGUAGE = re.compile(r"^[a-z]{2,3}$")


@dataclass(frozen=True, slots=True)
class TranscriptReferenceReviewReceipt:
    case_id: str
    packet_revision: str
    disposition: str
    corpus_id: str
    corpus_release: str
    corpus_split: str
    source_item_id: str
    corpus_source_uri: str
    suite_ids: tuple[str, ...]
    condition_labels: tuple[str, ...]
    audio_byte_length: int
    duration_samples: int
    audio_codec: str
    reference_tier: str
    reference_revision: str
    speaker_count: int
    timing_kind: str
    index_snapshot_sha256: str
    recorded_at_utc: datetime | None
    retrieved_at_utc: datetime
    language_bcp47: str
    audio_sha256: str
    decoded_pcm_sha256: str
    reference_sha256: str
    evaluation_policy_sha256: str
    assignment_sha256: str
    recipe_revision: str
    decoded_audio_sha256: str
    trim_start_sample: int
    trim_duration_samples: int
    sample_rate_hz: int
    channels: int
    preprocessing_receipt_sha256: str
    audio_uri: str
    reference_uri: str
    legal_notice_uri: str
    attribution_uri: str
    original_audio_sha256: str
    upstream_reference_sha256: str
    legal_notice_sha256: str
    source_identity_receipt_sha256: str
    attribution_receipt_sha256: str
    known_defect_codes: tuple[str, ...]
    rights: ReviewedRights
    listeners: tuple[ReviewedListener, ...]
    adjudicator_id: str
    adjudication_receipt_sha256: str
    locale_reviewer_id: str
    locale_basis_kind: str
    locale_basis_receipt_sha256: str
    override_reason_codes: tuple[str, ...]
    adjudication_completed_at_utc: datetime
    model_exposures: tuple[ReviewedModelExposure, ...]


def load_transcript_reference_review_receipt(
    path: Path,
    *,
    expected_sha256: str,
) -> TranscriptReferenceReviewReceipt:
    """Read one hash-bound receipt without returning its private raw document."""

    expected = sha256(expected_sha256, "review receipt SHA-256")
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("review receipt must be an absolute real file")
    body = read_bounded_regular_file(
        path,
        maximum_bytes=_MAX_RECEIPT_BYTES,
        field="review receipt",
    )
    return validate_transcript_reference_review_receipt_bytes(
        body,
        expected_sha256=expected,
    )


def validate_transcript_reference_review_receipt_bytes(
    body: bytes,
    *,
    expected_sha256: str,
) -> TranscriptReferenceReviewReceipt:
    expected = sha256(expected_sha256, "review receipt SHA-256")
    if not 1 <= len(body) <= _MAX_RECEIPT_BYTES:
        raise ValueError("review receipt size is invalid")
    try:
        payload, _identity = decode_json_object_with_identity(
            body,
            field="review receipt",
            expected_sha256=expected,
        )
    except ValueError as error:
        if "out-of-band digest" in str(error):
            raise ValueError(
                "review receipt differs from the trusted registry"
            ) from error
        raise
    return validate_transcript_reference_review_receipt(payload)


def validate_transcript_reference_review_receipt(
    value: object,
) -> TranscriptReferenceReviewReceipt:
    receipt = exact_object(
        value,
        {
            "schemaVersion",
            "caseId",
            "packetRevision",
            "disposition",
            "evaluationPolicySha256",
            "corpus",
            "coverage",
            "selection",
            "source",
            "preparation",
            "reviews",
            "adjudication",
            "rights",
            "modelExposure",
        },
        "transcript reference review",
    )
    if receipt["schemaVersion"] != 1:
        raise ValueError("transcript reference review schema is unsupported")
    case_id = identifier(receipt["caseId"], "review case ID")
    packet_revision = identifier(receipt["packetRevision"], "packet revision")
    if packet_revision != "transcript-reference-review-v1":
        raise ValueError("packet revision is unsupported")
    disposition = enum_value(receipt["disposition"], DISPOSITIONS, "disposition")
    evaluation_policy_sha256 = sha256(
        receipt["evaluationPolicySha256"], "evaluation policy SHA-256"
    )

    corpus = exact_object(
        receipt["corpus"],
        {"corpusId", "release", "split"},
        "review corpus",
    )
    corpus_id = identifier(corpus["corpusId"], "review corpus ID")
    corpus_release = identifier(corpus["release"], "review corpus release")
    corpus_split = identifier(corpus["split"], "review corpus split")

    coverage = exact_object(
        receipt["coverage"],
        {
            "suiteIds",
            "conditionLabels",
            "audioByteLength",
            "durationSamples",
            "audioCodec",
            "referenceTier",
            "referenceRevision",
            "speakerCount",
            "timingKind",
        },
        "review coverage",
    )
    suite_ids = bounded_identifiers(coverage["suiteIds"], "review suite IDs")
    condition_labels = bounded_identifiers(
        coverage["conditionLabels"], "review condition labels"
    )
    if tuple(sorted(suite_ids)) != suite_ids:
        raise ValueError("review suite IDs must be sorted")
    if tuple(sorted(condition_labels)) != condition_labels:
        raise ValueError("review condition labels must be sorted")
    audio_byte_length = positive_int(
        coverage["audioByteLength"], "review audio byte length"
    )
    duration_samples = positive_int(
        coverage["durationSamples"], "review audio duration samples"
    )
    audio_codec = identifier(coverage["audioCodec"], "review audio codec")
    reference_tier = identifier(coverage["referenceTier"], "reference tier")
    reference_revision = identifier(coverage["referenceRevision"], "reference revision")
    speaker_count = nonnegative_int(coverage["speakerCount"], "speaker count")
    if speaker_count > 64:
        raise ValueError("speaker count exceeds the review bound")
    timing_kind = identifier(coverage["timingKind"], "reference timing kind")

    selection = exact_object(
        receipt["selection"],
        {
            "sourceItemId",
            "indexSnapshotSha256",
            "sourceLanguageCode",
            "languageBcp47",
            "recordedAtUtc",
            "retrievedAtUtc",
        },
        "review selection",
    )
    source_item_id = identifier(selection["sourceItemId"], "source item ID")
    index_snapshot_sha256 = sha256(
        selection["indexSnapshotSha256"], "index snapshot SHA-256"
    )
    source_language = selection["sourceLanguageCode"]
    if not isinstance(source_language, str) or not _SOURCE_LANGUAGE.fullmatch(
        source_language
    ):
        raise ValueError(
            "source language code must be a lowercase BCP 47 primary subtag"
        )
    language_bcp47 = canonical_bcp47(selection["languageBcp47"], "review languageBcp47")
    if language_bcp47.split("-", 1)[0] != source_language:
        raise ValueError("review locale does not match the source language marker")
    recorded_at_value = selection["recordedAtUtc"]
    recorded_at = (
        None
        if recorded_at_value is None
        else utc(recorded_at_value, "source recording time")
    )
    retrieved_at = utc(selection["retrievedAtUtc"], "source retrieval time")
    if recorded_at is not None and recorded_at > retrieved_at:
        raise ValueError("source retrieval cannot precede the recording")

    source = exact_object(
        receipt["source"],
        {
            "audioUri",
            "referenceUri",
            "legalNoticeUri",
            "attributionUri",
            "corpusSourceUri",
            "originalAudioSha256",
            "upstreamReferenceSha256",
            "legalNoticeSha256",
            "sourceIdentityReceiptSha256",
            "attributionReceiptSha256",
        },
        "review source",
    )
    audio_uri = https_uri(source["audioUri"], "audio URI")
    reference_uri = https_uri(source["referenceUri"], "reference URI")
    legal_notice_uri = https_uri(source["legalNoticeUri"], "legal notice URI")
    attribution_uri = https_uri(source["attributionUri"], "attribution URI")
    corpus_source_uri = https_uri(source["corpusSourceUri"], "corpus source URI")
    original_audio_sha256 = sha256(
        source["originalAudioSha256"], "original audio SHA-256"
    )
    upstream_reference_sha256 = sha256(
        source["upstreamReferenceSha256"], "upstream reference SHA-256"
    )
    legal_notice_sha256 = sha256(source["legalNoticeSha256"], "legal notice SHA-256")
    source_identity_receipt_sha256 = sha256(
        source["sourceIdentityReceiptSha256"],
        "source identity receipt SHA-256",
    )
    attribution_receipt_sha256 = sha256(
        source["attributionReceiptSha256"], "attribution receipt SHA-256"
    )

    preparation = exact_object(
        receipt["preparation"],
        {
            "recipeRevision",
            "decodedAudioSha256",
            "trimStartSample",
            "trimDurationSamples",
            "sampleRateHz",
            "channels",
            "trimmedAudioSha256",
            "finalPcmSha256",
            "preprocessingReceiptSha256",
            "assignmentSha256",
        },
        "review preparation",
    )
    recipe_revision = identifier(preparation["recipeRevision"], "trim recipe revision")
    decoded_audio_sha256 = sha256(
        preparation["decodedAudioSha256"], "decoded source SHA-256"
    )
    trim_start_sample = nonnegative_int(
        preparation["trimStartSample"], "trim start sample"
    )
    trim_duration_samples = positive_int(
        preparation["trimDurationSamples"], "trim duration samples"
    )
    sample_rate_hz = positive_int(preparation["sampleRateHz"], "sample rate")
    channels = positive_int(preparation["channels"], "channel count")
    if sample_rate_hz != 16_000 or channels != 1:
        raise ValueError("review audio must be canonical mono PCM at 16 kHz")
    if trim_duration_samples != duration_samples:
        raise ValueError("review coverage and preprocessing durations differ")
    audio_sha256 = sha256(preparation["trimmedAudioSha256"], "trimmed audio SHA-256")
    decoded_pcm_sha256 = sha256(preparation["finalPcmSha256"], "final PCM SHA-256")
    preprocessing_receipt_sha256 = sha256(
        preparation["preprocessingReceiptSha256"],
        "preprocessing receipt SHA-256",
    )
    assignment_sha256 = sha256(
        preparation["assignmentSha256"], "review assignment SHA-256"
    )

    adjudication = validate_human_reference_adjudication(
        reviews_value=receipt["reviews"],
        adjudication_value=receipt["adjudication"],
        rights_value=receipt["rights"],
        exposures_value=receipt["modelExposure"],
        disposition=disposition,
        retrieved_at=retrieved_at,
        assignment_sha256=assignment_sha256,
        audio_sha256=audio_sha256,
        upstream_reference_sha256=upstream_reference_sha256,
        legal_notice_sha256=legal_notice_sha256,
        language_bcp47=language_bcp47,
    )
    return TranscriptReferenceReviewReceipt(
        case_id=case_id,
        packet_revision=packet_revision,
        disposition=disposition,
        corpus_id=corpus_id,
        corpus_release=corpus_release,
        corpus_split=corpus_split,
        source_item_id=source_item_id,
        corpus_source_uri=corpus_source_uri,
        suite_ids=suite_ids,
        condition_labels=condition_labels,
        audio_byte_length=audio_byte_length,
        duration_samples=duration_samples,
        audio_codec=audio_codec,
        reference_tier=reference_tier,
        reference_revision=reference_revision,
        speaker_count=speaker_count,
        timing_kind=timing_kind,
        index_snapshot_sha256=index_snapshot_sha256,
        recorded_at_utc=recorded_at,
        retrieved_at_utc=retrieved_at,
        language_bcp47=language_bcp47,
        audio_sha256=audio_sha256,
        decoded_pcm_sha256=decoded_pcm_sha256,
        reference_sha256=adjudication.reference_sha256,
        evaluation_policy_sha256=evaluation_policy_sha256,
        assignment_sha256=assignment_sha256,
        recipe_revision=recipe_revision,
        decoded_audio_sha256=decoded_audio_sha256,
        trim_start_sample=trim_start_sample,
        trim_duration_samples=trim_duration_samples,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        preprocessing_receipt_sha256=preprocessing_receipt_sha256,
        audio_uri=audio_uri,
        reference_uri=reference_uri,
        legal_notice_uri=legal_notice_uri,
        attribution_uri=attribution_uri,
        original_audio_sha256=original_audio_sha256,
        upstream_reference_sha256=upstream_reference_sha256,
        legal_notice_sha256=legal_notice_sha256,
        source_identity_receipt_sha256=source_identity_receipt_sha256,
        attribution_receipt_sha256=attribution_receipt_sha256,
        known_defect_codes=adjudication.known_defect_codes,
        rights=adjudication.rights,
        listeners=adjudication.listeners,
        adjudicator_id=adjudication.adjudicator_id,
        adjudication_receipt_sha256=adjudication.adjudication_receipt_sha256,
        locale_reviewer_id=adjudication.locale_reviewer_id,
        locale_basis_kind=adjudication.locale_basis_kind,
        locale_basis_receipt_sha256=adjudication.locale_basis_receipt_sha256,
        override_reason_codes=adjudication.override_reason_codes,
        adjudication_completed_at_utc=adjudication.completed_at_utc,
        model_exposures=adjudication.model_exposures,
    )
