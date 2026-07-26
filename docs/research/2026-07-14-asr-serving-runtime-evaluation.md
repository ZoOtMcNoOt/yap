# ASR Serving Runtime Evaluation

**Snapshot:** 2026-07-14

**Superseded serving recommendation:** ADR 0025 (2026-07-21) retired the common
Triton ASR plane after focused implementation evidence. The current direction
uses digest-pinned vLLM for Cohere batch, a Transformers reference plus a
separate NeMo streaming candidate for Nemotron, SGLang for later agent/LLM
workloads, and Yap/Rust-owned orchestration. The analysis below is retained as
historical decision evidence; it is not the current implementation authority.

**Historical snapshot state:** On 2026-07-16 this record was reconciled against
the then-executing worker and upstream model/runtime surfaces, and a same-day
amendment brought a Triton 26.06 candidate into Phase 6. ADR 0025 later replaced
that recommendation; statements below about selecting or promoting Triton are
past decision evidence only.

**Historical decision at this snapshot:** Keep the checked NVIDIA PyTorch
26.06, Python 3.12, CUDA 13.3, Transformers, and BF16 path as the executable
Phase 5 baseline. This is a raw
one-job Transformers worker, not a persistent inference server. Treat NVIDIA
Triton Server 26.06 as the cross-provider ASR serving candidate, with raw Python,
NeMo/Transformers, or vLLM used only as model-specific backends that pass their
own gates. Do not promote Triton, a vLLM backend, or a quantized path until it
passes the same model identity, transcript quality, concurrency, resource,
process-cleanup, and Yap contract gates. For the
Nemotron 3.5 FastConformer-RNNT route planned by ADR 0024, benchmark the exact
NeMo toolkit and Transformers implementations as the current DGX Spark
candidates. NVIDIA also publishes a serving-oriented Nemotron ASR Streaming
NIM. NVIDIA's current ASR NIM support matrix says that model is not supported on
DGX Spark even though a separate performance page publishes Nemotron/DGX Spark
measurements. Until NVIDIA resolves that contradiction or Yap proves a pinned
image through its own gate, the support matrix remains the promotion authority
and the NIM is ineligible for Yap's GB10 target rather than silently ignored.
SGLang remains a candidate for later text/agent pools, not a current exact-model
route for either Yap ASR provider.

At this snapshot, the record evaluated runtime choices and authorized a
digest-pinned Phase 6 Triton candidate behind the existing worker interface. It
did not replace the locked Phase 4/5 runtime or claim performance until the
exact candidate was measured on GB10. ADR 0025 now governs implementation.

## Yap Requirements

The relevant requirements are narrower than choosing the fastest general LLM
server:

- Linux ARM64 on DGX Spark GB10 with Python 3.12;
- the exact Cohere ASR revision and its 14-language contract;
- offline, hash-verified model artifacts with no worker network access;
- mono PCM16/16 kHz batch input and Yap-owned create/upload/commit/status/result
  semantics;
- one bounded checked worker baseline, with measured Triton concurrency in
  Phase 6;
- transcript accuracy and provenance ahead of speculative low-bit savings; and
- no runtime/model port exposed to the desktop, LAN, or public internet.

The model/runtime adapter is replaceable. A replacement still has to preserve
the Yap API contract and pass license, artifact, WER, language, cancellation,
restart, retention, and process-containment evidence. A model or runtime label
alone is never sufficient.

## Candidates

