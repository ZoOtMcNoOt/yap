"""Independent listener, adjudicator, rights, and model-exposure proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from yap_server.evaluation.evaluation_receipt_fields import (
    bounded_identifiers,
    enum_value,
    exact_object,
    identifier,
    model_id,
    sha256,
    utc,
)
from yap_server.language_tags import canonical_bcp47


DISPOSITIONS = frozenset({"pass", "hold", "exclude"})
_RIGHTS_DECISIONS = frozenset(
    {"approved", "hold", "excluded", "permissionRequired"}
)
_RIGHTS_CAPABILITIES = frozenset(
    {"allowed", "forbidden", "unknown", "permissionRequired"}
)
_INDEPENDENT_EXPOSURES = frozenset(
    {"contractually_excluded", "created_after_model_freeze"}
)
_LOCALE_BASIS_KINDS = frozenset(
    {"sourceLanguageMarker", "humanLocaleAdjudication"}
)


@dataclass(frozen=True, slots=True)
class ReviewedListener:
    reviewer_id: str
    decision: str
    completed_at_utc: datetime
    reviewed_reference_sha256: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewedModelExposure:
    model_id: str
    model_revision: str
    candidate_lock_sha256: str
    status: str
    freeze_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewedRights:
    license_id: str
    license_text_sha256: str
    audio_decision: str
    reference_decision: str
    commercial_use: str
    redistribution: str
    reidentification_prohibited: bool
    decision_owner_id: str
    decision_owner_receipt_sha256: str


@dataclass(frozen=True, slots=True)
class HumanReferenceAdjudication:
    reference_sha256: str
    known_defect_codes: tuple[str, ...]
    rights: ReviewedRights
    listeners: tuple[ReviewedListener, ...]
    adjudicator_id: str
    adjudication_receipt_sha256: str
    locale_reviewer_id: str
    locale_basis_kind: str
    locale_basis_receipt_sha256: str
    override_reason_codes: tuple[str, ...]
    completed_at_utc: datetime
    model_exposures: tuple[ReviewedModelExposure, ...]


def validate_human_reference_adjudication(
    *,
    reviews_value: object,
    adjudication_value: object,
    rights_value: object,
    exposures_value: object,
    disposition: str,
    retrieved_at: datetime,
    assignment_sha256: str,
    audio_sha256: str,
    upstream_reference_sha256: str,
    legal_notice_sha256: str,
    language_bcp47: str,
) -> HumanReferenceAdjudication:
    listeners, review_completion = _validate_reviews(
        reviews_value,
        retrieved_at=retrieved_at,
        assignment_sha256=assignment_sha256,
        audio_sha256=audio_sha256,
        upstream_reference_sha256=upstream_reference_sha256,
    )
    (
        reference_sha256,
        known_defect_codes,
        adjudicator_id,
        adjudication_receipt_sha256,
        locale_reviewer_id,
        locale_basis_kind,
        locale_basis_receipt_sha256,
        override_reason_codes,
        adjudication_completed_at,
    ) = _validate_adjudication(
        adjudication_value,
        disposition=disposition,
        language_bcp47=language_bcp47,
        reviewer_ids={listener.reviewer_id for listener in listeners},
        review_receipts={listener.receipt_sha256 for listener in listeners},
        review_completion=review_completion,
        review_decisions=[listener.decision for listener in listeners],
        reviewed_reference_sha256s={
            listener.reviewed_reference_sha256 for listener in listeners
        },
    )
    rights = _validate_rights(
        rights_value,
        disposition=disposition,
        legal_notice_sha256=legal_notice_sha256,
    )
    return HumanReferenceAdjudication(
        reference_sha256=reference_sha256,
        known_defect_codes=known_defect_codes,
        rights=rights,
        listeners=listeners,
        adjudicator_id=adjudicator_id,
        adjudication_receipt_sha256=adjudication_receipt_sha256,
        locale_reviewer_id=locale_reviewer_id,
        locale_basis_kind=locale_basis_kind,
        locale_basis_receipt_sha256=locale_basis_receipt_sha256,
        override_reason_codes=override_reason_codes,
        completed_at_utc=adjudication_completed_at,
        model_exposures=_validate_model_exposures(exposures_value),
    )


def _validate_reviews(
    value: object,
    *,
    retrieved_at: datetime,
    assignment_sha256: str,
    audio_sha256: str,
    upstream_reference_sha256: str,
) -> tuple[tuple[ReviewedListener, ...], list[datetime]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("exactly two independent transcript reviews are required")
    reviewer_ids: set[str] = set()
    review_receipts: set[str] = set()
    completion: list[datetime] = []
    listeners: list[ReviewedListener] = []
    for review_value in value:
        review = exact_object(
            review_value,
            {
                "reviewerId",
                "assignmentSha256",
                "audioSha256",
                "upstreamReferenceSha256",
                "completedAtUtc",
                "decision",
                "reviewedReferenceSha256",
                "receiptSha256",
            },
            "transcript review",
        )
        reviewer_id = identifier(review["reviewerId"], "reviewer ID")
        if reviewer_id in reviewer_ids:
            raise ValueError("transcript reviewers must be distinct")
        reviewer_ids.add(reviewer_id)
        if (
            sha256(review["assignmentSha256"], "review assignment SHA-256")
            != assignment_sha256
        ):
            raise ValueError("transcript reviewers received different assignments")
        if sha256(review["audioSha256"], "review audio SHA-256") != audio_sha256:
            raise ValueError("transcript reviewers received different audio")
        if sha256(
            review["upstreamReferenceSha256"], "review upstream reference SHA-256"
        ) != upstream_reference_sha256:
            raise ValueError(
                "transcript reviewers received different upstream references"
            )
        completed_at = utc(review["completedAtUtc"], "review completion time")
        if completed_at < retrieved_at:
            raise ValueError("transcript review predates source retrieval")
        completion.append(completed_at)
        decision = enum_value(review["decision"], DISPOSITIONS, "review decision")
        reviewed_reference_sha256 = sha256(
            review["reviewedReferenceSha256"], "reviewed reference SHA-256"
        )
        receipt_sha256 = sha256(review["receiptSha256"], "review receipt SHA-256")
        if receipt_sha256 in review_receipts:
            raise ValueError("transcript review receipts must be distinct")
        review_receipts.add(receipt_sha256)
        listeners.append(
            ReviewedListener(
                reviewer_id=reviewer_id,
                decision=decision,
                completed_at_utc=completed_at,
                reviewed_reference_sha256=reviewed_reference_sha256,
                receipt_sha256=receipt_sha256,
            )
        )
    return tuple(listeners), completion


def _validate_adjudication(
    value: object,
    *,
    disposition: str,
    language_bcp47: str,
    reviewer_ids: set[str],
    review_receipts: set[str],
    review_completion: list[datetime],
    review_decisions: list[str],
    reviewed_reference_sha256s: set[str],
) -> tuple[
    str,
    tuple[str, ...],
    str,
    str,
    str,
    str,
    str,
    tuple[str, ...],
    datetime,
]:
    adjudication = exact_object(
        value,
        {
            "adjudicatorId",
            "reviewReceiptSha256s",
            "finalReferenceSha256",
            "decision",
            "languageBcp47",
            "localeReviewerId",
            "localeBasisKind",
            "localeBasisReceiptSha256",
            "knownDefectCodes",
            "overrideReasonCodes",
            "completedAtUtc",
            "receiptSha256",
        },
        "transcript adjudication",
    )
    adjudicator_id = identifier(adjudication["adjudicatorId"], "adjudicator ID")
    if adjudicator_id in reviewer_ids:
        raise ValueError("the adjudicator must be independent of both reviewers")
    adjudicated_receipts = adjudication["reviewReceiptSha256s"]
    if not isinstance(adjudicated_receipts, list) or len(adjudicated_receipts) != 2:
        raise ValueError("adjudication must bind both review receipts")
    if {
        sha256(item, "adjudicated review receipt SHA-256")
        for item in adjudicated_receipts
    } != review_receipts:
        raise ValueError("adjudication does not bind the two review receipts")
    decision = enum_value(
        adjudication["decision"], DISPOSITIONS, "adjudication decision"
    )
    if decision != disposition:
        raise ValueError("packet disposition differs from adjudication")
    override_reason_codes = bounded_identifiers(
        adjudication["overrideReasonCodes"], "adjudication override reason codes"
    )
    final_reference_sha256 = sha256(
        adjudication["finalReferenceSha256"], "final reference SHA-256"
    )
    changed_listener_result = (
        any(review_decision != decision for review_decision in review_decisions)
        or reviewed_reference_sha256s != {final_reference_sha256}
    )
    if changed_listener_result:
        if not override_reason_codes:
            raise ValueError(
                "adjudication must explain a changed listener result"
            )
    elif override_reason_codes:
        raise ValueError("adjudication cannot claim an unused override")
    if canonical_bcp47(
        adjudication["languageBcp47"], "adjudicated languageBcp47"
    ) != language_bcp47:
        raise ValueError("adjudicated locale differs from the selected locale")
    locale_reviewer_id = identifier(
        adjudication["localeReviewerId"], "locale reviewer ID"
    )
    locale_basis_kind = enum_value(
        adjudication["localeBasisKind"], _LOCALE_BASIS_KINDS, "locale basis kind"
    )
    if "-" in language_bcp47 and locale_basis_kind != "humanLocaleAdjudication":
        raise ValueError("a locale with subtags requires human locale adjudication")
    locale_basis_receipt_sha256 = sha256(
        adjudication["localeBasisReceiptSha256"],
        "locale-basis receipt SHA-256",
    )
    known_defect_codes = bounded_identifiers(
        adjudication["knownDefectCodes"], "known defect codes"
    )
    completed_at = utc(
        adjudication["completedAtUtc"], "adjudication completion time"
    )
    if completed_at < max(review_completion):
        raise ValueError("adjudication predates an independent review")
    adjudication_receipt_sha256 = sha256(
        adjudication["receiptSha256"], "adjudication receipt SHA-256"
    )
    return (
        final_reference_sha256,
        known_defect_codes,
        adjudicator_id,
        adjudication_receipt_sha256,
        locale_reviewer_id,
        locale_basis_kind,
        locale_basis_receipt_sha256,
        override_reason_codes,
        completed_at,
    )


def _validate_rights(
    value: object,
    *,
    disposition: str,
    legal_notice_sha256: str,
) -> ReviewedRights:
    rights = exact_object(
        value,
        {
            "licenseId",
            "licenseTextSha256",
            "audioDecision",
            "referenceDecision",
            "commercialUse",
            "redistribution",
            "reidentificationProhibited",
            "decisionOwnerId",
            "decisionOwnerReceiptSha256",
        },
        "review rights",
    )
    license_id = identifier(rights["licenseId"], "rights license ID")
    license_text_sha256 = sha256(rights["licenseTextSha256"], "rights text SHA-256")
    if license_text_sha256 != legal_notice_sha256:
        raise ValueError("rights decision does not bind the reviewed legal notice")
    audio_decision = enum_value(
        rights["audioDecision"], _RIGHTS_DECISIONS, "audio rights decision"
    )
    reference_decision = enum_value(
        rights["referenceDecision"],
        _RIGHTS_DECISIONS,
        "reference rights decision",
    )
    commercial_use = enum_value(
        rights["commercialUse"], _RIGHTS_CAPABILITIES, "commercial-use decision"
    )
    redistribution = enum_value(
        rights["redistribution"], _RIGHTS_CAPABILITIES, "redistribution decision"
    )
    reidentification_prohibited = rights["reidentificationProhibited"]
    if not isinstance(reidentification_prohibited, bool):
        raise ValueError("reidentification policy must be a boolean")
    decision_owner_id = identifier(rights["decisionOwnerId"], "rights owner ID")
    decision_owner_receipt_sha256 = sha256(
        rights["decisionOwnerReceiptSha256"], "rights owner receipt SHA-256"
    )
    if disposition == "pass" and (
        audio_decision != "approved"
        or reference_decision != "approved"
        or commercial_use != "allowed"
    ):
        raise ValueError("passing review requires approved reusable source rights")
    return ReviewedRights(
        license_id=license_id,
        license_text_sha256=license_text_sha256,
        audio_decision=audio_decision,
        reference_decision=reference_decision,
        commercial_use=commercial_use,
        redistribution=redistribution,
        reidentification_prohibited=reidentification_prohibited,
        decision_owner_id=decision_owner_id,
        decision_owner_receipt_sha256=decision_owner_receipt_sha256,
    )


def _validate_model_exposures(value: object) -> tuple[ReviewedModelExposure, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("review receipt must classify every candidate model")
    exposures: list[ReviewedModelExposure] = []
    identities: set[tuple[str, str]] = set()
    for exposure_value in value:
        exposure = exact_object(
            exposure_value,
            {
                "modelId",
                "modelRevision",
                "candidateLockSha256",
                "status",
                "freezeEvidenceSha256",
            },
            "model exposure",
        )
        candidate_model_id = model_id(exposure["modelId"], "model ID")
        model_revision = identifier(exposure["modelRevision"], "model revision")
        identity = (candidate_model_id, model_revision)
        if identity in identities:
            raise ValueError("model exposure identities must be unique")
        identities.add(identity)
        exposures.append(
            ReviewedModelExposure(
                model_id=candidate_model_id,
                model_revision=model_revision,
                candidate_lock_sha256=sha256(
                    exposure["candidateLockSha256"], "candidate lock SHA-256"
                ),
                status=enum_value(
                    exposure["status"], _INDEPENDENT_EXPOSURES, "model exposure status"
                ),
                freeze_evidence_sha256=sha256(
                    exposure["freezeEvidenceSha256"],
                    "model freeze-evidence SHA-256",
                ),
            )
        )
    return tuple(exposures)
