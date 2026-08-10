from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable
import re

from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance


JsonRequest = Callable[[dict[str, object]], dict[str, object]]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AgentFixtureResult:
    case_id: str
    tool_name: str
    arguments: dict[str, object]
    answer: str
    citation_concept_ids: tuple[str, ...]
    latency_milliseconds: int
    tool_calls: tuple[tuple[str, dict[str, object]], ...]
    invalid_structured_output: bool = False

    def record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "caseId": self.case_id,
            "toolName": self.tool_name,
            "arguments": self.arguments,
            "answer": self.answer,
            "citationConceptIds": list(self.citation_concept_ids),
            "latencyMilliseconds": self.latency_milliseconds,
            "toolCalls": [
                {"name": name, "arguments": arguments}
                for name, arguments in self.tool_calls
            ],
        }
        if self.invalid_structured_output:
            record["invalidStructuredOutput"] = True
        return record


def run_agent_model_fixtures(
    repository_root: Path,
    *,
    model: str,
    workload_class: str,
    request_json: JsonRequest,
) -> tuple[AgentFixtureResult, ...]:
    """Run frozen cases through one OpenAI-compatible reasoning endpoint."""

    acceptance = load_agent_model_acceptance(repository_root)
    fixture, _identity = read_json_object_with_identity(
        repository_root / "server" / "agent-workload-fixtures.json",
        maximum_bytes=256_000,
        field="agent workload fixtures",
        expected_sha256=acceptance.fixture_sha256,
        containment_root=repository_root,
    )
    system_prompt = fixture["sharedSystemPrompt"]
    cases = fixture["cases"]
    if not isinstance(system_prompt, str) or not isinstance(cases, list):
        raise ValueError("agent workload fixture is invalid")
    selected_cases = [
        case
        for case in cases
        if isinstance(case, dict)
        and case.get("requiredForWorkloadClass") in {None, workload_class}
    ]
    return tuple(
        _run_case_safely(
            case,
            model=model,
            system_prompt=system_prompt,
            request_json=request_json,
        )
        for case in selected_cases
    )


def _run_case_safely(
    case: object,
    *,
    model: str,
    system_prompt: str,
    request_json: JsonRequest,
) -> AgentFixtureResult:
    started = time.monotonic()
    try:
        return _run_case(
            case,
            model=model,
            system_prompt=system_prompt,
            request_json=request_json,
        )
    except ValueError:
        if not isinstance(case, dict) or not isinstance(case.get("caseId"), str):
            raise
        return AgentFixtureResult(
            case_id=case["caseId"],
            tool_name="",
            arguments={},
            answer="",
            citation_concept_ids=(),
            latency_milliseconds=max(0, round((time.monotonic() - started) * 1_000)),
            tool_calls=(),
            invalid_structured_output=True,
        )


def _run_case(
    case: object,
    *,
    model: str,
    system_prompt: str,
    request_json: JsonRequest,
) -> AgentFixtureResult:
    if not isinstance(case, dict):
        raise ValueError("agent workload case is invalid")
    started = time.monotonic()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": case["user"]},
    ]
    if (
        case.get("expectedTool") == "propose_knowledge"
        and "expectedToolSequence" not in case
    ):
        messages.extend(_retrieval_messages(case))
    expected_sequence = tuple(case.get("expectedToolSequence", [case["expectedTool"]]))
    tool_calls: list[tuple[str, dict[str, object]]] = []
    for _expected_tool in expected_sequence:
        response = request_json(
            {
                "model": model,
                "messages": messages,
                "tools": _tool_definitions(),
                "tool_choice": "required",
                "temperature": 0,
                "max_tokens": 512,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        )
        assistant_message, tool_id, tool_name, arguments = _tool_call(response)
        validate_agent_tool_arguments(tool_name, arguments)
        tool_calls.append((tool_name, arguments))
        messages.append(assistant_message)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": tool_name,
                "content": json.dumps(
                    {
                        "generationSha256": "f" * 64,
                        "items": case["visibleContext"],
                        "outputBudgetExhausted": False,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
    tool_name, arguments = tool_calls[-1]
    final = request_json(
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 512,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "governed_answer",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                            "citationConceptIds": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["answer", "citationConceptIds"],
                        "additionalProperties": False,
                    },
                },
            },
        }
    )
    answer, citations = _final_answer(final)
    return AgentFixtureResult(
        case_id=str(case["caseId"]),
        tool_name=tool_name,
        arguments=arguments,
        answer=answer,
        citation_concept_ids=citations,
        latency_milliseconds=max(0, round((time.monotonic() - started) * 1_000)),
        tool_calls=tuple(tool_calls),
    )


