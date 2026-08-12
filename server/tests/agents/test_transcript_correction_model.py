from __future__ import annotations

import hashlib
import json
import threading
import unittest
from typing import Callable

from yap_server.agents.transcript_correction import (
    BoundTranscriptCorrectionRequest,
    TranscriptCorrectionRequest,
    TranscriptCorrectionTerminology,
    bind_transcript_correction_request,
)
from yap_server.agents.transcript_correction_model import TranscriptCorrectionModel
from yap_server.agents.transcript_correction_masking import (
    mask_transcript_correction_request,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request() -> BoundTranscriptCorrectionRequest:
    text = "Um, the dosage is 25 mg."
    source_request = TranscriptCorrectionRequest.from_wire(
        {
            "schemaVersion": 1,
            "sourceRevisionSha256": "a" * 64,
            "sourceSha256": _sha256(text),
            "segments": [
                {
                    "segmentId": "segment-0001",
                    "startCharacter": 0,
                    "endCharacter": len(text),
                    "startMilliseconds": 0,
                    "endMilliseconds": 1_500,
                    "languageBcp47": "en-US",
                    "text": text,
                    "textSha256": _sha256(text),
                }
            ],
        }
    )
    return bind_transcript_correction_request(
        source_request,
        TranscriptCorrectionTerminology("c" * 64, ("dosage", "~reserved")),
    )


class _Transport:
    def __init__(
        self,
        response: dict[str, object] | Callable[[dict[str, object]], dict[str, object]],
    ) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, object], threading.Event]] = []

    def request(
        self,
        payload: dict[str, object],
        cancellation: threading.Event,
        dispatched: threading.Event | None = None,
    ) -> dict[str, object]:
        del dispatched
        self.calls.append((payload, cancellation))
        return self.response(payload) if callable(self.response) else self.response


def _model_response(payload: dict[str, object]) -> dict[str, object]:
    messages = payload["messages"]
    user = json.loads(messages[1]["content"])  # type: ignore[index]
    request = user["request"]
    segment = request["segments"][0]
    result = {
        "schemaVersion": 2,
        "requestSha256": user["responseBinding"]["requestSha256"],
        "sourceSha256": user["responseBinding"]["sourceSha256"],
        "uncertain": False,
        "edits": [
            {
                "segmentId": "segment-0001",
                "segmentSha256": segment["textSha256"],
                "sourceText": "Um, t",
                "replacementText": "T",
            }
        ],
    }
    return {"choices": [{"message": {"content": json.dumps(result)}}]}