| Candidate | What it provides | Fit for Yap's current/planned ASR routes | Main cost or risk |
| --- | --- | --- | --- |
| NVIDIA PyTorch `26.06-py3` + Transformers/BF16 | Python 3.12, CUDA 13.3, prerelease NVIDIA Torch 2.13, Torch-TensorRT 2.13, TensorRT 11, Model Optimizer, and a flexible PyTorch execution surface | Best known-correct baseline. Yap has already pinned its ARM64 digest, overlay, model artifacts, WER fixture, isolation command, and GB10 result | Cold model/container startup per job and no continuous batching; the broad framework image needs Yap's overlay and containment |
| NVIDIA Triton Server `26.06-py3` | Python 3.12, CUDA 13.3, TensorRT 11, ONNX Runtime, PyTorch 2 dynamic batching, Python/vLLM backends, concurrent and dynamic/sequence scheduling, health/metrics, Performance Analyzer, and Model Analyzer | Historical Phase 6 cross-provider serving candidate, later retired by ADR 0025. The attempted backends preserved model-specific execution but did not demonstrate a useful common serving plane. | Neither exact ASR route was drop-in proven. Yap had to pin the image/backend environments, preserve offline artifacts, implement audio/result adapters, tune variable-length batching, constrain shared memory/model control, and retain Rust-owned admission, fairness, cancellation, and durable state. |
| NVIDIA vLLM `26.06-py3` | Python 3.12, vLLM 0.22.1, Transformers 5.6, Torch 2.13, CUDA 13.3, continuous batching, and an OpenAI-compatible transcription API | Best next **Cohere-only** performance experiment. The current vLLM developer roster lists `CohereAsrForConditionalGeneration` and the exact Cohere Transcribe model | The roster does not itself prove that the NVIDIA 0.22.1 image loads the model; vLLM 0.19 has an open Cohere load issue, and Yap has no GB10 accuracy/latency/cleanup evidence. NVIDIA also warns about default GPU allocation on unified-memory systems such as DGX Spark. It does not add Nemotron 3.5 RNNT support |
| Upstream vLLM `0.25.1` | A concrete upstream source/runtime comparison point | Confirms that Cohere is an active supported transcription architecture | Its build pins Torch 2.11.0, which conflicts with Yap's checked NVIDIA Torch 2.13 worker. It must not be pip-installed over that image; the Cohere publisher's vLLM 0.19 recipe also has an open upstream load issue |
| NeMo toolkit or Transformers 5.13+ | Exact NVIDIA-supported implementations for Nemotron 3.5 cache-aware FastConformer-RNNT | Current DGX Spark Phase 6 candidates for a separately pinned Nemotron reference worker and `target_lang=auto` route | No Yap server worker/lock, route correctness, GB10 resource, cancellation, or teardown evidence existed at this research checkpoint; current implementation status is authoritative in ADR 0025 |
| NVIDIA Nemotron ASR Streaming NIM | A serving container with batching, HTTP/gRPC/realtime surfaces, multilingual automatic detection, and published profiles | A legitimate serving option on supported hardware, but not a current Yap GB10 candidate | NVIDIA's support matrix limits DGX Spark to Parakeet 1.1B CTC English and Parakeet 1.1B RNNT Multilingual, while its performance page separately lists Nemotron/DGX Spark measurements. Treat the conflict as unresolved and reject promotion until a supported pinned image passes Yap's full gate |
| NVIDIA SGLang `26.06-py3` | Python 3.12, SGLang 0.5.12.post1, Torch 2.13, CUDA 13.3, DGX Spark support, and FP8/NVFP4 features for supported models | Useful later for Yap's text generation or agent workloads | Current SGLang surfaces do not document Cohere Transcribe, and its Parakeet component is an encoder for Nano Nemotron VL rather than the standalone Nemotron 3.5 RNNT decoder. It is not a current Yap ASR route |
| Torch-TensorRT or a custom TensorRT export | Potential engine-level latency and memory improvements | A later optimization experiment if the Cohere encoder-decoder graph exports cleanly | Model-specific conversion, dynamic generation, calibration, accuracy parity, and artifact provenance are unproven |

## Why BF16 Remains The Default

The locked Cohere model is a 2-billion-parameter BF16 checkpoint of about
4.13 GB. That is not a memory-pressure reason by itself to accept an unverified
quantized derivative on the GB10. The existing BF16 path has executable WER,
runtime-attestation, artifact-hash, and cleanup evidence; the low-bit paths do
not.

vLLM supports several quantization families and Blackwell-oriented formats in
general, while the Cohere model page lists community quantized derivatives.
Neither fact proves that a specific Cohere ASR quantization preserves Yap's
WER, multilingual behavior, punctuation, long-audio stability, or licensing
and byte provenance. Quantization is therefore benchmark-gated rather than a
Phase 5 default.

The historical first Cohere Triton backend was intended to retain the
unquantized BF16 model and the checked Python 3.12/NVIDIA PyTorch 26.06
environment. That isolates warm serving, scheduling, and batching effects
without changing weights or precision. A
separately pinned vLLM backend remains a Cohere-specific challenger only after
the raw backend has established contract parity. Only if measured memory,
throughput, or latency creates a real need should the same harness evaluate FP8
or a Blackwell-native four-bit format. Every candidate needs a newly pinned
model artifact identity; a community checkpoint is not inherited as trusted
merely because it names the canonical model as its base.

The later pre-ADR 0025 implementation proved a pinned Triton adapter and bounded
concurrent behavior, but the provider-specific comparison rejected it and its
implementation was removed. That historical comparison never made
authenticated ownership or persistent supervised mixed live/batch production
capacity a Phase 6 claim. Phase 7 owns authenticated owner derivation; Phase 10
owns supervised multi-worker service, production capacity/SLO promotion, and
enterprise observability.

