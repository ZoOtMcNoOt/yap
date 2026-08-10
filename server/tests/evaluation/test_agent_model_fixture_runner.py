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


if __name__ == "__main__":
    unittest.main()
