from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance
from .agent_model_fixture_runner import validate_agent_tool_arguments


_RESULT_KEYS = {
    "caseId",
    "toolName",
    "arguments",
    "answer",
    "citationConceptIds",
    "latencyMilliseconds",
    "toolCalls",
}


@dataclass(frozen=True, slots=True)
class AgentModelScore:
    case_count: int
    tool_selection_accuracy: float
    structured_argument_accuracy: float
    citation_fidelity: float
    terminology_preservation: float
    isolation_leak_count: int
    invalid_structured_output_count: int
    latency_milliseconds: tuple[int, ...]
    route_specific_evidence_passed: bool
    passed: bool


def score_agent_model_results(
    repository_root: Path,
    results: tuple[object, ...],
    *,
    workload_class: str,
) -> AgentModelScore:
    """Derive acceptance metrics from per-case outputs; trust no supplied aggregate."""

    acceptance = load_agent_model_acceptance(repository_root)
    fixture, _identity = read_json_object_with_identity(
        repository_root / "server" / "agent-workload-fixtures.json",
        maximum_bytes=256_000,
        field="agent workload fixtures",
        expected_sha256=acceptance.fixture_sha256,
        containment_root=repository_root,
    )
    cases = [
        case
        for case in fixture["cases"]
        if case.get("requiredForWorkloadClass") in {None, workload_class}
    ]
    assert isinstance(cases, list)
    by_id = {case["caseId"]: case for case in cases}  # type: ignore[index]
    if not isinstance(results, tuple) or len(results) != len(by_id):
        raise ValueError("agent model result set is incomplete")
    result_by_id: dict[str, dict[str, object]] = {}
    invalid = 0
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("agent model result must be an object")
        case_id = result["caseId"]
        if (
            not isinstance(case_id, str)
            or case_id not in by_id
            or case_id in result_by_id
        ):
            raise ValueError("agent model result identity is invalid")
        if set(result) != _RESULT_KEYS or not _valid_result_types(result):
            invalid += 1
        result_by_id[case_id] = result
    if set(result_by_id) != set(by_id):
        raise ValueError("agent model result set differs from fixtures")

    tool_pass = 0
    argument_checks = 0
    argument_pass = 0
    citation_checks = 0
    citation_pass = 0
    terminology_checks = 0
    terminology_pass = 0
    leaks = 0
    latencies: list[int] = []
    route_specific_evidence_passed = True
    for case_id, case in by_id.items():
        result = result_by_id[case_id]
        expected_sequence = case.get("expectedToolSequence", [case.get("expectedTool")])
        tool_calls = result.get("toolCalls")
        if (
            isinstance(tool_calls, list)
            and [call.get("name") for call in tool_calls if isinstance(call, dict)]
            == expected_sequence
        ):
            tool_pass += 1
        argument_checks += 1
        expected_arguments = dict(case.get("expectedArguments", {}))
        if "expectedProposalType" in case:
            expected_arguments["proposal_type"] = case["expectedProposalType"]
        arguments = result.get("arguments")
        try:
            if isinstance(arguments, dict) and isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
                        raise ValueError("agent tool sequence differs from the contract")
                    validate_agent_tool_arguments(
                        str(call["name"]), call["arguments"]  # type: ignore[arg-type]
                    )
                if not tool_calls or tool_calls[-1].get("arguments") != arguments:
                    raise ValueError("agent final tool arguments differ")
                expected_calls = case.get("expectedToolCalls")
                if expected_calls is not None and not _tool_calls_match_expected(
                    tool_calls, expected_calls
                ):
                    route_specific_evidence_passed = False
                    raise ValueError("agent multi-step arguments differ")
            else:
                raise ValueError("agent tool arguments must be an object")
            if all(arguments.get(key) == value for key, value in expected_arguments.items()):
                argument_pass += 1
        except ValueError:
            pass
        citation_checks += 1
        if _citations_are_faithful(case, result):
            citation_pass += 1
        required_terms = case.get("requiredTerms", [])
        if required_terms:
            terminology_checks += 1
            rendered = _rendered_output(result)
            if all(term in rendered for term in required_terms):
                terminology_pass += 1
        forbidden_output = (
            list(case.get("forbiddenTerms", []))
            + list(case.get("forbiddenClaims", []))
            + list(case.get("forbiddenTools", []))
        )
        observed_output = _policy_relevant_output(result).casefold()
        leaks += sum(
            1 for term in forbidden_output if str(term).casefold() in observed_output
        )
        latency = result.get("latencyMilliseconds")
        latencies.append(latency if isinstance(latency, int) else 0)

    case_count = len(by_id)
    metrics = AgentModelScore(
        case_count=case_count,
        tool_selection_accuracy=tool_pass / case_count,
        structured_argument_accuracy=_ratio(argument_pass, argument_checks),
        citation_fidelity=_ratio(citation_pass, citation_checks),
        terminology_preservation=_ratio(terminology_pass, terminology_checks),
        isolation_leak_count=leaks,
        invalid_structured_output_count=invalid,
        latency_milliseconds=tuple(latencies),
        route_specific_evidence_passed=route_specific_evidence_passed,
        passed=False,
    )
    passed = (
        metrics.tool_selection_accuracy == 1.0
        and metrics.structured_argument_accuracy == 1.0
        and metrics.citation_fidelity == 1.0
        and metrics.terminology_preservation == 1.0
        and metrics.isolation_leak_count == 0
        and metrics.invalid_structured_output_count == 0
    )
    return replace(metrics, passed=passed)


