from __future__ import annotations

import hashlib
import json
import threading
import unittest

from yap_server.agents.transcript_correction import (
    BoundTranscriptCorrectionRequest,
    TranscriptCorrectionRequest,
    TranscriptCorrectionTerminology,
    bind_transcript_correction_request,
    correction_request_sha256,
)
from yap_server.agents.transcript_correction_model import TranscriptCorrectionModel


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
        TranscriptCorrectionTerminology("c" * 64, ("dosage",)),
    )


class _Transport:
    def __init__(self, response: dict[str, object]) -> None:
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
        return self.response


def _model_response(request: BoundTranscriptCorrectionRequest) -> dict[str, object]:
    result = {
        "schemaVersion": 1,
        "requestSha256": correction_request_sha256(request),
        "sourceSha256": request.source_sha256,
        "uncertain": False,
        "edits": [
            {
                "segmentId": "segment-0001",
                "segmentSha256": request.segments[0].text_sha256,
                "startCharacter": 0,
                "endCharacter": 5,
                "sourceText": "Um, t",
                "replacementText": "T",
            }
        ],
    }
    return {"choices": [{"message": {"content": json.dumps(result)}}]}


class TranscriptCorrectionModelTests(unittest.TestCase):
    def test_model_uses_exact_source_bound_json_schema_request(self) -> None:
        request = _request()
        transport = _Transport(_model_response(request))
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
        self.assertEqual(
            schema["properties"]["requestSha256"]["const"],
            correction_request_sha256(request),
        )
        self.assertEqual(
            schema["properties"]["sourceSha256"]["const"],
            request.source_sha256,
        )
        messages = payload["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        user_payload = json.loads(messages[1]["content"])
        self.assertEqual(user_payload["request"], request.to_wire())
        self.assertEqual(
            user_payload["responseBinding"],
            {
                "requestSha256": correction_request_sha256(request),
                "sourceSha256": request.source_sha256,
            },
        )
        self.assertEqual(
            user_payload["request"]["approvedTerminology"],
            ["dosage"],
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
        transport = _Transport(_model_response(request))
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


if __name__ == "__main__":
    unittest.main()
