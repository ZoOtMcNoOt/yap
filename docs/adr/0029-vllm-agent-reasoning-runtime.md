# ADR 0029: vLLM agent reasoning runtime on DGX Spark

**Date:** 2026-08-09  
**Status:** Accepted (canonical Phase 9 agent-serving amendment)  
**Amends:** [Voice OS architecture](../VOICE-OS-ARCHITECTURE.md) and the Phase 9 model-evidence portion of [ADR 0017](0017-knowledge-base-compiler.md)

## Context

The Voice OS frame previously named SGLang for agent inference because prefix
caching, structured outputs, and high-concurrency scheduling fit Yap's governed
agent workload. Phase 9 froze Qwen 3.6 35B-A3B NVFP4 and Nemotron 3 Nano NVFP4
as workload candidates on one DGX Spark.

The exact Qwen checkpoint failed to load in pinned SGLang 26.06 because its
W4A16/FP8 block layout was unsupported. The same immutable checkpoint loaded
successfully in NVIDIA's digest-pinned vLLM 26.06 ARM64 image on GB10, which
identified the mixed FP8/NVFP4 format and produced a valid strict
`search_knowledge` tool call. NVIDIA's current DGX Spark Qwen 3.6 deployment
guidance also uses vLLM. Generic benchmark claims, including 200+ aggregate
tokens per second, are not Yap workload evidence.

## Decision

Yap uses vLLM as the sole Phase 9 agent-model serving candidate and Phase 10
supervision target. The locked runtime is:

- `nvcr.io/nvidia/vllm:26.06-py3`;
- ARM64 digest `sha256:bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e`;
- Python 3.12;
- reported vLLM `0.22.1+7b9cb5b7.dev`.

Qwen and Nemotron remain model candidates until the same frozen Yap workload
passes through an owned, receipt-bound runtime. Candidate evidence binds the
exact image, model revision and artifact manifest, quantization, parser flags,
launch arguments, checked head, cgroup observations, concurrent prefix
isolation, in-flight cancellation, and teardown. The final selector accepts
only independently hash-anchored private evidence.

Rust/Yap owns authentication, authorization, retrieval, tool policy, request
admission, cancellation intent, audit, and publication. vLLM owns model
residency, continuous batching, prefix caching, structured decoding, and engine
scheduling. Model output never grants access or becomes canonical.

SGLang is removed from the executing Phase 9/10 path. Reconsidering it requires
a separately authorized workload comparison; Yap will not maintain duplicate
vLLM and SGLang production planes for speculative optionality.

## Consequences

- Qwen follows its validated DGX Spark runtime instead of preserving an
  incompatible architectural prediction.
- Agent and ASR contracts remain separate even though both can use vLLM.
- Promotion depends on Yap quality, latency, concurrency, isolation, memory,
  cancellation, and teardown evidence—not headline TPS.
- Persistent supervision and sustained mixed-user capacity remain Phase 10.
