from __future__ import annotations

from copy import deepcopy
import unittest

from yap_server.language_span_contract import (
    ServerUtteranceLanguageObservation,
    build_server_language_span_evidence,
    validate_language_span_evidence,
)


MODEL_REVISION = "a" * 40
PLAN_SHA256 = "b" * 64


def _segment(
    text: str,
    *,
    language: str | None,
    status: str = "detected",
) -> dict[str, object]:
    return {
        "text": text,
        "status": status,
        "languageBcp47": language,
    }


def _evidence() -> dict[str, object]:
    return build_server_language_span_evidence(
        source_end_sample=32_000,
        provider_id="nemotron",
        pool_id="nemotron-batch",
        model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
        model_revision=MODEL_REVISION,
        utterance_plan_sha256=PLAN_SHA256,
        utterances=(
            ServerUtteranceLanguageObservation(
                start_sample=0,
                end_sample=16_000,
                language_segments=(_segment("hello", language="en-US"),),
            ),
            ServerUtteranceLanguageObservation(
                start_sample=16_000,
                end_sample=32_000,
                language_segments=(
                    _segment("bonjour", language="fr-FR"),
                    _segment("hello", language="en-US"),
                ),
            ),
        ),
    )


class LanguageSpanContractTests(unittest.TestCase):
    def test_server_spans_bind_complete_source_windows_without_inventing_boundaries(
        self,
    ) -> None:
        evidence = _evidence()

        self.assertEqual(evidence["boundaryAuthority"], "serverUtterance")
        self.assertEqual(
            evidence["spans"],
            [
                {
                    "startSample": 0,
                    "endSample": 16_000,
                    "languageBcp47": "en-US",
                    "decisionRevision": 1,
                    "disposition": "serverDetected",
                    "componentRevision": MODEL_REVISION,
                    "decisionEvidence": None,
                },
                {
                    "startSample": 16_000,
                    "endSample": 32_000,
                    "languageBcp47": "und",
                    "decisionRevision": 2,
                    "disposition": "serverUnknown",
                    "componentRevision": MODEL_REVISION,
                    "decisionEvidence": None,
                },
            ],
        )

    def test_nonempty_unknown_text_makes_the_whole_utterance_unknown(self) -> None:
        evidence = build_server_language_span_evidence(
            source_end_sample=16_000,
            provider_id="nemotron",
            pool_id="nemotron-batch",
            model_id="nvidia/nemotron-3.5-asr-streaming-0.6b",
            model_revision=MODEL_REVISION,
            utterance_plan_sha256=PLAN_SHA256,
            utterances=(
                ServerUtteranceLanguageObservation(
                    start_sample=0,
                    end_sample=16_000,
                    language_segments=(
                        _segment("hello", language="en-US"),
                        _segment("mystery", language=None, status="unknown"),
                    ),
                ),
            ),
        )

        self.assertEqual(evidence["spans"][0]["languageBcp47"], "und")  # type: ignore[index]

    def test_identity_and_complete_coverage_fail_closed(self) -> None:
        evidence = _evidence()
        validate_language_span_evidence(
            evidence,
            expected_source_end_sample=32_000,
            expected_provider_id="nemotron",
            expected_pool_id="nemotron-batch",
            expected_model_revision=MODEL_REVISION,
            expected_utterance_plan_sha256=PLAN_SHA256,
        )

        malformed = deepcopy(evidence)
        malformed["spans"][1]["startSample"] = 15_999  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "content"):
            validate_language_span_evidence(malformed)

        wrong_plan = deepcopy(evidence)
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_language_span_evidence(
                wrong_plan,
                expected_utterance_plan_sha256="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()