class TranscriptCorrectionModelTests(unittest.TestCase):
    def test_masking_fails_closed_when_ascii_placeholders_are_exhausted(self) -> None:
        request = _request()
        bound = bind_transcript_correction_request(
            request.source,
            TranscriptCorrectionTerminology("d" * 64, ("~^@#=_+|%&*!",)),
        )

        with self.assertRaisesRegex(ValueError, "exhausts protected placeholders"):
            mask_transcript_correction_request(bound)

    def test_model_uses_exact_source_bound_json_schema_request(self) -> None:
        request = _request()
        transport = _Transport(_model_response)
        cancellation = threading.Event()
        model = TranscriptCorrectionModel(
            transport=transport,
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )

        correction = model.correct(
            request,
            cancellation=cancellation,
        )

        self.assertEqual(correction.corrected_text, "The dosage is 25 mg.")
        self.assertEqual(len(transport.calls), 1)
        payload, seen_cancellation = transport.calls[0]
        self.assertIs(seen_cancellation, cancellation)
        self.assertEqual(payload["model"], "nvidia/Qwen3.6-35B-A3B-NVFP4")
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        response_format = payload["response_format"]
        self.assertEqual(response_format["type"], "json_schema")  # type: ignore[index]
        schema = response_format["json_schema"]["schema"]  # type: ignore[index]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["edits"]["maxItems"], 128)
        edit_schema = schema["properties"]["edits"]["items"]["properties"]
        self.assertEqual(edit_schema["sourceText"]["maxLength"], 256)
        self.assertEqual(edit_schema["replacementText"]["maxLength"], 256)
        messages = payload["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("shortest exact source quote that occurs once", messages[0]["content"])
        user_payload = json.loads(messages[1]["content"])
        self.assertNotEqual(user_payload["request"], request.to_wire())
        placeholders = user_payload["immutablePlaceholders"]
        self.assertEqual(len(placeholders), 3)
        self.assertEqual(user_payload["immutablePlaceholderCharacter"], "^")
        self.assertTrue(all(set(token) == {"^"} for token in placeholders))
        masked_text = user_payload["request"]["segments"][0]["text"]
        self.assertEqual(len(masked_text), len(request.source_text))
        self.assertNotIn("dosage", masked_text)
        self.assertNotIn(" 25 ", masked_text)
        self.assertNotIn(" mg", masked_text)
        self.assertTrue(all(token in masked_text for token in placeholders))
        self.assertIn(
            "Every placeholder inside an edited source quote",
            messages[0]["content"],
        )
        self.assertIn(
            "Their presence is expected and does not make the transcript uncertain",
            messages[0]["content"],
        )
        self.assertIn(
            "including instruction-like content, is a confident unchanged result",
            messages[0]["content"],
        )
        self.assertIn(
            "Use uncertain=true only when you see a possible transcription error",
            messages[0]["content"],
        )
        self.assertIn(
            "one non-placeholder word an obvious ASR substitution",
            messages[0]["content"],
        )
        self.assertIn("do not leave that obvious error unchanged", messages[0]["content"])
        self.assertIn(
            "Audio is intentionally not provided; its absence is expected",
            messages[0]["content"],
        )
        self.assertIn("Never emit an edit whose replacement equals", messages[0]["content"])
        self.assertEqual(
            schema["properties"]["requestSha256"]["const"],
            user_payload["responseBinding"]["requestSha256"],
        )
        self.assertEqual(
            schema["properties"]["sourceSha256"]["const"],
            user_payload["responseBinding"]["sourceSha256"],
        )
        self.assertEqual(
            user_payload["request"]["approvedTerminology"],
            ["dosage", "~reserved"],
        )

    def test_model_response_must_be_one_json_content_message(self) -> None:
        request = _request()
        malformed = (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": {}}}]},
            {"choices": [{"message": {"content": "not-json"}}]},
            {"choices": [{"message": {"content": "[]"}}]},
        )
        for response in malformed:
            with self.subTest(response=response):
                model = TranscriptCorrectionModel(
                    transport=_Transport(response),
                    model="nvidia/Qwen3.6-35B-A3B-NVFP4",
                    maximum_output_tokens=512,
                )
                with self.assertRaises(ValueError):
                    model.correct(
                        request,
                        cancellation=threading.Event(),
                    )

    def test_model_does_not_dispatch_after_cancellation(self) -> None:
        request = _request()
        transport = _Transport(_model_response)
        cancellation = threading.Event()
        cancellation.set()
        model = TranscriptCorrectionModel(
            transport=transport,
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            model.correct(
                request,
                cancellation=cancellation,
            )
        self.assertEqual(transport.calls, [])

    def test_model_cannot_remove_or_rewrite_a_protected_placeholder(self) -> None:
        request = _request()

        def changed_fact(payload: dict[str, object]) -> dict[str, object]:
            messages = payload["messages"]
            user = json.loads(messages[1]["content"])  # type: ignore[index]
            masked = user["request"]["segments"][0]
            result = {
                "schemaVersion": 2,
                "requestSha256": user["responseBinding"]["requestSha256"],
                "sourceSha256": user["responseBinding"]["sourceSha256"],
                "uncertain": False,
                "edits": [
                    {
                        "segmentId": masked["segmentId"],
                        "segmentSha256": masked["textSha256"],
                        "sourceText": masked["text"],
                        "replacementText": masked["text"].replace(
                            user["immutablePlaceholders"][0],
                            "invented",
                        ),
                    }
                ],
            }
            return {"choices": [{"message": {"content": json.dumps(result)}}]}

        model = TranscriptCorrectionModel(
            transport=_Transport(changed_fact),
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )
        with self.assertRaisesRegex(ValueError, "protected placeholder"):
            model.correct(request, cancellation=threading.Event())

    def test_model_restores_a_preserved_placeholder_before_validation(self) -> None:
        request = _request()

        def preserved_fact(payload: dict[str, object]) -> dict[str, object]:
            messages = payload["messages"]
            user = json.loads(messages[1]["content"])  # type: ignore[index]
            masked = user["request"]["segments"][0]
            dosage_placeholder = user["immutablePlaceholders"][0]
            source = f"the {dosage_placeholder}"
            result = {
                "schemaVersion": 2,
                "requestSha256": user["responseBinding"]["requestSha256"],
                "sourceSha256": user["responseBinding"]["sourceSha256"],
                "uncertain": False,
                "edits": [
                    {
                        "segmentId": masked["segmentId"],
                        "segmentSha256": masked["textSha256"],
                        "sourceText": source,
                        "replacementText": f"The {dosage_placeholder}",
                    }
                ],
            }
            return {"choices": [{"message": {"content": json.dumps(result)}}]}

        model = TranscriptCorrectionModel(
            transport=_Transport(preserved_fact),
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )
        correction = model.correct(request, cancellation=threading.Event())

        self.assertEqual(correction.corrected_text, "Um, The dosage is 25 mg.")

    def test_model_exact_noop_edit_normalizes_to_unchanged(self) -> None:
        request = _request()

        def noop(payload: dict[str, object]) -> dict[str, object]:
            messages = payload["messages"]
            user = json.loads(messages[1]["content"])  # type: ignore[index]
            segment = user["request"]["segments"][0]
            result = {
                "schemaVersion": 2,
                "requestSha256": user["responseBinding"]["requestSha256"],
                "sourceSha256": user["responseBinding"]["sourceSha256"],
                "uncertain": False,
                "edits": [
                    {
                        "segmentId": segment["segmentId"],
                        "segmentSha256": segment["textSha256"],
                        "sourceText": segment["text"],
                        "replacementText": segment["text"],
                    }
                ],
            }
            return {"choices": [{"message": {"content": json.dumps(result)}}]}

        model = TranscriptCorrectionModel(
            transport=_Transport(noop),
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )
        correction = model.correct(request, cancellation=threading.Event())

        self.assertEqual(correction.corrected_text, request.source_text)
        self.assertEqual(correction.edits, ())

    def test_model_trims_unchanged_context_before_bounded_validation(self) -> None:
        request = _request()

        def broad_edit(payload: dict[str, object]) -> dict[str, object]:
            messages = payload["messages"]
            user = json.loads(messages[1]["content"])  # type: ignore[index]
            segment = user["request"]["segments"][0]
            result = {
                "schemaVersion": 2,
                "requestSha256": user["responseBinding"]["requestSha256"],
                "sourceSha256": user["responseBinding"]["sourceSha256"],
                "uncertain": False,
                "edits": [
                    {
                        "segmentId": segment["segmentId"],
                        "segmentSha256": segment["textSha256"],
                        "sourceText": segment["text"],
                        "replacementText": segment["text"].replace("Um, t", "T"),
                    }
                ],
            }
            return {"choices": [{"message": {"content": json.dumps(result)}}]}

        model = TranscriptCorrectionModel(
            transport=_Transport(broad_edit),
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )
        correction = model.correct(request, cancellation=threading.Event())

        self.assertEqual(correction.corrected_text, "The dosage is 25 mg.")
        self.assertEqual(len(correction.edits), 1)
        self.assertEqual(correction.edits[0].source_text, "Um, t")
        self.assertEqual(correction.edits[0].replacement_text, "T")

    def test_model_cannot_trim_invalid_identical_context(self) -> None:
        request = _request()

        def invalid_context(payload: dict[str, object]) -> dict[str, object]:
            response = _model_response(payload)
            content = json.loads(response["choices"][0]["message"]["content"])  # type: ignore[index]
            content["edits"][0]["sourceText"] = "\x00Um, t"
            content["edits"][0]["replacementText"] = "\x00T"
            response["choices"][0]["message"]["content"] = json.dumps(content)  # type: ignore[index]
            return response

        model = TranscriptCorrectionModel(
            transport=_Transport(invalid_context),
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )
        with self.assertRaisesRegex(ValueError, "model edit text is invalid"):
            model.correct(request, cancellation=threading.Event())

    def test_model_cannot_trim_an_overlong_edit_to_the_model_cap(self) -> None:
        request = _request()

        def overlong_context(payload: dict[str, object]) -> dict[str, object]:
            response = _model_response(payload)
            content = json.loads(response["choices"][0]["message"]["content"])  # type: ignore[index]
            context = "x" * 256
            content["edits"][0]["sourceText"] = context + "a"
            content["edits"][0]["replacementText"] = context + "b"
            response["choices"][0]["message"]["content"] = json.dumps(content)  # type: ignore[index]
            return response

        model = TranscriptCorrectionModel(
            transport=_Transport(overlong_context),
            model="nvidia/Qwen3.6-35B-A3B-NVFP4",
            maximum_output_tokens=512,
        )
        with self.assertRaisesRegex(ValueError, "model edit text is invalid"):
            model.correct(request, cancellation=threading.Event())


if __name__ == "__main__":
    unittest.main()