The first measured Python-backend profile demonstrated why model-valid batching
must be proved rather than assumed: Cohere cross-request batches changed exact
text, while Nemotron scheduler batches still executed as serial singletons. The
current `single-resident-queued-v1` successor therefore keeps one resident GPU
instance per model and bounds concurrency with ordered singleton execution.
Focused dirty-source GB10 probes restore exact Cohere fixed, Nemotron fixed, and
Nemotron dynamic parity, retain one authoritative output under c4 load, and
cancel a queued follower without disrupting the leader or immediate recovery.
This is a viable frozen-comparison candidate, not a production selection; true
model batching remains a separate challenger that must prove both exact output
and material workload improvement.

## Historical Promotion Benchmark

A Triton, vLLM-backend, or quantized candidate can replace the baseline only
after a disposable, digest-pinned GB10 run records all of the following against
the same audio set:

1. exact model/revision and container/runtime identities;
2. WER and punctuation parity by supported language, not only one English clip;
3. cold-start time, warm real-time factor, p50/p95/p99 latency, queue time, peak
   unified memory, and sustained one/two/three-plus-job throughput;
4. long-audio behavior through Yap's four-hour admission boundary and practical
   shorter fixtures;
5. cancellation, timeout, restart, queue saturation, and clean container/process
   teardown;
6. identical Yap result authority, hashes, replay behavior, and error semantics;
7. offline artifact loading and proof that no runtime/model port becomes a
   client-facing interface; and
8. license, notice, digest, vulnerability-review, and model-provenance records.

Triton Performance Analyzer and Model Analyzer should sweep request concurrency,
model instances, and only model-valid dynamic/sequence batching settings. The
accepted configuration must satisfy latency constraints rather than maximize
throughput blindly. For NVIDIA vLLM 26.06 on DGX Spark, the benchmark must
explicitly set and record a bounded `--kv-cache-memory-bytes` or
`--gpu-memory-utilization` value; the default whole-device percentage is
inappropriate for shared unified memory. Yap's current eight-request,
1,024-token Cohere candidate uses a 1 GiB KV cache. Any larger value remains a
measurement result rather than an architectural constant.

## Sources

- [NVIDIA PyTorch 26.06 release notes](https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-26-06.html)
- [NVIDIA Triton Server 26.06 release notes](https://docs.nvidia.com/deeplearning/triton-inference-server/release-notes/rel-26-06.html)
- [NVIDIA Triton architecture and scheduling](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/index.html)
- [NVIDIA Triton Model Analyzer](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_analyzer.html)
- [NVIDIA vLLM 26.06 release notes](https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-26-06.html)
- [vLLM 0.22.1 supported transcription models](https://docs.vllm.ai/en/v0.22.1/models/supported_models/#transcription)
- [vLLM online speech-to-text APIs](https://docs.vllm.ai/en/stable/serving/online_serving/#speech-to-text-apis)
- [vLLM 0.25.1 CUDA dependency pin](https://raw.githubusercontent.com/vllm-project/vllm/v0.25.1/requirements/cuda.txt)
- [Open vLLM 0.19 Cohere load issue](https://github.com/vllm-project/vllm/issues/39252)
- [NVIDIA SGLang 26.06 release notes](https://docs.nvidia.com/deeplearning/frameworks/sglang-release-notes/rel-26-06.html)
- [Cohere Transcribe model card](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)
- [Nemotron 3.5 ASR Streaming model card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [NVIDIA NeMo ASR inference surface](https://docs.nvidia.com/nemo/speech/nightly/asr/inference.html) (pin the selected NeMo release/revision in the worker lock before implementation)
- [Nemotron ASR Streaming NIM deployment](https://docs.nvidia.com/nim/speech/latest/asr/deploy-asr-models/nemotron-asr-streaming.html)
- [NVIDIA ASR NIM support matrix](https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html)
- [NVIDIA ASR NIM performance tables](https://docs.nvidia.com/nim/speech/latest/reference/performances/asr/performance.html)
- [SGLang 0.5.12.post1 Parakeet encoder component](https://github.com/sgl-project/sglang/blob/v0.5.12.post1/python/sglang/srt/models/parakeet.py)
- [vLLM quantization overview](https://docs.vllm.ai/en/stable/features/quantization/)
- [LLM Compressor scheme selection](https://docs.vllm.ai/projects/llm-compressor/en/latest/steps/choosing-scheme/)
