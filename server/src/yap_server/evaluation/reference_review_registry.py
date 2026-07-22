"""Trusted participant and artifact registry for human ASR references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from yap_server.evaluation.evaluation_receipt_fields import (
    bounded_identifiers,
    enum_value,
    exact_object,
    identifier,
    sha256,
    utc,
)
from yap_server.evaluation.human_reference_adjudication import ReviewedListener
from yap_server.evaluation.private_evaluation_artifact import (
    decode_json_object_with_identity,
)
from yap_server.evaluation.transcript_reference_review import (
    TranscriptReferenceReviewReceipt,
    validate_transcript_reference_review_receipt_bytes,
)
from yap_server.language_tags import canonical_bcp47


_MAX_TRUSTED_PARTICIPANTS = 1_024
_MAX_TRUSTED_REFERENCE_REVIEWS = 16_384
_PARTICIPANT_ROLES = frozenset(
    {"listener", "adjudicator", "localeReviewer", "rightsDecisionOwner"}
)
_ARTIFACT_KINDS = frozenset(
    {
        "blindAssignment",
        "listenerReview",
        "adjudication",
        "localeBasis",
        "rightsDecision",
        "sourceIdentity",
        "attribution",
        "preprocessing",
    }
)
ArtifactVerifier = Callable[[object, str, str], bytes]


@dataclass(frozen=True, slots=True)
class TrustedReviewParticipant:
    participant_id: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrustedReferenceReview:
    case_id: str
    receipt_sha256: str
    receipt: TranscriptReferenceReviewReceipt


def load_trusted_review_participants(
    value: object,
    *,
    verify_artifact: ArtifactVerifier,
) -> tuple[TrustedReviewParticipant, ...]:
    participants: list[TrustedReviewParticipant] = []
    participant_roles: dict[str, tuple[str, ...]] = {}
    entries: list[tuple[Mapping[str, object], str, tuple[str, ...], str]] = []
    for participant_value in _bounded_array(
        value,
        "trusted review participants",
        maximum_entries=_MAX_TRUSTED_PARTICIPANTS,
        allow_empty=False,
    ):
        participant = exact_object(
            participant_value,
            {
                "participantId",
                "roles",
                "authorizationPath",
                "authorizationSha256",
            },
            "trusted review participant",
        )
        participant_id = identifier(
            participant["participantId"], "trusted review participant ID"
        )
        if participant_id in participant_roles:
            raise ValueError("trusted review participant IDs must be unique")
        roles = _unique_roles(participant["roles"])
        authorization_sha256 = sha256(
            participant["authorizationSha256"],
            "trusted review participant authorization SHA-256",
        )
        participant_roles[participant_id] = roles
        entries.append((participant, participant_id, roles, authorization_sha256))

    for participant, participant_id, roles, authorization_sha256 in entries:
        authorization_body = verify_artifact(
            participant["authorizationPath"],
            authorization_sha256,
            "trusted review participant authorization",
        )
        authorization, _identity = decode_json_object_with_identity(
            authorization_body,
            field="trusted review participant authorization",
            expected_sha256=authorization_sha256,
        )
        authorization = exact_object(
            authorization,
            {"schemaVersion", "participantId", "roles"},
            "trusted review participant authorization",
        )
        if (
            authorization["schemaVersion"] != 1
            or authorization["participantId"] != participant_id
            or _unique_roles(authorization["roles"]) != roles
        ):
            raise ValueError(
                "trusted review participant authorization does not match the registry"
            )
        participants.append(
            TrustedReviewParticipant(participant_id=participant_id, roles=roles)
        )
    return tuple(participants)


def trusted_review_participant_roles(
    participants: Iterable[TrustedReviewParticipant],
) -> dict[str, tuple[str, ...]]:
    roles_by_participant: dict[str, tuple[str, ...]] = {}
    for participant in participants:
        if not isinstance(participant, TrustedReviewParticipant):
            raise ValueError("trusted review participant is invalid")
        participant_id = identifier(
            participant.participant_id, "trusted review participant ID"
        )
        if participant_id in roles_by_participant:
            raise ValueError("trusted review participant IDs must be unique")
        roles_by_participant[participant_id] = _unique_roles(list(participant.roles))
    return roles_by_participant


def load_trusted_reference_reviews(
    value: object,
    *,
    participant_roles: Mapping[str, tuple[str, ...]],
    verify_artifact: ArtifactVerifier,
) -> tuple[TrustedReferenceReview, ...]:
    reviews: list[TrustedReferenceReview] = []
    entries: list[tuple[Mapping[str, object], str, str]] = []
    case_ids: set[str] = set()
    for review_value in _bounded_array(
        value,
        "trusted reference reviews",
        maximum_entries=_MAX_TRUSTED_REFERENCE_REVIEWS,
        allow_empty=True,
    ):
        review = exact_object(
            review_value,
            {
                "caseId",
                "reviewReceiptPath",
                "reviewReceiptSha256",
                "supportingArtifacts",
            },
            "trusted reference review",
        )
        case_id = identifier(review["caseId"], "trusted review case ID")
        if case_id in case_ids:
            raise ValueError("trusted reference review case IDs must be unique")
        case_ids.add(case_id)
        receipt_sha256 = sha256(
            review["reviewReceiptSha256"],
            "trusted reference review receipt SHA-256",
        )
        entries.append((review, case_id, receipt_sha256))

    for review, case_id, receipt_sha256 in entries:
        receipt_body = verify_artifact(
            review["reviewReceiptPath"],
            receipt_sha256,
            "trusted reference review receipt",
        )
        receipt = validate_transcript_reference_review_receipt_bytes(
            receipt_body,
            expected_sha256=receipt_sha256,
        )
        _verify_reference_review_support(
            review["supportingArtifacts"],
            case_id=case_id,
            receipt=receipt,
            participant_roles=participant_roles,
            verify_artifact=verify_artifact,
        )
        reviews.append(
            TrustedReferenceReview(
                case_id=case_id,
                receipt_sha256=receipt_sha256,
                receipt=receipt,
            )
        )
    return tuple(reviews)


def index_trusted_reference_reviews(
    reviews: Iterable[TrustedReferenceReview],
) -> dict[str, tuple[str, TranscriptReferenceReviewReceipt]]:
    indexed: dict[str, tuple[str, TranscriptReferenceReviewReceipt]] = {}
    for review in reviews:
        if not isinstance(review, TrustedReferenceReview):
            raise ValueError("trusted reference review is invalid")
        case_id = identifier(review.case_id, "trusted review case ID")
        if case_id in indexed:
            raise ValueError("trusted reference review case IDs must be unique")
        receipt_sha256 = sha256(
            review.receipt_sha256,
            "trusted reference review receipt SHA-256",
        )
        if not isinstance(review.receipt, TranscriptReferenceReviewReceipt):
            raise ValueError("trusted reference review receipt is invalid")
        indexed[case_id] = (receipt_sha256, review.receipt)
    return indexed


def _verify_reference_review_support(
    value: object,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
    participant_roles: Mapping[str, tuple[str, ...]],
    verify_artifact: ArtifactVerifier,
) -> None:
    expected: dict[tuple[str, str | None], str] = {
        ("blindAssignment", None): receipt.assignment_sha256,
        ("adjudication", receipt.adjudicator_id): receipt.adjudication_receipt_sha256,
        (
            "localeBasis",
            receipt.locale_reviewer_id,
        ): receipt.locale_basis_receipt_sha256,
        (
            "rightsDecision",
            receipt.rights.decision_owner_id,
        ): receipt.rights.decision_owner_receipt_sha256,
        ("attribution", None): receipt.attribution_receipt_sha256,
        ("sourceIdentity", None): receipt.source_identity_receipt_sha256,
        ("preprocessing", None): receipt.preprocessing_receipt_sha256,
    }
    for listener in receipt.listeners:
        expected[("listenerReview", listener.reviewer_id)] = listener.receipt_sha256

    observed: set[tuple[str, str | None]] = set()
    artifact_bodies: dict[tuple[str, str | None], tuple[bytes, str]] = {}
    for artifact_value in _nonempty_array(
        value, "trusted reference review artifacts"
    ):
        artifact = exact_object(
            artifact_value,
            {"kind", "participantId", "artifactPath", "artifactSha256"},
            "trusted reference review artifact",
        )
        kind = enum_value(
            artifact["kind"], _ARTIFACT_KINDS, "reference review artifact kind"
        )
        participant_value = artifact["participantId"]
        participant_id = (
            None
            if participant_value is None
            else identifier(participant_value, "reference review participant ID")
        )
        key = (kind, participant_id)
        if key in observed:
            raise ValueError("trusted reference review artifacts must be unique")
        observed.add(key)
        expected_sha256 = expected.get(key)
        artifact_sha256 = sha256(
            artifact["artifactSha256"], "reference review artifact SHA-256"
        )
        if expected_sha256 is None or artifact_sha256 != expected_sha256:
            raise ValueError(
                "trusted reference review artifacts do not match the review receipt"
            )
        artifact_bodies[key] = (
            verify_artifact(
                artifact["artifactPath"],
                artifact_sha256,
                f"trusted {kind} artifact",
            ),
            artifact_sha256,
        )
        required_role = {
            "listenerReview": "listener",
            "adjudication": "adjudicator",
            "localeBasis": "localeReviewer",
            "rightsDecision": "rightsDecisionOwner",
        }.get(kind)
        if required_role is not None:
            if participant_id is None or required_role not in participant_roles.get(
                participant_id, ()
            ):
                raise ValueError(
                    f"reference review participant is not an authorized {required_role}"
                )
        elif participant_id is not None:
            raise ValueError(f"{kind} artifact cannot claim a review participant")

    if observed != set(expected):
        raise ValueError("trusted reference review artifacts are incomplete")
    _validate_blind_assignment_artifact(
        *artifact_bodies[("blindAssignment", None)],
        case_id=case_id,
        receipt=receipt,
    )
    for listener in receipt.listeners:
        _validate_listener_review_artifact(
            *artifact_bodies[("listenerReview", listener.reviewer_id)],
            case_id=case_id,
            listener=listener,
            receipt=receipt,
        )
    _validate_adjudication_artifact(
        *artifact_bodies[("adjudication", receipt.adjudicator_id)],
        case_id=case_id,
        receipt=receipt,
    )
    _validate_locale_basis_artifact(
        *artifact_bodies[("localeBasis", receipt.locale_reviewer_id)],
        case_id=case_id,
        receipt=receipt,
    )
    _validate_rights_decision_artifact(
        *artifact_bodies[("rightsDecision", receipt.rights.decision_owner_id)],
        case_id=case_id,
        receipt=receipt,
    )
    _validate_attribution_artifact(
        *artifact_bodies[("attribution", None)],
        case_id=case_id,
        receipt=receipt,
    )
    _validate_source_identity_artifact(
        *artifact_bodies[("sourceIdentity", None)],
        case_id=case_id,
        receipt=receipt,
    )
    _validate_preprocessing_artifact(
        *artifact_bodies[("preprocessing", None)],
        case_id=case_id,
        receipt=receipt,
    )


def _read_artifact(body: bytes, expected_sha256: str, field: str) -> dict[str, object]:
    payload, _identity = decode_json_object_with_identity(
        body,
        field=field,
        expected_sha256=expected_sha256,
    )
    return payload


def _validate_blind_assignment_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    assignment = exact_object(
        _read_artifact(body, expected_sha256, "blind review assignment"),
        {
            "schemaVersion",
            "caseId",
            "reviewerIds",
            "audioSha256",
            "upstreamReferenceSha256",
            "excludedInputs",
        },
        "blind review assignment",
    )
    reviewer_ids = tuple(
        identifier(value, "blind assignment reviewer ID")
        for value in _nonempty_array(
            assignment["reviewerIds"], "blind assignment reviewers"
        )
    )
    if (
        assignment["schemaVersion"] != 1
        or assignment["caseId"] != case_id
        or reviewer_ids != tuple(listener.reviewer_id for listener in receipt.listeners)
        or assignment["audioSha256"] != receipt.audio_sha256
        or assignment["upstreamReferenceSha256"] != receipt.upstream_reference_sha256
        or assignment["excludedInputs"] != ["modelHypotheses", "peerReviews"]
    ):
        raise ValueError(
            "blind review assignment does not prove independent listener inputs"
        )


def _validate_listener_review_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    listener: ReviewedListener,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    if not isinstance(listener, ReviewedListener):
        raise ValueError("listener review identity is invalid")
    review = exact_object(
        _read_artifact(body, expected_sha256, "listener review receipt"),
        {
            "schemaVersion",
            "caseId",
            "reviewerId",
            "assignmentSha256",
            "audioSha256",
            "upstreamReferenceSha256",
            "completedAtUtc",
            "decision",
            "reviewedReferenceSha256",
        },
        "listener review receipt",
    )
    if (
        review["schemaVersion"] != 1
        or review["caseId"] != case_id
        or review["reviewerId"] != listener.reviewer_id
        or review["assignmentSha256"] != receipt.assignment_sha256
        or review["audioSha256"] != receipt.audio_sha256
        or review["upstreamReferenceSha256"] != receipt.upstream_reference_sha256
        or utc(review["completedAtUtc"], "listener review completion time")
        != listener.completed_at_utc
        or review["decision"] != listener.decision
        or review["reviewedReferenceSha256"] != listener.reviewed_reference_sha256
    ):
        raise ValueError("listener review receipt does not match the review packet")


def _validate_adjudication_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    adjudication = exact_object(
        _read_artifact(body, expected_sha256, "adjudication receipt"),
        {
            "schemaVersion",
            "caseId",
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
        },
        "adjudication receipt",
    )
    review_receipt_sha256s = tuple(
        sha256(value, "adjudicated listener receipt SHA-256")
        for value in _nonempty_array(
            adjudication["reviewReceiptSha256s"],
            "adjudicated listener receipts",
        )
    )
    if len(review_receipt_sha256s) != 2:
        raise ValueError("adjudication receipt must bind two listener receipts")
    known_defect_codes = bounded_identifiers(
        adjudication["knownDefectCodes"], "adjudication known defect codes"
    )
    override_reason_codes = bounded_identifiers(
        adjudication["overrideReasonCodes"], "adjudication override reason codes"
    )
    if (
        adjudication["schemaVersion"] != 1
        or adjudication["caseId"] != case_id
        or adjudication["adjudicatorId"] != receipt.adjudicator_id
        or review_receipt_sha256s
        != tuple(listener.receipt_sha256 for listener in receipt.listeners)
        or adjudication["finalReferenceSha256"] != receipt.reference_sha256
        or adjudication["decision"] != receipt.disposition
        or canonical_bcp47(
            adjudication["languageBcp47"], "adjudication receipt languageBcp47"
        )
        != receipt.language_bcp47
        or adjudication["localeReviewerId"] != receipt.locale_reviewer_id
        or adjudication["localeBasisKind"] != receipt.locale_basis_kind
        or adjudication["localeBasisReceiptSha256"]
        != receipt.locale_basis_receipt_sha256
        or known_defect_codes != receipt.known_defect_codes
        or override_reason_codes != receipt.override_reason_codes
        or utc(adjudication["completedAtUtc"], "adjudication completion time")
        != receipt.adjudication_completed_at_utc
    ):
        raise ValueError("adjudication receipt does not match the review packet")


def _validate_locale_basis_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    locale_basis = exact_object(
        _read_artifact(body, expected_sha256, "locale-basis receipt"),
        {"schemaVersion", "caseId", "reviewerId", "languageBcp47", "basisKind"},
        "locale-basis receipt",
    )
    if (
        locale_basis["schemaVersion"] != 1
        or locale_basis["caseId"] != case_id
        or locale_basis["reviewerId"] != receipt.locale_reviewer_id
        or canonical_bcp47(
            locale_basis["languageBcp47"], "locale-basis languageBcp47"
        )
        != receipt.language_bcp47
        or locale_basis["basisKind"] != receipt.locale_basis_kind
    ):
        raise ValueError("locale-basis receipt does not match the reviewed locale")


def _validate_rights_decision_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    rights = exact_object(
        _read_artifact(body, expected_sha256, "rights-decision receipt"),
        {
            "schemaVersion",
            "caseId",
            "decisionOwnerId",
            "licenseId",
            "licenseTextSha256",
            "audioDecision",
            "referenceDecision",
            "commercialUse",
            "redistribution",
            "reidentificationProhibited",
        },
        "rights-decision receipt",
    )
    reviewed = receipt.rights
    if (
        rights["schemaVersion"] != 1
        or rights["caseId"] != case_id
        or rights["decisionOwnerId"] != reviewed.decision_owner_id
        or rights["licenseId"] != reviewed.license_id
        or rights["licenseTextSha256"] != reviewed.license_text_sha256
        or rights["audioDecision"] != reviewed.audio_decision
        or rights["referenceDecision"] != reviewed.reference_decision
        or rights["commercialUse"] != reviewed.commercial_use
        or rights["redistribution"] != reviewed.redistribution
        or rights["reidentificationProhibited"]
        is not reviewed.reidentification_prohibited
    ):
        raise ValueError("rights-decision receipt does not match the reviewed rights")


def _validate_attribution_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    attribution = exact_object(
        _read_artifact(body, expected_sha256, "attribution receipt"),
        {"schemaVersion", "caseId", "attributionUri", "verified"},
        "attribution receipt",
    )
    if (
        attribution["schemaVersion"] != 1
        or attribution["caseId"] != case_id
        or attribution["attributionUri"] != receipt.attribution_uri
        or attribution["verified"] is not True
    ):
        raise ValueError("attribution receipt does not verify the review case")


def _validate_source_identity_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    source = exact_object(
        _read_artifact(body, expected_sha256, "source identity receipt"),
        {
            "schemaVersion",
            "caseId",
            "corpusId",
            "corpusRelease",
            "corpusSplit",
            "sourceItemId",
            "corpusSourceUri",
            "audioUri",
            "referenceUri",
            "legalNoticeUri",
            "indexSnapshotSha256",
            "recordedAtUtc",
            "retrievedAtUtc",
            "originalAudioSha256",
            "upstreamReferenceSha256",
            "legalNoticeSha256",
            "verified",
        },
        "source identity receipt",
    )
    recorded_at_value = source["recordedAtUtc"]
    recorded_at = (
        None
        if recorded_at_value is None
        else utc(recorded_at_value, "source identity recording time")
    )
    if (
        source["schemaVersion"] != 1
        or source["caseId"] != case_id
        or source["corpusId"] != receipt.corpus_id
        or source["corpusRelease"] != receipt.corpus_release
        or source["corpusSplit"] != receipt.corpus_split
        or source["sourceItemId"] != receipt.source_item_id
        or source["corpusSourceUri"] != receipt.corpus_source_uri
        or source["audioUri"] != receipt.audio_uri
        or source["referenceUri"] != receipt.reference_uri
        or source["legalNoticeUri"] != receipt.legal_notice_uri
        or source["indexSnapshotSha256"] != receipt.index_snapshot_sha256
        or recorded_at != receipt.recorded_at_utc
        or utc(source["retrievedAtUtc"], "source identity retrieval time")
        != receipt.retrieved_at_utc
        or source["originalAudioSha256"] != receipt.original_audio_sha256
        or source["upstreamReferenceSha256"] != receipt.upstream_reference_sha256
        or source["legalNoticeSha256"] != receipt.legal_notice_sha256
        or source["verified"] is not True
    ):
        raise ValueError("source identity receipt does not match the review packet")


def _validate_preprocessing_artifact(
    body: bytes,
    expected_sha256: str,
    *,
    case_id: str,
    receipt: TranscriptReferenceReviewReceipt,
) -> None:
    preprocessing = exact_object(
        _read_artifact(body, expected_sha256, "preprocessing receipt"),
        {
            "schemaVersion",
            "caseId",
            "assignmentSha256",
            "originalAudioSha256",
            "recipeRevision",
            "decodedAudioSha256",
            "trimStartSample",
            "trimDurationSamples",
            "sampleRateHz",
            "channels",
            "audioSha256",
            "decodedPcmSha256",
            "verified",
        },
        "preprocessing receipt",
    )
    if (
        preprocessing["schemaVersion"] != 1
        or preprocessing["caseId"] != case_id
        or preprocessing["assignmentSha256"] != receipt.assignment_sha256
        or preprocessing["originalAudioSha256"] != receipt.original_audio_sha256
        or preprocessing["recipeRevision"] != receipt.recipe_revision
        or preprocessing["decodedAudioSha256"] != receipt.decoded_audio_sha256
        or preprocessing["trimStartSample"] != receipt.trim_start_sample
        or preprocessing["trimDurationSamples"] != receipt.trim_duration_samples
        or preprocessing["sampleRateHz"] != receipt.sample_rate_hz
        or preprocessing["channels"] != receipt.channels
        or preprocessing["audioSha256"] != receipt.audio_sha256
        or preprocessing["decodedPcmSha256"] != receipt.decoded_pcm_sha256
        or preprocessing["verified"] is not True
    ):
        raise ValueError("preprocessing receipt does not match the review packet")


def _unique_roles(value: object) -> tuple[str, ...]:
    entries = tuple(
        enum_value(role, _PARTICIPANT_ROLES, "trusted review participant role")
        for role in _nonempty_array(value, "trusted review participant roles")
    )
    if entries != tuple(sorted(set(entries))):
        raise ValueError("trusted review participant roles must be unique and sorted")
    return entries


def _nonempty_array(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return value


def _bounded_array(
    value: object,
    field: str,
    *,
    maximum_entries: int,
    allow_empty: bool,
) -> Sequence[object]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or len(value) > maximum_entries
    ):
        raise ValueError(f"{field} exceeds its bounded array contract")
    return value
