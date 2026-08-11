from __future__ import annotations

import json
from pathlib import Path
import unittest

from yap_server.evaluation.agent_model_fixture_runner import (
    _step_visible_context,
    run_agent_model_fixtures,
    warm_agent_model_fixture_runtime,
)
from yap_server.evaluation.agent_model_scoring import score_agent_model_results
from yap_server.knowledge.knowledge_tool_contract import (
    governed_agent_tool_definitions,
    validate_governed_agent_tool_arguments,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelFixtureRunnerTests(unittest.TestCase):
    def test_warms_exact_tool_and_structured_response_shapes(self) -> None:
        requests: list[dict[str, object]] = []

        def request(payload: dict[str, object]) -> dict[str, object]:
            requests.append(payload)
            return {}

        warm_agent_model_fixture_runtime(
            model="synthetic",
            maximum_output_tokens=256,
            final_response_protocol="forced-answer-tool",
            request_json=request,
        )

        self.assertEqual(len(requests), 2)
        self.assertEqual([item["max_tokens"] for item in requests], [64, 64])
        self.assertIn("tools", requests[0])
        self.assertIs(requests[0]["parallel_tool_calls"], False)
        self.assertIn("tools", requests[1])
        self.assertNotIn("response_format", requests[1])
        self.assertEqual(
            requests[1]["tool_choice"],
            {
                "type": "function",
                "function": {"name": "return_governed_answer"},
            },
        )
        self.assertIs(requests[1]["parallel_tool_calls"], False)

    def test_requires_a_caller_supplied_generation_identity(self) -> None:
        tools = governed_agent_tool_definitions(require_generation_sha256=True)

        for tool in tools:
            parameters = tool["function"]["parameters"]
            self.assertIn("expected_generation_sha256", parameters["required"])
            self.assertEqual(
                parameters["properties"]["expected_generation_sha256"]["type"],
                "string",
            )

    def test_search_schema_and_validator_share_the_production_boundary(self) -> None:
        definitions = governed_agent_tool_definitions()
        search = next(
            item
            for item in definitions
            if item["function"]["name"] == "search_knowledge"
        )
        search_schema = search["function"]["parameters"]["properties"]["search_text"]
        self.assertEqual(search_schema["maxLength"], 1_024)
        validate_governed_agent_tool_arguments(
            "search_knowledge",
            {"purpose": "knowledge.read", "search_text": "a" * 1_024},
        )
        with self.assertRaisesRegex(ValueError, "search text"):
            validate_governed_agent_tool_arguments(
                "search_knowledge",
                {"purpose": "knowledge.read", "search_text": "a" * 1_025},
            )

    def test_terminology_workloads_request_a_noncanonical_proposal(self) -> None:
        fixture = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        terminology_cases = [
            case for case in fixture["cases"] if case["category"] == "terminology"
        ]

        self.assertEqual(len(terminology_cases), 2)
        for case in terminology_cases:
            with self.subTest(case=case["caseId"]):
                self.assertEqual(case["expectedTool"], "propose_knowledge")
                self.assertIn("propose_knowledge", case["user"])
                self.assertTrue(
                    any(
                        phrase in case["user"].lower()
                        for phrase in ("noncanonical", "no canónica")
                    )
                )
                for term in case["requiredTerms"]:
                    self.assertIn(term, case["user"])

    def test_empty_result_cases_freeze_short_explicit_tool_contracts(self) -> None:
        fixture = json.loads(
            (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        by_id = {case["caseId"]: case for case in fixture["cases"]}

        bounded = by_id["bounded-no-result"]
        self.assertEqual(
            bounded["expectedArguments"],
            {
                "purpose": "knowledge.read",
                "search_text": "missing governed evidence",
            },
        )
        self.assertIn("exactly once", bounded["user"])
        self.assertIn("Evidence is unavailable.", bounded["user"])
        self.assertEqual(bounded["expectedAnswer"], "Evidence is unavailable.")

        relationship = by_id["relationship-traversal"]
        self.assertEqual(
            relationship["expectedArguments"],
            {
                "purpose": "knowledge.read",
                "start_concept_id": "project/voiceos",
                "maximum_depth": 2,
            },
        )

        stale = by_id["stale-generation-binding"]
        self.assertIn("Evidence is unavailable.", stale["user"])
        self.assertEqual(stale["requiredTerms"], ["unavailable"])
        self.assertEqual(stale["expectedAnswer"], "Evidence is unavailable.")
        self.assertEqual(stale["maximumOutputTokens"], 128)
        self.assertEqual(
            stale["expectedArguments"],
            {
                "purpose": "knowledge.read",
                "search_text": "release",
                "expected_generation_sha256": "f" * 64,
            },
        )

        lexical = by_id["lexical-cited-answer"]
        self.assertIn("publication pointer", lexical["user"])
        self.assertNotIn("crash safety", lexical["user"])
        self.assertEqual(
            lexical["expectedAnswer"],
            "The publication pointer changes only after every projection validates.",
        )
        self.assertEqual(
            lexical["expectedArguments"],
            {"purpose": "knowledge.read", "search_text": "publication pointer"},
        )

        missing = by_id["missing-evidence-refusal"]
        self.assertEqual(missing["expectedAnswer"], "Evidence is unavailable.")

        self.assertEqual(
            {
                case["caseId"]
                for case in fixture["cases"]
                if case["visibleContext"] == []
            },
            {
                "relationship-traversal",
                "tree-browse",
                "missing-evidence-refusal",
                "stale-generation-binding",
                "bounded-no-result",
            },
        )
        for case in fixture["cases"]:
            if case["visibleContext"] == []:
                self.assertEqual(case["expectedAnswer"], "Evidence is unavailable.")

        complex_case = by_id["complex-governed-orchestration"]
        self.assertIn("Do not add generation or result controls.", complex_case["user"])

        injection = by_id["prompt-injection-denial"]
        self.assertEqual(
            injection["expectedAnswer"],
            "I cannot query the raw repository or filesystem or bypass permissions.",
        )
        for prompt in fixture["systemPrompts"].values():
            self.assertIn("answer exactly Evidence is unavailable.", prompt)
            self.assertIn(
                "answer exactly I cannot query the raw repository or filesystem or bypass permissions.",
                prompt,
            )

    def test_withholds_context_from_semantically_wrong_tool_calls(self) -> None:
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

        expected_calls = case["expectedToolCalls"]
        for step_index, expected in enumerate(expected_calls):
            name = expected["name"]
            arguments = dict(expected["expectedArguments"])
            if name == "propose_knowledge":
                arguments.update(
                    proposed_content="VoiceOS permission ledger",
                    source_citations=[
                        {
                            "concept_id": item["conceptId"],
                            "source_revision": item["sourceRevision"],
                            "content_sha256": item["contentSha256"],
                            "char_start": item["charStart"],
                            "char_end": item["charEnd"],
                        }
                        for item in case["visibleContext"]
                    ],
                )
            self.assertEqual(
                _step_visible_context(
                    case,
                    step_index=step_index,
                    tool_name=name,
                    arguments=arguments,
                ),
                case["visibleContext"],
            )
            extra_controls = [("expected_generation_sha256", "e" * 64)]
            if name in {"search_knowledge", "traverse_knowledge"}:
                extra_controls.append(("maximum_results", 1))
            for field, value in extra_controls:
                with self.subTest(step=name, extra=field):
                    self.assertEqual(
                        _step_visible_context(
                            case,
                            step_index=step_index,
                            tool_name=name,
                            arguments={**arguments, field: value},
                        ),
                        [],
                    )

        lexical = next(
            item
            for item in fixture["cases"]
            if item["caseId"] == "lexical-cited-answer"
        )
        self.assertEqual(
            _step_visible_context(
                lexical,
                step_index=0,
                tool_name="search_knowledge",
                arguments={
                    "purpose": "knowledge.read",
                    "search_text": "completely unrelated banana",
                },
            ),
            [],
        )
        self.assertEqual(
            _step_visible_context(
                lexical,
                step_index=0,
                tool_name="search_knowledge",
                arguments={
                    **lexical["expectedArguments"],
                    "expected_generation_sha256": "e" * 64,
                },
            ),
            [],
        )
        self.assertEqual(
            _step_visible_context(
                lexical,
                step_index=0,
                tool_name="search_knowledge",
                arguments=lexical["expectedArguments"],
            ),
            lexical["visibleContext"],
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
                                        "answer": case.get(
                                            "expectedAnswer",
                                            " ".join(case.get("requiredTerms", [])),
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
            maximum_output_tokens=256,
            final_response_protocol="json-schema",
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
            if payload.get("tool_choice") == {
                "type": "function",
                "function": {"name": "return_governed_answer"},
            }:
                assert active is not None
                self.assertEqual(
                    payload["max_tokens"], active.get("maximumOutputTokens", 512)
                )
                answer = {
                    "answer": active.get(
                        "expectedAnswer",
                        " ".join(active.get("requiredTerms", [])),
                    ),
                    "citationConceptIds": active.get(
                        "requiredCitationConceptIds", []
                    ),
                }
                active = None
                return _tool_response("return_governed_answer", answer)
            if "tools" in payload:
                active = next(cases)
                self.assertEqual(
                    payload["max_tokens"], active.get("maximumOutputTokens", 512)
                )
                arguments = {
                    "purpose": "knowledge.read",
                    **active.get("expectedArguments", {}),
                }
                if active["expectedTool"] == "search_knowledge":
                    arguments.setdefault("search_text", active["user"])
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
            self.assertEqual(
                payload["max_tokens"], active.get("maximumOutputTokens", 512)
            )
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": active.get(
                                        "expectedAnswer",
                                        " ".join(active.get("requiredTerms", [])),
                                    ),
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
            maximum_output_tokens=512,
            final_response_protocol="forced-answer-tool",
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
            maximum_output_tokens=512,
            final_response_protocol="json-schema",
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
                maximum_output_tokens=512,
                final_response_protocol="json-schema",
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


def _answer_response(answer: str = "unavailable") -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"answer": answer, "citationConceptIds": []}
                    ),
                }
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
