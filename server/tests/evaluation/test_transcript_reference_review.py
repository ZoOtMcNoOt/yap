from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yap_server import private_artifact
from yap_server.private_artifact import (
    read_bounded_regular_file,
)
from yap_server.evaluation.transcript_reference_review import (
    load_transcript_reference_review_receipt,
    validate_transcript_reference_review_receipt,
)
from tests.evaluation.transcript_reference_review_fixture import (
    receipt_hash as _hash,
    transcript_reference_review_fixture as _receipt,
)


class TranscriptReferenceReviewTests(unittest.TestCase):
    def test_bounded_read_checks_the_opened_handle_against_its_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            artifact = root / "review.json"
            artifact.write_bytes(b"{}")

            with patch.object(
                private_artifact,
                "_opened_file_path",
                return_value=outside / "review.json",
            ):
                with self.assertRaisesRegex(ValueError, "changed before it was opened"):
                    read_bounded_regular_file(
                        artifact,
                        maximum_bytes=16,
                        field="review artifact",
                        containment_root=root,
                    )

    def test_valid_receipt_returns_only_hash_bound_promotion_identity(self) -> None:
        validated = validate_transcript_reference_review_receipt(_receipt())

        self.assertEqual(validated.case_id, "europarl-es-001")
        self.assertEqual(validated.language_bcp47, "es-ES")
        self.assertEqual(validated.audio_sha256, _hash("europarl-es-001:trimmed-wav"))
        self.assertEqual(
            validated.decoded_pcm_sha256, _hash("europarl-es-001:final-pcm")
        )
        self.assertEqual(
            validated.reference_sha256, _hash("europarl-es-001:final-reference")
        )
        self.assertEqual(len(validated.model_exposures), 2)

    def test_contract_rejects_content_and_path_fields(self) -> None:
        for field, value in (
            ("transcript", "private words"),
            ("audioPath", "C:/private/audio.wav"),
            ("referencePath", "/private/reference.txt"),
        ):
            with self.subTest(field=field):
                payload = _receipt()
                payload[field] = value
                with self.assertRaisesRegex(ValueError, "fields differ"):
                    validate_transcript_reference_review_receipt(payload)

    def test_exactly_two_distinct_reviewers_must_review_identical_inputs(self) -> None:
        mutations = {
            "one review": lambda payload: payload.__setitem__(
                "reviews", payload["reviews"][:1]
            ),
            "duplicate reviewer": lambda payload: payload["reviews"][1].__setitem__(
                "reviewerId", "reviewer-a"
            ),
            "assignment mismatch": lambda payload: payload["reviews"][1].__setitem__(
                "assignmentSha256", _hash("other-assignment")
            ),
            "audio mismatch": lambda payload: payload["reviews"][1].__setitem__(
                "audioSha256", _hash("other-audio")
            ),
            "upstream mismatch": lambda payload: payload["reviews"][1].__setitem__(
                "upstreamReferenceSha256", _hash("other-reference")
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                payload = _receipt()
                mutate(payload)
                with self.assertRaises(ValueError):
                    validate_transcript_reference_review_receipt(payload)

    def test_pass_requires_independent_final_adjudication_and_approved_rights(
        self,
    ) -> None:
        mutations = {
            "reviewer adjudicates": lambda payload: payload["adjudication"].__setitem__(
                "adjudicatorId", "reviewer-a"
            ),
            "review receipt mismatch": lambda payload: payload[
                "adjudication"
            ].__setitem__(
                "reviewReceiptSha256s",
                [_hash("other-a"), _hash("other-b")],
            ),
            "reference hold": lambda payload: payload["rights"].__setitem__(
                "referenceDecision", "hold"
            ),
            "nonfinal adjudication": lambda payload: payload[
                "adjudication"
            ].__setitem__("decision", "hold"),
            "locale disagreement": lambda payload: payload["adjudication"].__setitem__(
                "languageBcp47", "es-US"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                payload = _receipt()
                mutate(payload)
                with self.assertRaises(ValueError):
                    validate_transcript_reference_review_receipt(payload)

    def test_candidate_exposure_set_is_unique_and_complete_for_the_packet(self) -> None:
        duplicate = _receipt()
        duplicate["modelExposure"][1]["modelId"] = duplicate["modelExposure"][0][
            "modelId"
        ]
        duplicate["modelExposure"][1]["modelRevision"] = duplicate["modelExposure"][0][
            "modelRevision"
        ]
        with self.assertRaisesRegex(ValueError, "model exposure.*unique"):
            validate_transcript_reference_review_receipt(duplicate)

        missing = _receipt()
        missing["modelExposure"] = missing["modelExposure"][:1]
        validated = validate_transcript_reference_review_receipt(missing)
        self.assertEqual(len(validated.model_exposures), 1)

    def test_locale_subtags_require_human_locale_adjudication(self) -> None:
        payload = _receipt(locale_basis_kind="sourceLanguageMarker")
        with self.assertRaisesRegex(ValueError, "human locale adjudication"):
            validate_transcript_reference_review_receipt(payload)

        unsupported_source_claim = _receipt()
        unsupported_source_claim["adjudication"]["localeBasisKind"] = (
            "sourceRegionalMetadata"
        )
        with self.assertRaisesRegex(ValueError, "locale basis kind"):
            validate_transcript_reference_review_receipt(unsupported_source_claim)

        base_language = _receipt(
            language_bcp47="es",
            locale_basis_kind="sourceLanguageMarker",
        )
        self.assertEqual(
            validate_transcript_reference_review_receipt(base_language).language_bcp47,
            "es",
        )

        three_letter_language = _receipt(
            language_bcp47="yue",
            locale_basis_kind="sourceLanguageMarker",
        )
        self.assertEqual(
            validate_transcript_reference_review_receipt(
                three_letter_language
            ).language_bcp47,
            "yue",
        )

    def test_adjudicator_must_explain_a_changed_listener_result(self) -> None:
        payload = _receipt()
        payload["reviews"][0]["decision"] = "exclude"
        with self.assertRaisesRegex(ValueError, "changed listener result"):
            validate_transcript_reference_review_receipt(payload)

        payload["adjudication"]["overrideReasonCodes"] = ["listener-disagreement"]
        validate_transcript_reference_review_receipt(payload)

        changed_reference = _receipt()
        changed_reference["reviews"][0]["reviewedReferenceSha256"] = _hash(
            "different-listener-reference"
        )
        with self.assertRaisesRegex(ValueError, "changed listener result"):
            validate_transcript_reference_review_receipt(changed_reference)

        changed_reference["adjudication"]["overrideReasonCodes"] = [
            "listener-reference-divergence"
        ]
        validate_transcript_reference_review_receipt(changed_reference)

    def test_loader_rejects_receipt_tampering_against_the_registry_hash(self) -> None:
        payload = _receipt()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "review-receipt.json"
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            path.write_bytes(encoded)
            expected_sha256 = hashlib.sha256(encoded).hexdigest()

            loaded = load_transcript_reference_review_receipt(
                path, expected_sha256=expected_sha256
            )
            self.assertEqual(loaded.case_id, payload["caseId"])

            tampered = deepcopy(payload)
            tampered["caseId"] = "europarl-es-tampered"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "trusted registry"):
                load_transcript_reference_review_receipt(
                    path, expected_sha256=expected_sha256
                )

    def test_loader_rejects_duplicate_json_keys_even_when_the_hash_matches(
        self,
    ) -> None:
        payload = _receipt()
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = encoded.replace(
            b'"disposition":"pass"',
            b'"disposition":"exclude","disposition":"pass"',
            1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate-key-review.json"
            path.write_bytes(encoded)

            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_transcript_reference_review_receipt(
                    path,
                    expected_sha256=hashlib.sha256(encoded).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
