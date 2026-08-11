from __future__ import annotations

import json
import unittest

from yap_server.knowledge.governed_answer_protocol import (
    governed_answer_json,
    governed_answer_request_fields,
    read_governed_answer,
)


class GovernedAnswerProtocolTests(unittest.TestCase):
    def test_keeps_qwen_schema_lean_and_gemma_tool_descriptive(self) -> None:
        qwen = governed_answer_request_fields("json-schema")
        gemma = governed_answer_request_fields("forced-answer-tool")

        qwen_properties = qwen["response_format"]["json_schema"]["schema"][  # type: ignore[index]
            "properties"
        ]
        gemma_properties = gemma["tools"][0]["function"]["parameters"][  # type: ignore[index]
            "properties"
        ]
        self.assertNotIn("description", qwen_properties["answer"])
        self.assertIn("description", gemma_properties["answer"])
        self.assertIn(
            "Evidence is unavailable.", gemma_properties["answer"]["description"]
        )

    def test_forces_one_native_answer_tool(self) -> None:
        fields = governed_answer_request_fields("forced-answer-tool")

        self.assertNotIn("response_format", fields)
        self.assertIs(fields["parallel_tool_calls"], False)
        self.assertEqual(
            fields["tool_choice"],
            {
                "type": "function",
                "function": {"name": "return_governed_answer"},
            },
        )
        content = governed_answer_json(
            _forced_response(
                {
                    "answer": "Bound answer.",
                    "citationConceptIds": ["concept-1"],
                }
            ),
            "forced-answer-tool",
        )
        self.assertEqual(
            json.loads(content),
            {"answer": "Bound answer.", "citationConceptIds": ["concept-1"]},
        )

    def test_rejects_extra_forced_tool_arguments(self) -> None:
        with self.assertRaisesRegex(ValueError, "differs from the contract"):
            read_governed_answer(
                _forced_response(
                    {
                        "answer": "Bound answer.",
                        "citationConceptIds": [],
                        "hidden": True,
                    }
                ),
                "forced-answer-tool",
            )

    def test_rejects_wrong_forced_tool_identity(self) -> None:
        response = _forced_response(
            {"answer": "Bound answer.", "citationConceptIds": []}
        )
        response["choices"][0]["message"]["tool_calls"][0]["function"][  # type: ignore[index]
            "name"
        ] = "search_knowledge"

        with self.assertRaisesRegex(ValueError, "identity"):
            read_governed_answer(response, "forced-answer-tool")


def _forced_response(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "answer-1",
                            "type": "function",
                            "function": {
                                "name": "return_governed_answer",
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
