# ADR 0029: vLLM agent reasoning runtime on DGX Spark

**Date:** 2026-08-09  
**Status:** Accepted (canonical Phase 9 agent-serving amendment)  
**Amends:** [Voice OS architecture](../VOICE-OS-ARCHITECTURE.md) and the Phase 9 model-evidence portion of [ADR 0017](0017-knowledge-base-compiler.md)

## Context

The Voice OS frame previously named SGLang for agent inference because prefix
caching, structured outputs, and high-concurrency scheduling fit Yap's governed
agent workload. Phase 9 initially considered Qwen 3.6 35B-A3B NVFP4 and
Nemotron 3 Nano NVFP4 as universal candidates on one DGX Spark. Before the
frozen gate, the product owner rejected a universal-winner policy, removed
Nemotron from the agent candidate set, and assigned Qwen 3.6 to rapid automation
and Gemma 4 31B IT to complex orchestration. Nemotron remains separately
governed ASR technology, not a third agent route.

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

Qwen and Gemma are both required workload routes, not interchangeable fallback
models and not competitors for one universal winner. The frozen assignment is
Qwen to `rapid-automation` and Gemma to `complex-orchestration`. Each exact
checkpoint passes the common frozen admission workload and its route-specific
track through an owned, receipt-bound runtime. Candidate evidence binds the
exact image, model revision and artifact manifest, quantization, parser flags,
launch arguments, checked head, cgroup observations, concurrent prefix
isolation, in-flight cancellation, and teardown. Sequential Phase 9
qualification proves common safety, structured-output, isolation, cancellation,
and lifecycle admission independently. Exact private checked head
`36350d449735a4daea6546e16759f28f6f15631a` additionally passed the frozen Qwen
rapid-route and Gemma semantic multi-step tracks and returned
`required-workload-routes-qualified` with public-safe evidence SHA-256
`ca5a3f712ff737b92cc0d17979e5cd5b00e3034c880729e290a6f6ba255ca951`.
That outcome qualifies the two assigned workloads; it does not advertise a
production service or authorize silent cross-route substitution.
Exact aggregate candidate `a4f34678ea9980379b18266d40d3347b818ac57e`
then admitted that hash-locked private tree through semantic validation and
passed the complete knowledge gate with outcome
`governed-knowledge-gate-passed` and public-safe evidence SHA-256
`4013903410e22206c5b46f4dfcbf1878badc3dc9bbdfddb0ddad2ba0e2ff3260`.
This is aggregate gate admission, not production service promotion.
Simultaneous residency and sustained mixed-route capacity remain Phase 10
claims and require their own measured evidence.

Yap's server boundary owns authentication, authorization, retrieval, tool
policy, request admission, cancellation intent, audit, and publication. The
current explicit workload selector is Python; Rust-owned production
orchestration remains Phase 10. vLLM owns model
residency, continuous batching, prefix caching, structured decoding, and engine
scheduling. Model output never grants access or becomes canonical.

SGLang is removed from the executing Phase 9/10 path. Reconsidering it requires
a separately authorized workload comparison; Yap will not maintain duplicate
vLLM and SGLang production planes for speculative optionality.

## Consequences

- Qwen follows its validated DGX Spark runtime instead of preserving an
  incompatible architectural prediction.
- Qwen uses the `qwen3_xml` tool parser, `qwen3` reasoning parser, and
  `json-schema` final-response protocol.
- Gemma uses NVIDIA's Apache-2.0 ModelOpt NVFP4 checkpoint, the `gemma4` tool
  parser, no reasoning parser, and the `forced-answer-tool` final-response
  protocol. Its chat template is
  `/opt/vllm/vllm-src/examples/tool_chat_template_gemma4.jinja`, provenance-bound
  through the digest-pinned vLLM image and exact launch receipt rather than a
  copied repository artifact.
- Nemotron is removed from the agent-model set; it remains unrelated ASR
  technology where separately governed and is not retained as a speculative
  third agent route.
- Yap's Python server selector chooses the explicit workload class before
  inference. Runtime failure never silently reroutes a request to the other
  model; Rust-owned production orchestration remains Phase 10.
- Agent and ASR contracts remain separate even though both can use vLLM.
- Workload-route qualification depends on Yap quality, latency, concurrency,
  isolation, memory, cancellation, and teardown evidence—not headline TPS.
- Production advertisement still requires supervised service integration and
  the Phase 10 capacity, observability, recovery, and deployment gates.
- Persistent supervision and sustained mixed-user capacity remain Phase 10.
