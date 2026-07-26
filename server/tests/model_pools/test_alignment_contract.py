from __future__ import annotations

import unittest

from yap_server.alignment_contract import (
    ALIGNMENT_COMPONENT_REVISION,
    AlignedWordEvidence,
    AlignmentUnavailable,
    AlignmentUnavailableReason,
    available_alignment,
    unavailable_alignment,
    validate_alignment_payload,
)


class AlignmentContractTests(unittest.TestCase):
    def test_serializes_available_and_typed_unavailable_outcomes(self) -> None:
        word = AlignedWordEvidence(0, "hello", 0, 10)

        self.assertEqual(
            available_alignment((word,)),
            {
                "status": "available",
                "reason": None,
                "componentRevision": ALIGNMENT_COMPONENT_REVISION,
                "alignedWords": [word.to_result()],
            },
        )
        self.assertEqual(
            unavailable_alignment(AlignmentUnavailableReason.PROVIDER_UNSUPPORTED),
            {
                "status": "unavailable",
                "reason": "ALIGNMENT_PROVIDER_UNSUPPORTED",
                "componentRevision": ALIGNMENT_COMPONENT_REVISION,
                "alignedWords": [],
            },
        )

    def test_payload_validation_rejects_noncanonical_text_and_invalid_bounds(self) -> None:
        payload = unavailable_alignment(AlignmentUnavailableReason.RUNTIME_FAILED)
        with self.assertRaisesRegex(ValueError, "canonical"):
            validate_alignment_payload(payload, transcript=" hello")
        with self.assertRaisesRegex(ValueError, "source duration"):
            validate_alignment_payload(payload, transcript="", maximum_end_ms=True)
        with self.assertRaises(AlignmentUnavailable):
            available_alignment((AlignedWordEvidence(0, "two words", 0, 10),))

    def test_available_payload_preserves_exact_text_and_source_bounds(self) -> None:
        payload = available_alignment(
            (
                AlignedWordEvidence(0, "hello", 0, 10),
                AlignedWordEvidence(1, "world", 10, 20),
            )
        )

        validate_alignment_payload(
            payload,
            transcript="hello world",
            maximum_end_ms=20,
        )
        payload["alignedWords"][1]["endMs"] = 21
        with self.assertRaisesRegex(ValueError, "aligned word content"):
            validate_alignment_payload(
                payload,
                transcript="hello world",
                maximum_end_ms=20,
            )


if __name__ == "__main__":
    unittest.main()
