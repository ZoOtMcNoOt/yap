from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance


_RESULT_KEYS = {
    "caseId",
    "toolName",
    "arguments",
    "answer",
    "citationConceptIds",
    "latencyMilliseconds",
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
    passed: bool


def score_agent_model_results(
    repository_root: Path, results: tuple[object, ...]
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
    cases = fixture["cases"]
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
    for case_id, case in by_id.items():
        result = result_by_id[case_id]
        if result.get("toolName") == case.get("expectedTool"):
            tool_pass += 1
        expected_arguments = dict(case.get("expectedArguments", {}))
        if "expectedProposalType" in case:
            expected_arguments["proposal_type"] = case["expectedProposalType"]
        if expected_arguments:
            argument_checks += 1
            arguments = result.get("arguments")
            if isinstance(arguments, dict) and all(
                arguments.get(key) == value for key, value in expected_arguments.items()
            ):
                argument_pass += 1
        required_citations = case.get("requiredCitationConceptIds", [])
        if required_citations:
            citation_checks += 1
            citations = result.get("citationConceptIds")
            observed = set(citations) if isinstance(citations, list) else set()
            argument_citations = _argument_citations(result.get("arguments"))
            if set(required_citations) <= observed | argument_citations:
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
        observed_output = (
            f"{result.get('toolName', '')} {_rendered_output(result)}".casefold()
        )
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
    )


def _argument_citations(value: object) -> set[str]:
    if not isinstance(value, dict):
        return set()
    citations = value.get("source_citations", [])
    if not isinstance(citations, list):
        return set()
    return {
        str(item["concept_id"])
        for item in citations
        if isinstance(item, dict) and isinstance(item.get("concept_id"), str)
    }


def _rendered_output(result: dict[str, object]) -> str:
    return str(result.get("answer", "")) + json.dumps(
        result.get("arguments", {}), ensure_ascii=False, sort_keys=True
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        raise ValueError("agent model metric has no denominator")
    return numerator / denominator


__all__ = ["AgentModelScore", "score_agent_model_results"]
