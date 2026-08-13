from __future__ import annotations

import json
import re


_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def qualified_agent_vllm_batch_invariant(candidate: dict[str, object]) -> bool:
    """Return the exact batch-invariance policy for one locked route."""

    candidate_id = candidate.get("candidateId")
    if candidate_id == "qwen3.6-35b-a3b-nvfp4":
        return False
    if candidate_id == "gemma-4-31b-it-nvfp4":
        return True
    raise ValueError("agent vLLM launch candidate is invalid")


def validate_qualified_agent_vllm_route_policy(
    profile: dict[str, object],
    candidate: dict[str, object],
    *,
    maximum_model_length: int,
    maximum_sequences: int,
    maximum_batched_tokens: int,
    gpu_memory_utilization: str,
    load_format: str,
    memory_bytes: int,
    memory_swap_bytes: int,
    cpu_count: int,
    pids_limit: int,
    shm_bytes: int,
    tmpfs_bytes: int,
) -> None:
    """Require the route settings qualified for the two locked candidates."""

    common_valid = (
        maximum_model_length == 8192
        and maximum_batched_tokens == 8192
        and load_format == "fastsafetensors"
        and memory_bytes == memory_swap_bytes
        and cpu_count == 16
        and pids_limit == 4096
        and shm_bytes == 17_179_869_184
        and tmpfs_bytes == 8_589_934_592
        and profile.get("batchInvariant", False)
        is qualified_agent_vllm_batch_invariant(candidate)
    )
    if profile["profileId"] == "rapid-automation":
        valid = (
            common_valid
            and "batchInvariant" not in profile
            and candidate.get("reasoningParser")
            == profile.get("reasoningParser")
            == "qwen3"
            and "chatTemplate" not in candidate
            and profile.get("attentionBackend") == "flashinfer"
            and profile.get("moeBackend") == "marlin"
            and profile.get("speculativeConfig")
            == {
                "method": "mtp",
                "moe_backend": "triton",
                "num_speculative_tokens": 3,
            }
            and maximum_sequences == 4
            and gpu_memory_utilization == "0.40"
            and memory_bytes == 68_719_476_736
        )
    else:
        valid = (
            common_valid
            and profile.get("batchInvariant") is True
            and "reasoningParser" not in candidate
            and candidate.get("chatTemplate")
            == profile.get("chatTemplate")
            == "/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja"
            and maximum_sequences == 8
            and gpu_memory_utilization == "0.70"
            and memory_bytes == 103_079_215_104
        )
    if not valid:
        raise ValueError("agent service route policy differs")


def build_qualified_agent_vllm_launch_arguments(
    candidate: dict[str, object],
    *,
    model_path: str,
    host: str,
    port: int,
) -> tuple[str, ...]:
    """Build the shared route-specific vLLM command for an exact candidate."""

    candidate_id = candidate.get("candidateId")
    model = candidate.get("model")
    revision = candidate.get("revision")
    tool_parser = candidate.get("toolCallParser")
    final_response_protocol = candidate.get("finalResponseProtocol")
    if (
        candidate_id not in {"qwen3.6-35b-a3b-nvfp4", "gemma-4-31b-it-nvfp4"}
        or not isinstance(model, str)
        or not model
        or not isinstance(revision, str)
        or not _GIT_SHA.fullmatch(revision)
        or not isinstance(tool_parser, str)
        or not tool_parser
        or not isinstance(model_path, str)
        or not model_path.startswith("/")
        or host not in {"127.0.0.1", "0.0.0.0"}
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65_535
    ):
        raise ValueError("agent vLLM launch candidate is invalid")
    arguments = [
        "vllm",
        "serve",
        model_path,
        "--host",
        host,
        "--port",
        str(port),
        "--served-model-name",
        model,
    ]
    if candidate_id == "qwen3.6-35b-a3b-nvfp4":
        reasoning_parser = candidate.get("reasoningParser")
        if (
            reasoning_parser != "qwen3"
            or final_response_protocol != "json-schema"
            or "chatTemplate" in candidate
        ):
            raise ValueError("Qwen reasoning parser is invalid")
        arguments.extend(["--reasoning-parser", reasoning_parser])
    else:
        chat_template = candidate.get("chatTemplate")
        if (
            "reasoningParser" in candidate
            or final_response_protocol != "forced-answer-tool"
            or chat_template
            != "/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja"
        ):
            raise ValueError("Gemma response protocol is invalid")
        arguments.extend(["--chat-template", chat_template])
    arguments.extend(
        [
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            tool_parser,
            "--max-model-len",
            "8192",
            "--tensor-parallel-size",
            "1",
            "--kv-cache-dtype",
            "fp8",
            *(
                ["--enable-prefix-caching"]
                if candidate_id == "qwen3.6-35b-a3b-nvfp4"
                else ["--no-enable-prefix-caching"]
            ),
            "--enable-chunked-prefill",
            "--async-scheduling",
            "--language-model-only",
        ]
    )
    if candidate_id == "qwen3.6-35b-a3b-nvfp4":
        arguments.extend(
            [
                "--attention-backend",
                "flashinfer",
                "--moe-backend",
                "marlin",
                "--gpu-memory-utilization",
                "0.40",
                "--max-num-seqs",
                "4",
                "--max-num-batched-tokens",
                "8192",
                "--speculative-config",
                json.dumps(
                    {
                        "method": "mtp",
                        "moe_backend": "triton",
                        "num_speculative_tokens": 3,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "--load-format",
                "fastsafetensors",
            ]
        )
    else:
        arguments.extend(
            [
                "--gpu-memory-utilization",
                "0.70",
                "--max-num-seqs",
                "8",
                "--max-num-batched-tokens",
                "8192",
                "--load-format",
                "fastsafetensors",
            ]
        )
    return tuple(arguments)


__all__ = [
    "build_qualified_agent_vllm_launch_arguments",
    "qualified_agent_vllm_batch_invariant",
    "validate_qualified_agent_vllm_route_policy",
]
