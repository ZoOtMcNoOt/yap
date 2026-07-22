from __future__ import annotations

from dataclasses import replace
import unittest

from yap_server.evaluation.promotion_reference_review import (
    validate_promotion_reference_review,
)
from yap_server.evaluation.transcript_reference_review import (
    validate_transcript_reference_review_receipt,
)
from tests.evaluation.transcript_reference_review_fixture import (
    receipt_hash,
    transcript_reference_review_fixture,
)


def _validated_receipt():
    return validate_transcript_reference_review_receipt(
        transcript_reference_review_fixture()
    )


def _arguments(receipt) -> dict[str, object]:
    return {
        "case_id": receipt.case_id,
        "corpus_id": receipt.corpus_id,
        "corpus_release": receipt.corpus_release,
        "corpus_split": receipt.corpus_split,
        "source_item_id": receipt.source_item_id,
        "source_uri": receipt.corpus_source_uri,
        "suite_ids": receipt.suite_ids,
        "condition_labels": receipt.condition_labels,
        "audio_sha256": receipt.audio_sha256,
        "audio_byte_length": receipt.audio_byte_length,
        "decoded_pcm_sha256": receipt.decoded_pcm_sha256,
        "duration_samples": receipt.duration_samples,
        "sample_rate_hz": receipt.sample_rate_hz,
        "channels": receipt.channels,
        "audio_codec": receipt.audio_codec,
        "reference_sha256": receipt.reference_sha256,
        "evaluation_policy_sha256": receipt.evaluation_policy_sha256,
        "language_bcp47": receipt.language_bcp47,
        "reference_tier": receipt.reference_tier,
        "reference_revision": receipt.reference_revision,
        "speaker_count": receipt.speaker_count,
        "timing_kind": receipt.timing_kind,
        "recorded_at": receipt.recorded_at_utc,
        "retrieved_at": receipt.retrieved_at_utc,
        "license_id": receipt.rights.license_id,
        "license_text_sha256": receipt.rights.license_text_sha256,
        "audio_rights_decision": receipt.rights.audio_decision,
        "reference_rights_decision": receipt.rights.reference_decision,
        "commercial_use": receipt.rights.commercial_use,
        "redistribution": receipt.rights.redistribution,
        "reidentification_prohibited": receipt.rights.reidentification_prohibited,
        "known_defect_codes": receipt.known_defect_codes,
        "candidate_models": {
            (exposure.model_id, exposure.model_revision): (
                exposure.candidate_lock_sha256,
                exposure.freeze_evidence_sha256,
            )
            for exposure in receipt.model_exposures
        },
        "exposure_statuses": {
            (exposure.model_id, exposure.model_revision): exposure.status
            for exposure in receipt.model_exposures
        },
    }


class PromotionReferenceReviewTests(unittest.TestCase):
    def test_one_receipt_binds_the_case_locale_and_complete_candidate_set(self) -> None:
        receipt = _validated_receipt()

        validate_promotion_reference_review(
            receipt,
            **_arguments(receipt),
        )

    def test_receipt_cannot_relabel_the_locale_or_reference(self) -> None:
        receipt = _validated_receipt()
        for field, value in (
            ("language_bcp47", "es-US"),
            ("reference_sha256", receipt_hash("different-reference")),
            ("audio_sha256", receipt_hash("different-audio")),
        ):
            with self.subTest(field=field):
                arguments = _arguments(receipt)
                arguments[field] = value
                with self.assertRaisesRegex(ValueError, "does not match"):
                    validate_promotion_reference_review(
                        receipt,
                        **arguments,
                    )

    def test_receipt_must_cover_every_frozen_candidate_and_exposure_state(self) -> None:
        receipt = _validated_receipt()
        arguments = _arguments(receipt)
        candidate_models = dict(arguments["candidate_models"])
        candidate_models[("third/model", "revision-3")] = (
            receipt_hash("third-lock"),
            receipt_hash("third-freeze"),
        )
        arguments["candidate_models"] = candidate_models
        arguments["exposure_statuses"] = {
            **arguments["exposure_statuses"],
            ("third/model", "revision-3"): "created_after_model_freeze",
        }
        with self.assertRaisesRegex(ValueError, "omits a frozen candidate"):
            validate_promotion_reference_review(
                receipt,
                **arguments,
            )

        changed = replace(
            receipt.model_exposures[0],
            status="contractually_excluded",
        )
        changed_receipt = replace(
            receipt,
            model_exposures=(changed, *receipt.model_exposures[1:]),
        )
        with self.assertRaisesRegex(ValueError, "differs from the freeze"):
            validate_promotion_reference_review(
                changed_receipt,
                **_arguments(receipt),
            )

    def test_matching_fractional_recording_time_is_preserved(self) -> None:
        receipt = validate_transcript_reference_review_receipt(
            transcript_reference_review_fixture(
                recorded_at_utc="2026-07-08T10:00:00.500Z"
            )
        )
        arguments = _arguments(receipt)
        arguments["recorded_at"] = receipt.recorded_at_utc

        validate_promotion_reference_review(
            receipt,
            **arguments,
        )


if __name__ == "__main__":
    unittest.main()
