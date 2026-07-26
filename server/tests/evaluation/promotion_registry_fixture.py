from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yap_server.evaluation.corpus_manifest import evaluation_policy_sha256
from yap_server.evaluation.transcript_scoring import current_scorer_lock
from tests.evaluation.transcript_reference_review_fixture import (
    receipt_hash,
    transcript_reference_review_fixture,
)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def promotion_registry_fixture(
    root: Path,
    manifest: dict[str, object],
    *,
    include_reference_review: bool = True,
) -> tuple[Path, Path, dict[str, str]]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    scorer_lock_path = root / "scorer.lock.json"
    write_json(scorer_lock_path, current_scorer_lock())
    manifest["scorerLockSha256"] = file_sha256(scorer_lock_path)
    registry_models: list[dict[str, object]] = []
    candidate_models = manifest["candidateModels"]  # type: ignore[assignment]
    for index, model in enumerate(candidate_models):
        lock_path = root / f"candidate-{index}.lock.json"
        freeze_path = root / f"candidate-{index}.freeze.json"
        lock_path.write_bytes(f"candidate-lock-{index}".encode())
        freeze_path.write_bytes(f"freeze-evidence-{index}".encode())
        model["candidateLockSha256"] = file_sha256(lock_path)
        model["freezeEvidenceSha256"] = file_sha256(freeze_path)
        registry_models.append(
            {
                "id": model["id"],
                "revision": model["revision"],
                "candidateLockPath": lock_path.name,
                "candidateLockSha256": model["candidateLockSha256"],
                "frozenAtUtc": model["frozenAtUtc"],
                "freezeEvidencePath": freeze_path.name,
                "freezeEvidenceSha256": model["freezeEvidenceSha256"],
            }
        )

    registry_exposures: list[dict[str, object]] = []
    registry_reference_reviews: list[dict[str, object]] = []
    participant_roles = {
        "reviewer-a": ["listener"],
        "reviewer-b": ["listener"],
        "adjudicator-c": ["adjudicator"],
        "locale-reviewer-d": ["localeReviewer"],
        "rights-owner-d": ["rightsDecisionOwner"],
    }
    registry_participants: list[dict[str, object]] = []
    for participant_id, roles in participant_roles.items():
        authorization_path = root / f"participant-{participant_id}.json"
        write_json(
            authorization_path,
            {
                "schemaVersion": 1,
                "participantId": participant_id,
                "roles": roles,
            },
        )
        registry_participants.append(
            {
                "participantId": participant_id,
                "roles": roles,
                "authorizationPath": authorization_path.name,
                "authorizationSha256": file_sha256(authorization_path),
            }
        )
    exposure_index = 0
    for case in manifest["cases"]:  # type: ignore[union-attr]
        corpus = case["corpus"]
        audio = case["audio"]
        reference = case["reference"]
        candidate_by_identity = {
            (candidate["id"], candidate["revision"]): candidate
            for candidate in candidate_models
        }
        review_model_exposures = [
            {
                "modelId": exposure["modelId"],
                "modelRevision": exposure["modelRevision"],
                "candidateLockSha256": candidate_by_identity[
                    (exposure["modelId"], exposure["modelRevision"])
                ]["candidateLockSha256"],
                "status": exposure["status"],
                "freezeEvidenceSha256": candidate_by_identity[
                    (exposure["modelId"], exposure["modelRevision"])
                ]["freezeEvidenceSha256"],
            }
            for exposure in case["modelExposure"]
        ]
        case_policy_sha256 = evaluation_policy_sha256(
            language_bcp47=reference["languageBcp47"],
            scoring_profile=reference["scoringProfile"],
            punctuation_profile=reference["punctuationProfile"],
            critical_token_set_sha256=reference["criticalTokenSetSha256"],
        )
        upstream_reference_sha256 = receipt_hash(
            f"{case['id']}:upstream-reference"
        )
        supporting_artifacts: list[dict[str, object]] = []

        def add_supporting_artifact(
            kind: str,
            participant_id: str | None,
            value: object,
        ) -> str:
            artifact_path = (
                root / f"{case['id']}-{kind}-{len(supporting_artifacts)}.json"
            )
            write_json(artifact_path, value)
            artifact_sha256 = file_sha256(artifact_path)
            supporting_artifacts.append(
                {
                    "kind": kind,
                    "participantId": participant_id,
                    "artifactPath": artifact_path.name,
                    "artifactSha256": artifact_sha256,
                }
            )
            return artifact_sha256

        assignment_sha256 = add_supporting_artifact(
            "blindAssignment",
            None,
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "reviewerIds": ["reviewer-a", "reviewer-b"],
                "audioSha256": audio["sha256"],
                "upstreamReferenceSha256": upstream_reference_sha256,
                "excludedInputs": ["modelHypotheses", "peerReviews"],
            },
        )
        first_reviewed_reference_sha256 = reference["sha256"]
        first_review_receipt_sha256 = add_supporting_artifact(
            "listenerReview",
            "reviewer-a",
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "reviewerId": "reviewer-a",
                "assignmentSha256": assignment_sha256,
                "audioSha256": audio["sha256"],
                "upstreamReferenceSha256": upstream_reference_sha256,
                "completedAtUtc": "2026-07-20T13:00:00Z",
                "decision": "pass",
                "reviewedReferenceSha256": first_reviewed_reference_sha256,
            },
        )
        second_reviewed_reference_sha256 = reference["sha256"]
        second_review_receipt_sha256 = add_supporting_artifact(
            "listenerReview",
            "reviewer-b",
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "reviewerId": "reviewer-b",
                "assignmentSha256": assignment_sha256,
                "audioSha256": audio["sha256"],
                "upstreamReferenceSha256": upstream_reference_sha256,
                "completedAtUtc": "2026-07-20T14:00:00Z",
                "decision": "pass",
                "reviewedReferenceSha256": second_reviewed_reference_sha256,
            },
        )
        locale_basis_kind = (
            "humanLocaleAdjudication"
            if "-" in reference["languageBcp47"]
            else "sourceLanguageMarker"
        )
        locale_basis_receipt_sha256 = add_supporting_artifact(
            "localeBasis",
            "locale-reviewer-d",
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "reviewerId": "locale-reviewer-d",
                "languageBcp47": reference["languageBcp47"],
                "basisKind": locale_basis_kind,
            },
        )
        adjudication_receipt_sha256 = add_supporting_artifact(
            "adjudication",
            "adjudicator-c",
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "adjudicatorId": "adjudicator-c",
                "reviewReceiptSha256s": [
                    first_review_receipt_sha256,
                    second_review_receipt_sha256,
                ],
                "finalReferenceSha256": reference["sha256"],
                "decision": "pass",
                "languageBcp47": reference["languageBcp47"],
                "localeReviewerId": "locale-reviewer-d",
                "localeBasisKind": locale_basis_kind,
                "localeBasisReceiptSha256": locale_basis_receipt_sha256,
                "knownDefectCodes": case["knownDefects"],
                "overrideReasonCodes": [],
                "completedAtUtc": "2026-07-20T15:00:00Z",
            },
        )
        rights_owner_receipt_sha256 = add_supporting_artifact(
            "rightsDecision",
            "rights-owner-d",
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "decisionOwnerId": "rights-owner-d",
                **case["rights"],
            },
        )
        attribution_receipt_sha256 = add_supporting_artifact(
            "attribution",
            None,
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "attributionUri": corpus["sourceUri"],
                "verified": True,
            },
        )
        source_identity_receipt_sha256 = add_supporting_artifact(
            "sourceIdentity",
            None,
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "corpusId": corpus["id"],
                "corpusRelease": corpus["release"],
                "corpusSplit": corpus["split"],
                "sourceItemId": corpus["itemId"],
                "corpusSourceUri": corpus["sourceUri"],
                "audioUri": "https://example.invalid/original.mpg",
                "referenceUri": "https://example.invalid/reference.docx",
                "legalNoticeUri": "https://example.invalid/legal-notice",
                "indexSnapshotSha256": receipt_hash(
                    f"{case['id']}:index-snapshot"
                ),
                "recordedAtUtc": audio["recordedAtUtc"],
                "retrievedAtUtc": corpus["retrievedAtUtc"],
                "originalAudioSha256": receipt_hash(
                    f"{case['id']}:original-audio"
                ),
                "upstreamReferenceSha256": upstream_reference_sha256,
                "legalNoticeSha256": case["rights"]["licenseTextSha256"],
                "verified": True,
            },
        )
        preprocessing_receipt_sha256 = add_supporting_artifact(
            "preprocessing",
            None,
            {
                "schemaVersion": 1,
                "caseId": case["id"],
                "assignmentSha256": assignment_sha256,
                "originalAudioSha256": receipt_hash(
                    f"{case['id']}:original-audio"
                ),
                "recipeRevision": "exact-source-trim-v1",
                "decodedAudioSha256": receipt_hash(
                    f"{case['id']}:decoded-source"
                ),
                "trimStartSample": 0,
                "trimDurationSamples": audio["durationSamples"],
                "sampleRateHz": 16_000,
                "channels": 1,
                "audioSha256": audio["sha256"],
                "decodedPcmSha256": audio["decodedPcmSha256"],
                "verified": True,
            },
        )
        review_payload = transcript_reference_review_fixture(
            case_id=case["id"],
            corpus_id=corpus["id"],
            corpus_release=corpus["release"],
            corpus_split=corpus["split"],
            source_item_id=corpus["itemId"],
            corpus_source_uri=corpus["sourceUri"],
            suite_ids=case["suiteIds"],
            condition_labels=case["conditionLabels"],
            audio_byte_length=audio["byteLength"],
            audio_codec=audio["codec"],
            reference_tier=reference["tier"],
            reference_revision=reference["revision"],
            speaker_count=reference["speakerCount"],
            timing_kind=reference["timingKind"],
            recorded_at_utc=audio["recordedAtUtc"],
            retrieved_at_utc=corpus["retrievedAtUtc"],
            language_bcp47=reference["languageBcp47"],
            audio_sha256=audio["sha256"],
            decoded_pcm_sha256=audio["decodedPcmSha256"],
            reference_sha256=reference["sha256"],
            evaluation_policy_sha256=case_policy_sha256,
            license_text_sha256=case["rights"]["licenseTextSha256"],
            license_id=case["rights"]["licenseId"],
            audio_rights_decision=case["rights"]["audioDecision"],
            reference_rights_decision=case["rights"]["referenceDecision"],
            commercial_use=case["rights"]["commercialUse"],
            redistribution=case["rights"]["redistribution"],
            reidentification_prohibited=case["rights"][
                "reidentificationProhibited"
            ],
            known_defect_codes=case["knownDefects"],
            trim_start_sample=0,
            trim_duration_samples=audio["durationSamples"],
            assignment_sha256=assignment_sha256,
            first_review_receipt_sha256=first_review_receipt_sha256,
            second_review_receipt_sha256=second_review_receipt_sha256,
            adjudication_receipt_sha256=adjudication_receipt_sha256,
            locale_basis_receipt_sha256=locale_basis_receipt_sha256,
            rights_owner_receipt_sha256=rights_owner_receipt_sha256,
            attribution_receipt_sha256=attribution_receipt_sha256,
            source_identity_receipt_sha256=source_identity_receipt_sha256,
            preprocessing_receipt_sha256=preprocessing_receipt_sha256,
            locale_basis_kind=locale_basis_kind,
            model_exposures=review_model_exposures,
        )
        if case["purpose"] == "independentPromotion" and include_reference_review:
            review_path = root / f"review-{case['id']}.json"
            write_json(review_path, review_payload)
            registry_reference_reviews.append(
                {
                    "caseId": case["id"],
                    "reviewReceiptPath": review_path.name,
                    "reviewReceiptSha256": file_sha256(review_path),
                    "supportingArtifacts": supporting_artifacts,
                }
            )
        for exposure in case["modelExposure"]:
            evidence_path = root / f"exposure-{exposure_index}.json"
            evidence_path.write_bytes(
                f"exposure-evidence-{exposure_index}".encode()
            )
            exposure["evidenceSha256"] = file_sha256(evidence_path)
            registry_exposures.append(
                {
                    "caseId": case["id"],
                    "corpusId": corpus["id"],
                    "corpusRelease": corpus["release"],
                    "corpusSplit": corpus["split"],
                    "sourceItemId": corpus["itemId"],
                    "audioSha256": audio["sha256"],
                    "decodedPcmSha256": audio["decodedPcmSha256"],
                    "referenceSha256": reference["sha256"],
                    "evaluationPolicySha256": case_policy_sha256,
                    "modelId": exposure["modelId"],
                    "modelRevision": exposure["modelRevision"],
                    "status": exposure["status"],
                    "recordedAtUtc": audio["recordedAtUtc"],
                    "evidenceUri": exposure["evidenceUri"],
                    "evidencePath": evidence_path.name,
                    "evidenceSha256": exposure["evidenceSha256"],
                }
            )
            exposure_index += 1

    registry_path = root / "promotion-registry.json"
    write_json(
        registry_path,
        {
            "schemaVersion": 2,
            "scorerLockPath": scorer_lock_path.name,
            "scorerLockSha256": manifest["scorerLockSha256"],
            "candidateModels": registry_models,
            "trustedReviewParticipants": registry_participants,
            "verifiedExposures": registry_exposures,
            "verifiedReferenceReviews": registry_reference_reviews,
        },
    )
    manifest_path = root / "corpus-manifest.json"
    write_json(manifest_path, manifest)
    environ = {
        "YAP_EVAL_CACHE": str(root),
        "YAP_EVAL_PROMOTION_REGISTRY_SHA256": file_sha256(registry_path),
    }
    return manifest_path, registry_path, environ
