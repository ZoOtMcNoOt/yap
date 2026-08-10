from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_fixture_runner import run_agent_model_fixtures
from yap_server.evaluation.agent_model_scoring import score_agent_model_results


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelFixtureRunnerTests(unittest.TestCase):
    def test_runs_tool_and_structured_answer_round_trip(self) -> None:
        fixture = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        cases = iter(fixture["cases"])
        active: dict[str, object] | None = None

        def request(payload: dict[str, object]) -> dict[str, object]:
            nonlocal active
            if "tools" in payload:
                active = next(cases)
                arguments = {
                    "purpose": "knowledge.read",
                    **active.get("expectedArguments", {}),
                }
                if active["expectedTool"] == "search_knowledge":
                    arguments["search_text"] = active["user"]
                if "expectedProposalType" in active:
                    arguments.update(
                        {
                            "proposal_type": active["expectedProposalType"],
                            "proposed_content": " ".join(
                                active.get("requiredTerms", [])
                            ),
                            "source_citations": [
                                {
                                    "concept_id": item["conceptId"],
                                    "source_revision": item["sourceRevision"],
                                    "content_sha256": item["contentSha256"],
                                    "char_start": item["charStart"],
                                    "char_end": item["charEnd"],
                                }
                                for item in active["visibleContext"]
                            ],
                        }
                    )
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": active["expectedTool"],
                                            "arguments": json.dumps(arguments),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            assert active is not None
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": " ".join(active.get("requiredTerms", [])),
                                    "citationConceptIds": active.get(
                                        "requiredCitationConceptIds", []
                                    ),
                                }
                            ),
                        }
                    }
                ]
            }

        results = run_agent_model_fixtures(
            REPOSITORY_ROOT, model="synthetic", request_json=request
        )
        score = score_agent_model_results(
            REPOSITORY_ROOT, tuple(item.record() for item in results)
        )

        self.assertEqual(len(results), 12)
        self.assertTrue(score.passed)

    def test_records_malformed_model_output_and_continues(self) -> None:
        calls = 0

        def request(payload: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"choices": []}
            if "tools" in payload:
                return _tool_response("search_knowledge")
            return _answer_response()

        results = run_agent_model_fixtures(
            REPOSITORY_ROOT, model="synthetic", request_json=request
        )

        self.assertTrue(results[0].invalid_structured_output)
        self.assertFalse(results[1].invalid_structured_output)
        score = score_agent_model_results(
            REPOSITORY_ROOT, tuple(item.record() for item in results)
        )
        self.assertGreaterEqual(score.invalid_structured_output_count, 1)
        self.assertFalse(score.passed)


def _tool_response(name: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(
                                    {
                                        "purpose": "knowledge.read",
                                        "search_text": "bounded test",
                                    }
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _answer_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"answer":"unavailable","citationConceptIds":[]}',
                }
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
