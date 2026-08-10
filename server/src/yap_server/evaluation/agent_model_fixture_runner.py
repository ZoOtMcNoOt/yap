from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable

from yap_server.private_artifact import read_json_object_with_identity

from .agent_model_acceptance import load_agent_model_acceptance


JsonRequest = Callable[[dict[str, object]], dict[str, object]]


@dataclass(frozen=True, slots=True)
class AgentFixtureResult:
    case_id: str
    tool_name: str
    arguments: dict[str, object]
    answer: str
    citation_concept_ids: tuple[str, ...]
    latency_milliseconds: int

    def record(self) -> dict[str, object]:
        return {
            "caseId": self.case_id,
            "toolName": self.tool_name,
            "arguments": self.arguments,
            "answer": self.answer,
            "citationConceptIds": list(self.citation_concept_ids),
            "latencyMilliseconds": self.latency_milliseconds,
        }


def run_agent_model_fixtures(
    repository_root: Path,
    *,
    model: str,
    request_json: JsonRequest,
) -> tuple[AgentFixtureResult, ...]:
    """Run frozen cases through one OpenAI-compatible SGLang endpoint."""

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
    return tuple(
        _run_case(
            case,
            model=model,
            system_prompt=system_prompt,
            request_json=request_json,
        )
        for case in cases
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
    initial = request_json(
        {
            "model": model,
            "messages": messages,
            "tools": _tool_definitions(),
            "tool_choice": "required",
            "temperature": 0,
            "max_tokens": 512,
        }
    )
    assistant_message, tool_id, tool_name, arguments = _tool_call(initial)
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
    final = request_json(
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 512,
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
    )


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
    if not isinstance(answer, str) or not isinstance(citations, list) or not all(
        isinstance(item, str) for item in citations
    ):
        raise ValueError("agent final response fields are invalid")
    return answer, tuple(citations)


def _message(response: dict[str, object]) -> dict[str, object]:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
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
                "proposal_type": {"type": "string", "enum": ["summary", "relationship"]},
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
                        "required": ["concept_id", "source_revision", "content_sha256", "char_start", "char_end"],
                        "additionalProperties": False,
                    },
                },
            },
            ["purpose", "proposal_type", "proposed_content", "source_citations"],
        ),
    ]


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


__all__ = ["AgentFixtureResult", "run_agent_model_fixtures"]
