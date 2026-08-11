from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable

from yap_server.knowledge.governed_answer_protocol import (
    FINAL_RESPONSE_PROTOCOLS,
    governed_answer_request_fields,
    read_governed_answer,
)
from yap_server.knowledge.knowledge_tool_contract import (
    governed_agent_tool_definitions,
    validate_governed_agent_tool_arguments,
)
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
    maximum_output_tokens: int,
    final_response_protocol: str,
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
    system_prompts = fixture["systemPrompts"]
    cases = fixture["cases"]
    if (
        not isinstance(system_prompts, dict)
        or not isinstance(system_prompts.get(workload_class), str)
        or not isinstance(cases, list)
    ):
        raise ValueError("agent workload fixture is invalid")
    system_prompt = system_prompts[workload_class]
    if not 1 <= maximum_output_tokens <= int(
        acceptance.runtime_tracks["maximumOutputTokens"]
    ):
        raise ValueError("agent fixture output bound is invalid")
    if final_response_protocol not in FINAL_RESPONSE_PROTOCOLS:
        raise ValueError("agent fixture final response protocol is invalid")
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
            maximum_output_tokens=maximum_output_tokens,
            final_response_protocol=final_response_protocol,
            request_json=request_json,
        )
        for case in selected_cases
    )


def warm_agent_model_fixture_runtime(
    *,
    model: str,
    maximum_output_tokens: int,
    final_response_protocol: str,
    request_json: JsonRequest,
) -> None:
    """Compile the exact tool and structured-output shapes before measurement."""

    if not model or not 1 <= maximum_output_tokens <= 4_096:
        raise ValueError("agent fixture warmup contract is invalid")
    warmup_output_tokens = min(maximum_output_tokens, 64)
    request_json(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Select the requested governed tool exactly once.",
                },
                {
                    "role": "user",
                    "content": (
                        "Call search_knowledge exactly once with purpose "
                        "knowledge.read and search_text runtime warmup."
                    ),
                },
            ],
            "tools": governed_agent_tool_definitions(),
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "temperature": 0,
            "max_tokens": warmup_output_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    )
    final_payload: dict[str, object] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return the requested answer structure only.",
            },
            {
                "role": "user",
                "content": "Return WARMUP_READY with no citations.",
            },
        ],
        "temperature": 0,
        "max_tokens": warmup_output_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    final_payload.update(
        governed_answer_request_fields(final_response_protocol)
    )
    request_json(final_payload)


def _run_case_safely(
    case: object,
    *,
    model: str,
    system_prompt: str,
    maximum_output_tokens: int,
    final_response_protocol: str,
    request_json: JsonRequest,
) -> AgentFixtureResult:
    started = time.monotonic()
    try:
        return _run_case(
            case,
            model=model,
            system_prompt=system_prompt,
            maximum_output_tokens=maximum_output_tokens,
            final_response_protocol=final_response_protocol,
            request_json=request_json,
        )
    except RuntimeError as error:
        if not isinstance(case, dict) or not isinstance(case.get("caseId"), str):
            raise
        raise RuntimeError(
            f"agent workload case {case['caseId']} failed"
        ) from error
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
    maximum_output_tokens: int,
    final_response_protocol: str,
    request_json: JsonRequest,
) -> AgentFixtureResult:
    if not isinstance(case, dict):
        raise ValueError("agent workload case is invalid")
    case_output_tokens = case.get("maximumOutputTokens", maximum_output_tokens)
    if (
        isinstance(case_output_tokens, bool)
        or not isinstance(case_output_tokens, int)
        or not 1 <= case_output_tokens <= maximum_output_tokens
    ):
        raise ValueError("agent workload case output bound is invalid")
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
    expected_arguments = case.get("expectedArguments", {})
    tools = governed_agent_tool_definitions(
        require_generation_sha256=(
            isinstance(expected_arguments, dict)
            and "expected_generation_sha256" in expected_arguments
        )
    )
    tool_calls: list[tuple[str, dict[str, object]]] = []
    for step_index, _expected_tool in enumerate(expected_sequence):
        response = request_json(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "required",
                "parallel_tool_calls": False,
                "temperature": 0,
                "max_tokens": case_output_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        )
        assistant_message, tool_id, tool_name, arguments = _tool_call(response)
        validate_governed_agent_tool_arguments(tool_name, arguments)
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
                        "items": _step_visible_context(
                            case,
                            step_index=step_index,
                            tool_name=tool_name,
                            arguments=arguments,
                        ),
                        "outputBudgetExhausted": False,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
        if step_index + 1 < len(expected_sequence):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The preceding tool call is complete. Select exactly one "
                        "not-yet-completed tool required by the original user "
                        "request. Never repeat a completed tool."
                    ),
                }
            )
    tool_name, arguments = tool_calls[-1]
    final_payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": case_output_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    final_payload.update(
        governed_answer_request_fields(final_response_protocol)
    )
    final = request_json(final_payload)
    answer, citations = read_governed_answer(final, final_response_protocol)
    return AgentFixtureResult(
        case_id=str(case["caseId"]),
        tool_name=tool_name,
        arguments=arguments,
        answer=answer,
        citation_concept_ids=citations,
        latency_milliseconds=max(0, round((time.monotonic() - started) * 1_000)),
        tool_calls=tuple(tool_calls),
    )


def _step_visible_context(
    case: dict[str, object],
    *,
    step_index: int,
    tool_name: str,
    arguments: dict[str, object],
) -> object:
    expected_calls = case.get("expectedToolCalls")
    if expected_calls is None:
        return case["visibleContext"]
    if not isinstance(expected_calls, list) or step_index >= len(expected_calls):
        raise ValueError("agent expected tool calls are invalid")
    expected = expected_calls[step_index]
    if not isinstance(expected, dict) or expected.get("name") != tool_name:
        return []
    required = expected.get("expectedArguments")
    if not isinstance(required, dict) or not all(
        arguments.get(key) == value for key, value in required.items()
    ):
        return []
    return case["visibleContext"]


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


__all__ = [
    "AgentFixtureResult",
    "run_agent_model_fixtures",
]
