from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from yap_server.evaluation.agent_model_fixture_runner import _run_case_safely


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AgentModelFinalResponseRetryTests(unittest.TestCase):
    def test_retries_only_an_undecodable_final_response(self) -> None:
        case = _fixture_case("cited-summary-proposal")
        proposal_arguments = _proposal_arguments(case)
        expected_answer = " ".join(case["requiredTerms"])
        for protocol in ("json-schema", "forced-answer-tool"):
            with self.subTest(protocol=protocol):
                requests: list[dict[str, object]] = []

                def request(payload: dict[str, object]) -> dict[str, object]:
                    requests.append(payload)
                    if payload.get("tool_choice") == "required":
                        return _tool_response(
                            "propose_knowledge", proposal_arguments
                        )
                    final_count = sum(
                        item.get("tool_choice") != "required" for item in requests
                    )
                    if final_count == 1:
                        return {"choices": []}
                    if protocol == "forced-answer-tool":
                        return _tool_response(
                            "return_governed_answer",
                            {
                                "answer": expected_answer,
                                "citationConceptIds": case[
                                    "requiredCitationConceptIds"
                                ],
                            },
                        )
                    return _answer_response(
                        expected_answer,
                        list(case["requiredCitationConceptIds"]),
                    )

                with patch(
                    "yap_server.evaluation.agent_model_fixture_runner.time.monotonic",
                    side_effect=(10.0, 10.75),
                ):
                    result = _run_case_safely(
                        case,
                        model="synthetic",
                        system_prompt="Use governed evidence.",
                        maximum_output_tokens=256,
                        maximum_final_response_attempts=2,
                        final_response_protocol=protocol,
                        request_json=request,
                    )

                final_requests = [
                    item for item in requests if item.get("tool_choice") != "required"
                ]
                self.assertFalse(result.invalid_structured_output)
                self.assertEqual(result.model_request_count, 3)
                self.assertEqual(result.latency_milliseconds, 750)
                self.assertEqual(len(result.tool_calls), 1)
                self.assertEqual(result.tool_name, "propose_knowledge")
                self.assertEqual(
                    result.citation_concept_ids,
                    tuple(case["requiredCitationConceptIds"]),
                )
                self.assertEqual(
                    sum(item.get("tool_choice") == "required" for item in requests),
                    1,
                )
                self.assertEqual(len(final_requests), 2)
                self.assertEqual(
                    final_requests[0]["messages"], final_requests[1]["messages"]
                )

    def test_retry_exhaustion_preserves_completed_tool_evidence(self) -> None:
        case = _fixture_case("cited-summary-proposal")
        proposal_arguments = _proposal_arguments(case)
        requests: list[dict[str, object]] = []

        def request(payload: dict[str, object]) -> dict[str, object]:
            requests.append(payload)
            if payload.get("tool_choice") == "required":
                return _tool_response("propose_knowledge", proposal_arguments)
            return {"choices": []}

        result = _run_case_safely(
            case,
            model="synthetic",
            system_prompt="Use governed evidence.",
            maximum_output_tokens=256,
            maximum_final_response_attempts=2,
            final_response_protocol="json-schema",
            request_json=request,
        )

        self.assertTrue(result.invalid_structured_output)
        self.assertEqual(result.model_request_count, 3)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_name, "propose_knowledge")
        self.assertEqual(
            sum(item.get("tool_choice") == "required" for item in requests), 1
        )
        self.assertEqual(result.answer, "")
        self.assertEqual(sum("tools" not in item for item in requests), 2)

    def test_does_not_retry_well_formed_wrong_answers_or_tool_arguments(self) -> None:
        case = _fixture_case("lexical-cited-answer")
        semantic_failures = (
            ("A well-formed but unsupported answer.", [], "wrong-answer"),
            (case["expectedAnswer"], ["hidden/concept"], "wrong-citation"),
        )
        for answer, citations, label in semantic_failures:
            with self.subTest(label=label):
                requests: list[dict[str, object]] = []

                def wrong_final(payload: dict[str, object]) -> dict[str, object]:
                    requests.append(payload)
                    if "tools" in payload:
                        return _tool_response(
                            "search_knowledge", case["expectedArguments"]
                        )
                    return _answer_response(str(answer), list(citations))

                result = _run_case_safely(
                    case,
                    model="synthetic",
                    system_prompt="Use governed evidence.",
                    maximum_output_tokens=256,
                    maximum_final_response_attempts=2,
                    final_response_protocol="json-schema",
                    request_json=wrong_final,
                )
                self.assertFalse(result.invalid_structured_output)
                self.assertEqual(result.model_request_count, 2)
                self.assertEqual(result.answer, answer)
                self.assertEqual(result.citation_concept_ids, tuple(citations))

        wrong_calls = (
            ("browse_knowledge", {"purpose": "knowledge.read"}, "wrong-tool"),
            (
                "search_knowledge",
                dict(
                    purpose="knowledge.read",
                    search_text="completely unrelated banana",
                    maximum_results=1,
                ),
                "wrong-arguments",
            ),
        )
        for name, arguments, label in wrong_calls:
            with self.subTest(label=label):
                requests: list[dict[str, object]] = []

                def wrong_call(payload: dict[str, object]) -> dict[str, object]:
                    requests.append(payload)
                    if "tools" in payload:
                        return _tool_response(name, arguments)
                    return _answer_response(str(case["expectedAnswer"]))

                result = _run_case_safely(
                    case,
                    model="synthetic",
                    system_prompt="Use governed evidence.",
                    maximum_output_tokens=256,
                    maximum_final_response_attempts=2,
                    final_response_protocol="json-schema",
                    request_json=wrong_call,
                )
                self.assertFalse(result.invalid_structured_output)
                self.assertEqual(result.model_request_count, 2)
                self.assertEqual(
                    sum(item.get("tool_choice") == "required" for item in requests),
                    1,
                )

        tool_requests = 0

        def wrong_arguments(_payload: dict[str, object]) -> dict[str, object]:
            nonlocal tool_requests
            tool_requests += 1
            return _tool_response(
                "search_knowledge",
                {
                    "purpose": "knowledge.read",
                    "search_text": "publication pointer",
                    "maximum_results": 0,
                },
            )

        invalid = _run_case_safely(
            case,
            model="synthetic",
            system_prompt="Use governed evidence.",
            maximum_output_tokens=256,
            maximum_final_response_attempts=2,
            final_response_protocol="json-schema",
            request_json=wrong_arguments,
        )
        self.assertTrue(invalid.invalid_structured_output)
        self.assertEqual(invalid.model_request_count, 1)
        self.assertEqual(tool_requests, 1)

    def test_request_value_error_is_not_reclassified_as_retryable_output(self) -> None:
        case = _fixture_case("lexical-cited-answer")

        def request(_payload: dict[str, object]) -> dict[str, object]:
            raise ValueError("private response transport detail")

        with self.assertRaisesRegex(ValueError, "private response transport detail"):
            _run_case_safely(
                case,
                model="synthetic",
                system_prompt="Use governed evidence.",
                maximum_output_tokens=256,
                maximum_final_response_attempts=2,
                final_response_protocol="json-schema",
                request_json=request,
            )


def _fixture_case(case_id: str) -> dict[str, object]:
    fixture = json.loads(
        (REPOSITORY_ROOT / "server" / "agent-workload-fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    return next(case for case in fixture["cases"] if case["caseId"] == case_id)


def _proposal_arguments(case: dict[str, object]) -> dict[str, object]:
    visible = case["visibleContext"]
    assert isinstance(visible, list)
    fields = {
        "conceptId": "concept_id",
        "sourceRevision": "source_revision",
        "contentSha256": "content_sha256",
        "charStart": "char_start",
        "charEnd": "char_end",
    }
    return {
        "purpose": "knowledge.read",
        "proposal_type": case["expectedProposalType"],
        "proposed_content": " ".join(case["requiredTerms"]),
        "source_citations": [
            {target: item[source] for source, target in fields.items()}
            for item in visible
        ],
    }


def _tool_response(name: str, arguments: object) -> dict[str, object]:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }
    return {"choices": [{"message": message}]}


def _answer_response(
    answer: str, citations: list[object] | None = None
) -> dict[str, object]:
    message = {
        "role": "assistant",
        "content": json.dumps(
            {"answer": answer, "citationConceptIds": citations or []}
        ),
    }
    return {"choices": [{"message": message}]}
