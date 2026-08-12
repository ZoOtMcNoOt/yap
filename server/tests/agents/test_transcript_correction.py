from __future__ import annotations

import hashlib
import unittest

from yap_server.agents.transcript_correction import (
    BoundTranscriptCorrectionRequest,
    TranscriptCorrectionRequest,
    TranscriptCorrectionTerminology,
    apply_validated_transcript_correction,
    bind_transcript_correction_request,
    correction_request_sha256,
    parse_transcript_correction_response,
    validate_transcript_correction,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(
    *,
    first_text: str = (
        "Dr. Rivera did not prescribe 25 mg metoprolol on 2026-08-11. "
    ),
    second_text: str = "Um, the follow-up is tomorrow.",
    terminology: tuple[str, ...] = ("follow-up",),
) -> BoundTranscriptCorrectionRequest:
    first = first_text
    second = second_text
    source = first + second
    source_request = TranscriptCorrectionRequest.from_wire(
        {
            "schemaVersion": 1,
            "sourceRevisionSha256": "a" * 64,
            "sourceSha256": _sha256(source),
            "segments": [
                {
                    "segmentId": "segment-0001",
                    "startCharacter": 0,
                    "endCharacter": len(first),
                    "startMilliseconds": 0,
                    "endMilliseconds": 3_200,
                    "languageBcp47": "en-US",
                    "text": first,
                    "textSha256": _sha256(first),
                },
                {
                    "segmentId": "segment-0002",
                    "startCharacter": len(first),
                    "endCharacter": len(source),
                    "startMilliseconds": 3_200,
                    "endMilliseconds": 5_100,
                    "languageBcp47": "en-US",
                    "text": second,
                    "textSha256": _sha256(second),
                },
            ],
        }
    )
    return bind_transcript_correction_request(
        source_request,
        TranscriptCorrectionTerminology("c" * 64, terminology),
    )


def _response(
    request: BoundTranscriptCorrectionRequest,
    *,
    edits: list[dict[str, object]],
    uncertain: bool = False,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "requestSha256": correction_request_sha256(request),
        "sourceSha256": request.source_sha256,
        "uncertain": uncertain,
        "edits": edits,
    }


class TranscriptCorrectionTests(unittest.TestCase):
    def test_request_requires_exact_contiguous_finalized_source(self) -> None:
        request = _request()
        self.assertEqual(request.source_text, "".join(segment.text for segment in request.segments))

        value = request.source.to_wire()
        value["segments"][1]["startCharacter"] += 1  # type: ignore[index]
        value["segments"][1]["endCharacter"] += 1  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "contiguous"):
            TranscriptCorrectionRequest.from_wire(value)

        value = request.source.to_wire()
        value["segments"][0]["textSha256"] = "b" * 64  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "segment hash"):
            TranscriptCorrectionRequest.from_wire(value)

        value = request.source.to_wire()
        value["sourceSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "source hash"):
            TranscriptCorrectionRequest.from_wire(value)

        value = request.source.to_wire()
        value["segments"][0]["startMilliseconds"] = None  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "start time is invalid"):
            TranscriptCorrectionRequest.from_wire(value)

        value = request.source.to_wire()
        value["approvedTerminology"] = ["caller-selected"]
        with self.assertRaisesRegex(ValueError, "shape differs"):
            TranscriptCorrectionRequest.from_wire(value)

    def test_mixed_finalized_languages_use_an_und_terminology_snapshot_locale(self) -> None:
        value = _request().source.to_wire()
        value["segments"][1]["languageBcp47"] = "es-ES"  # type: ignore[index]
        request = TranscriptCorrectionRequest.from_wire(value)
        self.assertEqual(request.language_bcp47, "und")

    def test_unqualified_language_is_rejected_without_model_work(self) -> None:
        value = _request().source.to_wire()
        value["segments"][0]["languageBcp47"] = "fr-FR"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "language is unsupported"):
            TranscriptCorrectionRequest.from_wire(value)

    def test_server_bound_terminology_identity_changes_request_identity(self) -> None:
        request = _request()
        changed = bind_transcript_correction_request(
            request.source,
            TranscriptCorrectionTerminology("d" * 64, ("follow-up",)),
        )
        self.assertNotEqual(
            correction_request_sha256(request),
            correction_request_sha256(changed),
        )

    def test_safe_source_bound_edit_is_applied_without_rewriting_raw_source(self) -> None:
        request = _request()
        segment = request.segments[1]
        parsed = parse_transcript_correction_response(
            _response(
                request,
                edits=[
                    {
                        "segmentId": segment.segment_id,
                        "segmentSha256": segment.text_sha256,
                        "startCharacter": 0,
                        "endCharacter": 5,
                        "sourceText": "Um, t",
                        "replacementText": "T",
                    }
                ],
            )
        )
        validated = validate_transcript_correction(request, parsed)

        self.assertEqual(
            apply_validated_transcript_correction(request, validated),
            "Dr. Rivera did not prescribe 25 mg metoprolol on 2026-08-11. The follow-up is tomorrow.",
        )
        self.assertEqual(
            request.source_text,
            "Dr. Rivera did not prescribe 25 mg metoprolol on 2026-08-11. Um, the follow-up is tomorrow.",
        )

    def test_uncertain_response_must_be_edit_free_and_returns_raw_source(self) -> None:
        request = _request()
        parsed = parse_transcript_correction_response(
            _response(request, edits=[], uncertain=True)
        )
        validated = validate_transcript_correction(request, parsed)
        self.assertTrue(validated.uncertain)
        self.assertEqual(
            apply_validated_transcript_correction(request, validated),
            request.source_text,
        )

        with self.assertRaisesRegex(ValueError, "uncertain response"):
            parse_transcript_correction_response(
                _response(
                    request,
                    uncertain=True,
                    edits=[
                        {
                            "segmentId": request.segments[0].segment_id,
                            "segmentSha256": request.segments[0].text_sha256,
                            "startCharacter": 0,
                            "endCharacter": 2,
                            "sourceText": "Dr",
                            "replacementText": "Doctor",
                        }
                    ],
                )
            )

    def test_names_numbers_dates_units_medications_negation_and_terms_are_preserved(
        self,
    ) -> None:
        request = _request()
        first = request.segments[0]
        protected_mutations = (
            ("Rivera", "Riviera"),
            ("not", "now"),
            ("25", "20"),
            ("mg", "mL"),
            ("metoprolol", "metropolol"),
            ("2026-08-11", "2026-08-12"),
        )
        for source_text, replacement in protected_mutations:
            with self.subTest(source_text=source_text):
                start = first.text.index(source_text)
                parsed = parse_transcript_correction_response(
                    _response(
                        request,
                        edits=[
                            {
                                "segmentId": first.segment_id,
                                "segmentSha256": first.text_sha256,
                                "startCharacter": start,
                                "endCharacter": start + len(source_text),
                                "sourceText": source_text,
                                "replacementText": replacement,
                            }
                        ],
                    )
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "protected transcript facts|not a bounded correction",
                ):
                    validate_transcript_correction(request, parsed)

        second = request.segments[1]
        start = second.text.index("follow-up")
        parsed = parse_transcript_correction_response(
            _response(
                request,
                edits=[
                    {
                        "segmentId": second.segment_id,
                        "segmentSha256": second.text_sha256,
                        "startCharacter": start,
                        "endCharacter": start + len("follow-up"),
                        "sourceText": "follow-up",
                        "replacementText": "followup",
                    }
                ],
            )
        )
        with self.assertRaisesRegex(ValueError, "protected transcript facts"):
            validate_transcript_correction(request, parsed)

    def test_word_form_numbers_dates_and_units_are_immutable_facts(self) -> None:
        for source_text, replacement_text in (
            ("fifteen", "sixteen"),
            ("Monday", "Tuesday"),
            ("milligrams", "kilograms"),
            ("quince", "dieciseis"),
            ("lunes", "martes"),
            ("miligramos", "kilogramos"),
        ):
            with self.subTest(source_text=source_text):
                request = _request(
                    first_text=f"The value is {source_text}.",
                    second_text="The follow-up is tomorrow.",
                    terminology=(),
                )
                first = request.segments[0]
                start = first.text.index(source_text)
                parsed = parse_transcript_correction_response(
                    _response(
                        request,
                        edits=[
                            {
                                "segmentId": first.segment_id,
                                "segmentSha256": first.text_sha256,
                                "startCharacter": start,
                                "endCharacter": start + len(source_text),
                                "sourceText": source_text,
                                "replacementText": replacement_text,
                            }
                        ],
                    )
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "protected transcript facts|not a bounded correction",
                ):
                    validate_transcript_correction(request, parsed)

    def test_correction_cannot_insert_or_delete_non_filler_words(self) -> None:
        request = _request()
        second = request.segments[1]
        cases = (
            ("tomorrow", "tomorrow after discharge"),
            ("the follow-up", "follow-up"),
        )
        for source_text, replacement_text in cases:
            with self.subTest(source_text=source_text):
                start = second.text.index(source_text)
                parsed = parse_transcript_correction_response(
                    _response(
                        request,
                        edits=[
                            {
                                "segmentId": second.segment_id,
                                "segmentSha256": second.text_sha256,
                                "startCharacter": start,
                                "endCharacter": start + len(source_text),
                                "sourceText": source_text,
                                "replacementText": replacement_text,
                            }
                        ],
                    )
                )
                with self.assertRaisesRegex(ValueError, "not a bounded correction"):
                    validate_transcript_correction(request, parsed)

    def test_unrelated_rewrite_is_not_accepted_as_transcript_correction(self) -> None:
        request = _request()
        second = request.segments[1]
        source_text = "tomorrow"
        start = second.text.index(source_text)
        parsed = parse_transcript_correction_response(
            _response(
                request,
                edits=[
                    {
                        "segmentId": second.segment_id,
                        "segmentSha256": second.text_sha256,
                        "startCharacter": start,
                        "endCharacter": start + len(source_text),
                        "sourceText": source_text,
                        "replacementText": "approved",
                    }
                ],
            )
        )
        with self.assertRaisesRegex(ValueError, "not a bounded correction"):
            validate_transcript_correction(request, parsed)

    def test_response_binding_source_spans_and_order_fail_closed(self) -> None:
        request = _request()
        second = request.segments[1]
        valid = {
            "segmentId": second.segment_id,
            "segmentSha256": second.text_sha256,
            "startCharacter": 0,
            "endCharacter": 5,
            "sourceText": "Um, t",
            "replacementText": "T",
        }
        mutations = (
            {**valid, "segmentId": "missing"},
            {**valid, "segmentSha256": "b" * 64},
            {**valid, "sourceText": "Er, "},
            {**valid, "endCharacter": len(second.text) + 1},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    parsed = parse_transcript_correction_response(
                        _response(request, edits=[mutation])
                    )
                    validate_transcript_correction(request, parsed)

        overlapping = [
            valid,
            {
                **valid,
                "startCharacter": 3,
                "endCharacter": 6,
                "sourceText": " th",
                "replacementText": " Th",
            },
        ]
        parsed = parse_transcript_correction_response(
            _response(request, edits=overlapping)
        )
        with self.assertRaisesRegex(ValueError, "ordered and non-overlapping"):
            validate_transcript_correction(request, parsed)

    def test_response_requires_exact_request_and_source_identity(self) -> None:
        request = _request()
        for field in ("requestSha256", "sourceSha256"):
            value = _response(request, edits=[])
            value[field] = "b" * 64
            parsed = parse_transcript_correction_response(value)
            with self.assertRaisesRegex(ValueError, "identity differs"):
                validate_transcript_correction(request, parsed)

    def test_unknown_keys_and_noncanonical_types_are_rejected(self) -> None:
        request = _request()
        value = _response(request, edits=[])
        value["extra"] = True
        with self.assertRaisesRegex(ValueError, "shape"):
            parse_transcript_correction_response(value)

        value = _response(request, edits=[])
        value["uncertain"] = 0
        with self.assertRaisesRegex(TypeError, "uncertain"):
            parse_transcript_correction_response(value)


if __name__ == "__main__":
    unittest.main()
