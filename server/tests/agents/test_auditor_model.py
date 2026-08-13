from __future__ import annotations

import json
import threading
import unittest

from yap_server.agents.auditor import AuditorEvidencePack, AuditorRequest
from yap_server.agents.auditor_model import (
    AuditorDecision,
    AuditorEvidenceModel,
    parse_auditor_decision,
)
from yap_server.agents.librarian import LibrarianEvidenceItem


def _response(arguments: object, *, content: object = None) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "return_auditor_selection",
                                "arguments": (
                                    arguments
                                    if isinstance(arguments, str)
                                    else json.dumps(arguments, separators=(",", ":"))
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _evidence() -> AuditorEvidencePack:
    items = []
    for index, text in enumerate(("Limit is five.", "Limit is ten.")):
        items.append(
            LibrarianEvidenceItem(
                concept_id=f"concept-{index}",
                source_revision="revision-1",
                content_sha256=f"{index + 1:064x}",
                char_start=0,
                char_end=len(text),
                text=text,
            )
        )
    return AuditorEvidencePack.create(
        generation_sha256="a" * 64,
        source_admission_sha256="b" * 64,
        permission_hash="c" * 64,
        authorization_hash="d" * 64,
        items=tuple(items),
        output_budget_exhausted=False,
    )


class _Transport:
    def __init__(self, response: dict[str, object], tokens: int = 200) -> None:
        self.response = response
        self.tokens = tokens
        self.payload: dict[str, object] | None = None

    def render_chat_token_count(
        self, payload: dict[str, object], cancellation: threading.Event
    ) -> int:
        self.payload = payload
        return self.tokens

    def request(
        self,
        payload: dict[str, object],
        cancellation: threading.Event,
        dispatched: threading.Event | None = None,
    ) -> dict[str, object]:
        self.payload = payload
        return self.response


class AuditorModelTests(unittest.TestCase):
    def test_forced_tool_payload_is_selection_only_and_fixed(self) -> None:
        transport = _Transport(
            _response(
                {
                    "outcome": "report",
                    "findings": [{"leftEvidenceIndex": 0, "rightEvidenceIndex": 1}],
                }
            )
        )
        model = AuditorEvidenceModel(
            transport=transport,
            model="gemma-model",
            maximum_output_tokens=512,
        )
        decision = model.review(
            AuditorRequest("limit conflict", 2, None),
            _evidence(),
            cancellation=threading.Event(),
        )
        self.assertEqual(decision, AuditorDecision("report", ((0, 1),)))
        assert transport.payload is not None
        self.assertEqual(transport.payload["temperature"], 0.0)
        self.assertEqual(transport.payload["seed"], 0)
        self.assertEqual(transport.payload["n"], 1)
        self.assertEqual(transport.payload["max_tokens"], 512)
        self.assertEqual(
            transport.payload["tool_choice"],
            {
                "type": "function",
                "function": {"name": "return_auditor_selection"},
            },
        )
        serialized = json.dumps(transport.payload, sort_keys=True)
        self.assertNotIn("concept-0", serialized)
        self.assertNotIn("contentSha256", serialized)
        self.assertIn("untrusted source data", serialized)
        self.assertIn("directly incompatible factual claims", serialized)
        self.assertIn("same stated time and scope", serialized)
        self.assertIn(
            "missing information, distinct scopes, distinct times", serialized
        )

    def test_parser_rejects_broader_envelopes_and_invalid_pairs(self) -> None:
        valid = {
            "outcome": "report",
            "findings": [{"leftEvidenceIndex": 0, "rightEvidenceIndex": 1}],
        }
        invalid = [
            _response(valid, content="prose"),
            _response('{"outcome":"report","outcome":"report","findings":[]}'),
            _response({**valid, "extra": True}),
            _response(
                {
                    "outcome": "report",
                    "findings": [{"leftEvidenceIndex": True, "rightEvidenceIndex": 1}],
                }
            ),
            _response(
                {
                    "outcome": "report",
                    "findings": [{"leftEvidenceIndex": 0, "rightEvidenceIndex": 0}],
                }
            ),
            _response(
                {
                    "outcome": "evidence-unavailable",
                    "findings": [{"leftEvidenceIndex": 0, "rightEvidenceIndex": 1}],
                }
            ),
        ]
        for response in invalid:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    parse_auditor_decision(response)

    def test_model_rejects_incomplete_evidence_context_overflow_and_out_of_range(
        self,
    ) -> None:
        request = AuditorRequest("limit conflict", 2, None)
        evidence = _evidence()
        cases = (
            (
                _Transport(
                    _response(
                        {
                            "outcome": "report",
                            "findings": [
                                {"leftEvidenceIndex": 0, "rightEvidenceIndex": 2}
                            ],
                        }
                    )
                ),
                evidence,
            ),
            (
                _Transport(
                    _response({"outcome": "evidence-unavailable", "findings": []}),
                    tokens=7_681,
                ),
                evidence,
            ),
            (
                _Transport(
                    _response({"outcome": "evidence-unavailable", "findings": []})
                ),
                AuditorEvidencePack.create(
                    generation_sha256="a" * 64,
                    source_admission_sha256="b" * 64,
                    permission_hash="c" * 64,
                    authorization_hash="d" * 64,
                    items=(evidence.items[0],),
                    output_budget_exhausted=False,
                ),
            ),
        )
        for transport, supplied in cases:
            with self.subTest(tokens=transport.tokens, count=len(supplied.items)):
                with self.assertRaises(ValueError):
                    AuditorEvidenceModel(
                        transport=transport,
                        model="gemma-model",
                        maximum_output_tokens=512,
                    ).review(request, supplied, cancellation=threading.Event())


if __name__ == "__main__":
    unittest.main()