def _tool_calls_match_expected(tool_calls: list[object], expected_calls: object) -> bool:
    if not isinstance(expected_calls, list) or len(tool_calls) != len(expected_calls):
        return False
    for call, expected in zip(tool_calls, expected_calls, strict=True):
        if not isinstance(call, dict) or not isinstance(expected, dict):
            return False
        arguments = call.get("arguments")
        required = expected.get("expectedArguments")
        if (
            call.get("name") != expected.get("name")
            or not isinstance(arguments, dict)
            or not isinstance(required, dict)
            or not all(arguments.get(key) == value for key, value in required.items())
        ):
            return False
    return True


def _valid_result_types(result: dict[str, object]) -> bool:
    return (
        isinstance(result["toolName"], str)
        and isinstance(result["arguments"], dict)
        and isinstance(result["answer"], str)
        and isinstance(result["citationConceptIds"], list)
        and all(isinstance(item, str) for item in result["citationConceptIds"])
        and isinstance(result["latencyMilliseconds"], int)
        and not isinstance(result["latencyMilliseconds"], bool)
        and result["latencyMilliseconds"] >= 0
        and isinstance(result["toolCalls"], list)
        and bool(result["toolCalls"])
    )


def _citations_are_faithful(
    case: dict[str, object], result: dict[str, object]
) -> bool:
    visible = case.get("visibleContext", [])
    if not isinstance(visible, list):
        return False
    exact = {
        (
            item.get("conceptId"),
            item.get("sourceRevision"),
            item.get("contentSha256"),
            item.get("charStart"),
            item.get("charEnd"),
        )
        for item in visible
        if isinstance(item, dict)
    }
    allowed_ids = {str(item[0]) for item in exact}
    required = set(case.get("requiredCitationConceptIds", []))
    citations = result.get("citationConceptIds")
    if (
        not isinstance(citations, list)
        or len(set(citations)) != len(citations)
        or not set(citations) <= allowed_ids
        or not required <= set(citations)
    ):
        return False
    arguments = result.get("arguments")
    if not isinstance(arguments, dict):
        return False
    supplied = arguments.get("source_citations", [])
    if not isinstance(supplied, list):
        return False
    tuples = []
    for item in supplied:
        if not isinstance(item, dict):
            return False
        tuples.append(
            (
                item.get("concept_id"),
                item.get("source_revision"),
                item.get("content_sha256"),
                item.get("char_start"),
                item.get("char_end"),
            )
        )
    return (
        len(set(tuples)) == len(tuples)
        and set(tuples) <= exact
        and required <= {str(item[0]) for item in tuples} | set(citations)
    )


def _rendered_output(result: dict[str, object]) -> str:
    return str(result.get("answer", "")) + json.dumps(
        result.get("arguments", {}), ensure_ascii=False, sort_keys=True
    )


def _policy_relevant_output(result: dict[str, object]) -> str:
    arguments = result.get("arguments")
    proposed = (
        arguments.get("proposed_content", "") if isinstance(arguments, dict) else ""
    )
    return f"{result.get('toolName', '')} {result.get('answer', '')} {proposed}"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        raise ValueError("agent model metric has no denominator")
    return numerator / denominator


__all__ = ["AgentModelScore", "score_agent_model_results"]