def _retrieval_messages(case: dict[str, object]) -> list[dict[str, object]]:
    tool_id = f"retrieval-{case['caseId']}"
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": "search_knowledge",
                        "arguments": json.dumps(
                            {
                                "purpose": "knowledge.read",
                                "search_text": case["user"],
                            },
                            separators=(",", ":"),
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tool_id,
            "name": "search_knowledge",
            "content": json.dumps(
                {
                    "generationSha256": "f" * 64,
                    "items": case["visibleContext"],
                    "outputBudgetExhausted": False,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def _tool_call(
    response: dict[str, object],
) -> tuple[dict[str, object], str, str, dict[str, object]]:
    message = _message(response)
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise ValueError("agent response must contain exactly one tool call")
    call = calls[0]
    function = call.get("function")
    if not isinstance(call.get("id"), str) or not isinstance(function, dict):
        raise ValueError("agent tool call identity is invalid")
    name = function.get("name")
    raw_arguments = function.get("arguments")
    if not isinstance(name, str) or not isinstance(raw_arguments, str):
        raise ValueError("agent tool call is invalid")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ValueError("agent tool arguments are not valid JSON") from error
    if not isinstance(arguments, dict):
        raise ValueError("agent tool arguments must be an object")
    return message, call["id"], name, arguments


def _final_answer(response: dict[str, object]) -> tuple[str, tuple[str, ...]]:
    content = _message(response).get("content")
    if not isinstance(content, str):
        raise ValueError("agent final response content is invalid")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("agent final response is not valid JSON") from error
    if not isinstance(value, dict) or set(value) != {"answer", "citationConceptIds"}:
        raise ValueError("agent final response differs from the contract")
    answer = value["answer"]
    citations = value["citationConceptIds"]
    if (
        not isinstance(answer, str)
        or not isinstance(citations, list)
        or not all(isinstance(item, str) for item in citations)
    ):
        raise ValueError("agent final response fields are invalid")
    return answer, tuple(citations)


def _message(response: dict[str, object]) -> dict[str, object]:
    choices = response.get("choices")
    if (
        not isinstance(choices, list)
        or len(choices) != 1
        or not isinstance(choices[0], dict)
    ):
        raise ValueError("agent response choices are invalid")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("agent response message is invalid")
    return message


def _tool_definitions() -> list[dict[str, object]]:
    common = {
        "purpose": {"type": "string", "enum": ["knowledge.read"]},
        "expected_generation_sha256": {"type": ["string", "null"]},
    }
    return [
        _tool(
            "search_knowledge",
            "Search permission-filtered knowledge.",
            {
                **common,
                "search_text": {"type": "string"},
                "maximum_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            ["purpose", "search_text"],
        ),
        _tool(
            "browse_knowledge",
            "Browse visible knowledge concepts.",
            common,
            ["purpose"],
        ),
        _tool(
            "traverse_knowledge",
            "Traverse visible typed relationships.",
            {
                **common,
                "start_concept_id": {"type": "string"},
                "maximum_depth": {"type": "integer", "minimum": 1, "maximum": 4},
                "maximum_results": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["purpose", "start_concept_id"],
        ),
        _tool(
            "propose_knowledge",
            "Store a cited noncanonical proposal.",
            {
                **common,
                "proposal_type": {
                    "type": "string",
                    "enum": ["summary", "relationship"],
                },
                "proposed_content": {"type": "string"},
                "source_citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept_id": {"type": "string"},
                            "source_revision": {"type": "string"},
                            "content_sha256": {"type": "string"},
                            "char_start": {"type": "integer"},
                            "char_end": {"type": "integer"},
                        },
                        "required": [
                            "concept_id",
                            "source_revision",
                            "content_sha256",
                            "char_start",
                            "char_end",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            ["purpose", "proposal_type", "proposed_content", "source_citations"],
        ),
    ]


def validate_agent_tool_arguments(name: str, arguments: dict[str, object]) -> None:
    """Apply the exact frozen product-tool bounds to model-authored arguments."""

    if not isinstance(arguments, dict):
        raise ValueError("agent tool arguments must be an object")
    common = {"purpose", "expected_generation_sha256"}
    required: set[str]
    allowed: set[str]
    if name == "search_knowledge":
        required = {"purpose", "search_text"}
        allowed = common | {"search_text", "maximum_results"}
        _bounded_text(arguments.get("search_text"), "search text", 4_096)
        _optional_integer(arguments.get("maximum_results"), 1, 10)
    elif name == "browse_knowledge":
        required = {"purpose"}
        allowed = common
    elif name == "traverse_knowledge":
        required = {"purpose", "start_concept_id"}
        allowed = common | {"start_concept_id", "maximum_depth", "maximum_results"}
        _bounded_text(arguments.get("start_concept_id"), "start concept ID", 512)
        _optional_integer(arguments.get("maximum_depth"), 1, 4)
        _optional_integer(arguments.get("maximum_results"), 1, 50)
    elif name == "propose_knowledge":
        required = {
            "purpose",
            "proposal_type",
            "proposed_content",
            "source_citations",
        }
        allowed = common | required
        if arguments.get("proposal_type") not in {"summary", "relationship"}:
            raise ValueError("agent proposal type is invalid")
        _bounded_text(arguments.get("proposed_content"), "proposed content", 100_000)
        _validate_citations(arguments.get("source_citations"))
    else:
        raise ValueError("agent selected an unknown tool")
    if set(arguments) - allowed or not required <= set(arguments):
        raise ValueError("agent tool arguments differ from the contract")
    if arguments.get("purpose") != "knowledge.read":
        raise ValueError("agent tool purpose is invalid")
    generation = arguments.get("expected_generation_sha256")
    if generation is not None and (
        not isinstance(generation, str) or not _SHA256.fullmatch(generation)
    ):
        raise ValueError("agent expected generation is invalid")


def _validate_citations(value: object) -> None:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ValueError("agent proposal citations are invalid")
    identities: set[tuple[object, ...]] = set()
    for citation in value:
        if not isinstance(citation, dict) or set(citation) != {
            "concept_id",
            "source_revision",
            "content_sha256",
            "char_start",
            "char_end",
        }:
            raise ValueError("agent proposal citation differs from the contract")
        _bounded_text(citation["concept_id"], "citation concept ID", 512)
        _bounded_text(citation["source_revision"], "citation revision", 512)
        digest = citation["content_sha256"]
        start = citation["char_start"]
        end = citation["char_end"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("agent proposal citation digest is invalid")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise ValueError("agent proposal citation span is invalid")
        identity = tuple(citation[key] for key in sorted(citation))
        if identity in identities:
            raise ValueError("agent proposal citation is duplicated")
        identities.add(identity)


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value.strip() != value
    ):
        raise ValueError(f"agent {field} is invalid")
    return value


def _optional_integer(value: object, minimum: int, maximum: int) -> None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError("agent tool integer bound is invalid")


def _tool(
    name: str,
    description: str,
    properties: dict[str, object],
    required: list[str],
) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


__all__ = [
    "AgentFixtureResult",
    "run_agent_model_fixtures",
    "validate_agent_tool_arguments",
]
