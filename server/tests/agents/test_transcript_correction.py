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
    protected_transcript_spans,
    transcript_correction_response_schema,
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
    authorized_replacements: tuple[tuple[str, str], ...] = (),
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
        TranscriptCorrectionTerminology(
            "c" * 64,
            terminology,
            authorized_replacements,
        ),
    )


def _response(
    request: BoundTranscriptCorrectionRequest,
    *,
    edits: list[dict[str, object]],
    uncertain: bool = False,
) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "requestSha256": correction_request_sha256(request),
        "sourceSha256": request.source_sha256,
        "uncertain": uncertain,
        "edits": edits,
    }


class TranscriptCorrectionTests(unittest.TestCase):
    def test_authorized_terminology_mapping_is_canonical_and_server_bound(self) -> None:
        invalid = (
            (("variant", "unapproved"),),
            (("same", "same"),),
            (("zeta", "dosage"), ("alpha", "dosage")),
            (("Variant", "dosage"), ("variant", "dosage")),
        )
        for replacements in invalid:
            with self.subTest(replacements=replacements), self.assertRaises(
                (TypeError, ValueError)
            ):
                TranscriptCorrectionTerminology(
                    "c" * 64,
                    ("dosage",),
                    replacements,
                )

    def test_server_applies_only_whole_token_authorized_terminology_replacements(
        self,
    ) -> None:
        request = _request(
            first_text="Rivera says the doasge remains stable. ",
            second_text="A doasgeable label and 25 remain unchanged.",
            terminology=("dosage", "30", "Riviera"),
            authorized_replacements=(
                ("25", "30"),
                ("doasge", "dosage"),
                ("Rivera", "Riviera"),
            ),
        )

        correction = validate_transcript_correction(
            request,
            parse_transcript_correction_response(_response(request, edits=[])),
        )

        self.assertEqual(
            correction.corrected_text,
            "Rivera says the dosage remains stable. "
            "A doasgeable label and 25 remain unchanged.",
        )
        self.assertEqual(len(correction.edits), 1)
        self.assertEqual(correction.edits[0].source_text, "doasge")
        self.assertEqual(correction.edits[0].replacement_text, "dosage")

    def test_authorized_terminology_is_bound_into_request_identity(self) -> None:
        without_replacement = _request(
            first_text="The doasge remains stable. ",
            terminology=("dosage",),
            authorized_replacements=(),
        )
        with_replacement = _request(
            first_text="The doasge remains stable. ",
            terminology=("dosage",),
            authorized_replacements=(("doasge", "dosage"),),
        )

        self.assertNotEqual(
            correction_request_sha256(without_replacement),
            correction_request_sha256(with_replacement),
        )
        self.assertEqual(
            with_replacement.to_wire()["authorizedTerminologyReplacements"],
            [{"source": "doasge", "replacement": "dosage"}],
        )
        self.assertEqual(with_replacement.to_wire()["schemaVersion"], 2)

    def test_authorized_terminology_overrides_conflicting_model_edit(self) -> None:
        request = _request(
            first_text="The tavi plan is ready. ",
            terminology=("transcatheter aortic valve implantation",),
            authorized_replacements=(
                ("tavi", "transcatheter aortic valve implantation"),
            ),
        )
        proposed = {
            "segmentId": "segment-0001",
            "segmentSha256": request.segments[0].text_sha256,
            "sourceText": "tavi",
            "replacementText": "taxi",
        }

        correction = validate_transcript_correction(
            request,
            parse_transcript_correction_response(
                _response(request, edits=[proposed])
            ),
        )

        self.assertEqual(
            correction.corrected_text,
            "The transcatheter aortic valve implantation plan is ready. "
            "Um, the follow-up is tomorrow.",
        )

    def test_uncertainty_preserves_raw_source_despite_authorized_replacement(self) -> None:
        request = _request(
            first_text="The doasge remains unclear. ",
            terminology=("dosage",),
            authorized_replacements=(("doasge", "dosage"),),
        )

        correction = validate_transcript_correction(
            request,
            parse_transcript_correction_response(
                _response(request, edits=[], uncertain=True)
            ),
        )

        self.assertEqual(
            apply_validated_transcript_correction(request, correction),
            request.source_text,
        )

    def test_protected_spans_match_validation_categories(self) -> None:
        request = _request(
            first_text=(
                "Dr. Rivera did Not prescribe 25 MG Metoprolol on 2026-08-11. "
            )
        )

        self.assertEqual(
            tuple(span.text for span in protected_transcript_spans(request)),
            (
                "Dr",
                "Rivera",
                "Not",
                "25",
                "MG",
                "Metoprolol",
                "2026-08-11",
                "follow-up",
            ),
        )
        with self.assertRaisesRegex(TypeError, "request type"):
            protected_transcript_spans(object())  # type: ignore[arg-type]

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
                        "sourceText": "Um, t",
                        "replacementText": "T",
                    }
                ],
            )
        )
        validated = validate_transcript_correction(request, parsed)
        self.assertEqual(validated.edits[0].start_character, 0)
        self.assertEqual(validated.edits[0].end_character, 5)

        self.assertEqual(
            apply_validated_transcript_correction(request, validated),
            "Dr. Rivera did not prescribe 25 mg metoprolol on 2026-08-11. The follow-up is tomorrow.",
        )
        self.assertEqual(
            request.source_text,
            "Dr. Rivera did not prescribe 25 mg metoprolol on 2026-08-11. Um, the follow-up is tomorrow.",
        )

    def test_server_derives_unicode_character_span_from_unique_source_quote(
        self,
    ) -> None:
        request = _request(second_text="Sí, um, the follow-up is tomorrow.")
        segment = request.segments[1]
        parsed = parse_transcript_correction_response(
            _response(
                request,
                edits=[
                    {
                        "segmentId": segment.segment_id,
                        "segmentSha256": segment.text_sha256,
                        "sourceText": "um, t",
                        "replacementText": "t",
                    }
                ],
            )
        )

        validated = validate_transcript_correction(request, parsed)

        self.assertEqual(validated.edits[0].start_character, 4)
        self.assertEqual(validated.edits[0].end_character, 9)

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
                parsed = parse_transcript_correction_response(
                    _response(
                        request,
                        edits=[
                            {
                                "segmentId": first.segment_id,
                                "segmentSha256": first.text_sha256,
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
        parsed = parse_transcript_correction_response(
            _response(
                request,
                edits=[
                    {
                        "segmentId": second.segment_id,
                        "segmentSha256": second.text_sha256,
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
                parsed = parse_transcript_correction_response(
                    _response(
                        request,
                        edits=[
                            {
                                "segmentId": first.segment_id,
                                "segmentSha256": first.text_sha256,
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
                parsed = parse_transcript_correction_response(
                    _response(
                        request,
                        edits=[
                            {
                                "segmentId": second.segment_id,
                                "segmentSha256": second.text_sha256,
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
        parsed = parse_transcript_correction_response(
            _response(
                request,
                edits=[
                    {
                        "segmentId": second.segment_id,
                        "segmentSha256": second.text_sha256,
                        "sourceText": source_text,
                        "replacementText": "approved",
                    }
                ],
            )
        )
        with self.assertRaisesRegex(ValueError, "not a bounded correction"):
            validate_transcript_correction(request, parsed)

    def test_response_source_binding_derived_spans_and_order_fail_closed(self) -> None:
        request = _request()
        second = request.segments[1]
        valid = {
            "segmentId": second.segment_id,
            "segmentSha256": second.text_sha256,
            "sourceText": "Um, t",
            "replacementText": "T",
        }
        mutations = (
            {**valid, "segmentId": "missing"},
            {**valid, "segmentSha256": "b" * 64},
            {**valid, "sourceText": "Er, "},
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
                "sourceText": " th",
                "replacementText": " Th",
            },
        ]
        parsed = parse_transcript_correction_response(
            _response(request, edits=overlapping)
        )
        with self.assertRaisesRegex(ValueError, "ordered and non-overlapping"):
            validate_transcript_correction(request, parsed)

        repeated = _request(second_text="um, um, the follow-up is tomorrow.")
        parsed = parse_transcript_correction_response(
            _response(
                repeated,
                edits=[
                    {
                        "segmentId": repeated.segments[1].segment_id,
                        "segmentSha256": repeated.segments[1].text_sha256,
                        "sourceText": "um",
                        "replacementText": "uh",
                    }
                ],
            )
        )
        with self.assertRaisesRegex(ValueError, "edit source differs"):
            validate_transcript_correction(repeated, parsed)

    def test_response_requires_exact_request_and_source_identity(self) -> None:
        request = _request()
        schema = transcript_correction_response_schema(request)
        self.assertEqual(
            schema["properties"]["requestSha256"]["const"],
            correction_request_sha256(request),
        )
        self.assertEqual(
            schema["properties"]["sourceSha256"]["const"],
            request.source_sha256,
        )
        edit_schema = schema["properties"]["edits"]["items"]
        self.assertEqual(
            set(edit_schema["properties"]),
            {"segmentId", "segmentSha256", "sourceText", "replacementText"},
        )
        for field in ("requestSha256", "sourceSha256"):
            value = _response(request, edits=[])
            value[field] = "b" * 64
            parsed = parse_transcript_correction_response(value)
            with self.assertRaisesRegex(ValueError, "identity differs"):
                validate_transcript_correction(request, parsed)

    def test_unknown_keys_and_noncanonical_types_are_rejected(self) -> None:
        request = _request()
        value = _response(request, edits=[])
        value["schemaVersion"] = 1
        with self.assertRaisesRegex(ValueError, "schema differs"):
            parse_transcript_correction_response(value)

        value = _response(request, edits=[])
        value["extra"] = True
        with self.assertRaisesRegex(ValueError, "shape"):
            parse_transcript_correction_response(value)

        value = _response(request, edits=[])
        value["uncertain"] = 0
        with self.assertRaisesRegex(TypeError, "uncertain"):
            parse_transcript_correction_response(value)

        segment = request.segments[1]
        value = _response(
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
        with self.assertRaisesRegex(ValueError, "edit shape"):
            parse_transcript_correction_response(value)


if __name__ == "__main__":
    unittest.main()
