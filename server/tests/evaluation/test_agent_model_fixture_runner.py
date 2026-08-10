from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_fixture_runner import (
    _step_visible_context,
    run_agent_model_fixtures,
)
from yap_server.evaluation.agent_model_scoring import score_agent_model_results


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelFixtureRunnerTests(unittest.TestCase):
    def test_withholds_context_from_semantically_wrong_orchestration_step(self) -> None:
        fixture = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        case = next(
            item
            for item in fixture["cases"]
            if item["caseId"] == "complex-governed-orchestration"
        )

        self.assertEqual(
            _step_visible_context(
                case,
                step_index=1,
                tool_name="traverse_knowledge",
                arguments={
                    "purpose": "knowledge.read",
                    "start_concept_id": "unrelated/concept",
                    "maximum_depth": 2,
                },
            ),
            [],
        )

    def test_runs_complex_orchestration_as_three_owned_tool_steps(self) -> None:
        fixture = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        cases = iter(fixture["cases"])
        active: dict[str, object] | None = None

        def request(payload: dict[str, object]) -> dict[str, object]:
            nonlocal active
            messages = payload["messages"]
            assert isinstance(messages, list)
            if "tools" in payload and active is None:
                active = next(cases)
            assert active is not None
            case = active
            if "tools" not in payload:
                response = {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "answer": " ".join(
                                            case.get("requiredTerms", [])
                                        ),
                                        "citationConceptIds": case.get(
                                            "requiredCitationConceptIds", []
                                        ),
                                    }
                                ),
                            }
                        }
                    ]
                }
                active = None
                return response
            sequence = case.get("expectedToolSequence", [case["expectedTool"]])
            prior_calls = sum(
                message.get("role") == "tool" for message in messages
            )
            if "expectedToolSequence" not in case:
                prior_calls = 0
            name = sequence[prior_calls]
            expected_calls = case.get("expectedToolCalls")
            if name == "search_knowledge":
                arguments = {
                    "purpose": "knowledge.read",
                    "search_text": case["user"],
                }
            elif name == "browse_knowledge":
                arguments = {"purpose": "knowledge.read"}
            elif name == "traverse_knowledge":
                arguments = {
                    "purpose": "knowledge.read",
                    "start_concept_id": case.get("expectedArguments", {}).get(
                        "start_concept_id", "project/voiceos"
                    ),
                    "maximum_depth": case.get("expectedArguments", {}).get(
                        "maximum_depth", 2
                    ),
                }
            else:
                arguments = {
                    "purpose": "knowledge.read",
                    "proposal_type": "summary",
                    "proposed_content": " ".join(case.get("requiredTerms", [])),
                    "source_citations": [
                        {
                            "concept_id": item["conceptId"],
                            "source_revision": item["sourceRevision"],
                            "content_sha256": item["contentSha256"],
                            "char_start": item["charStart"],
                            "char_end": item["charEnd"],
                        }
                        for item in case["visibleContext"]
                    ],
                }
            if isinstance(expected_calls, list):
                expected_call = expected_calls[prior_calls]
                assert isinstance(expected_call, dict)
                arguments.update(expected_call["expectedArguments"])
            arguments.update(case.get("expectedArguments", {}))
            return _tool_response(name, arguments)

        results = run_agent_model_fixtures(
            REPOSITORY_ROOT,
            model="synthetic",
            workload_class="complex-orchestration",
            request_json=request,
        )
        result = results[-1].record()

        self.assertEqual(
            [call["name"] for call in result["toolCalls"]],  # type: ignore[index]
            ["search_knowledge", "traverse_knowledge", "propose_knowledge"],
        )
        score = score_agent_model_results(
            REPOSITORY_ROOT,
            tuple(item.record() for item in results),
            workload_class="complex-orchestration",
        )
        self.assertTrue(
            score.passed,
            (
                score,
                tuple(
                    (
                        item.case_id,
                        item.answer,
                        item.citation_concept_ids,
                        item.arguments,
                    )
                    for item in results
                ),
            ),
        )

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
            self.assertEqual(
                payload["chat_template_kwargs"], {"enable_thinking": False}
            )
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
            REPOSITORY_ROOT,
            model="synthetic",
            workload_class="rapid-automation",
            request_json=request,
        )
        score = score_agent_model_results(
            REPOSITORY_ROOT,
            tuple(item.record() for item in results),
            workload_class="rapid-automation",
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
            REPOSITORY_ROOT,
            model="synthetic",
            workload_class="rapid-automation",
            request_json=request,
        )

        self.assertTrue(results[0].invalid_structured_output)
        self.assertFalse(results[1].invalid_structured_output)
        score = score_agent_model_results(
            REPOSITORY_ROOT,
            tuple(item.record() for item in results),
            workload_class="rapid-automation",
        )
        self.assertGreaterEqual(score.invalid_structured_output_count, 1)
        self.assertFalse(score.passed)

    def test_identifies_the_case_for_a_runtime_request_failure(self) -> None:
        def request(_payload: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("private endpoint detail")

        with self.assertRaisesRegex(
            RuntimeError, "agent workload case lexical-cited-answer failed"
        ):
            run_agent_model_fixtures(
                REPOSITORY_ROOT,
                model="synthetic",
                workload_class="rapid-automation",
                request_json=request,
            )


def _tool_response(
    name: str, arguments: dict[str, object] | None = None
) -> dict[str, object]:
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
                                    arguments
                                    or {
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
