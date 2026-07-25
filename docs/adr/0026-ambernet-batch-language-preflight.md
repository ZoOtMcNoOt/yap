# ADR 0026: AmberNet batch language preflight

**Date:** 2026-07-22
**Status:** Accepted; client/server contract and isolated CPU implementation
execute. Exact executable candidate
`e4a62f4b8914e9233cd5229fa8f134f0c59fdbbb` passed the source-exact ARM64
resource/lifecycle boundary, five-window connected route, and complete 30-child
Phase 6 matrix. Hosted exact-head closure, final review, and merge remain.
Representative suggestion quality remains unpromoted and is not a Phase 6
product claim.
**Builds on:** [ADR 0020](0020-meeting-capture-diarization-authority.md),
[ADR 0024](0024-global-language-routing.md), and
[ADR 0025](0025-provider-specific-asr-serving.md)
**Supersedes:** the model, runtime, delivery, probe-selection, and score-threshold
details in [ADR 0008](0008-speechbrain-lid-gate.md)
**Amends:** ADR 0024's batch-preflight model/runtime/probe details; ADR 0024's
explicit user-confirmation and fail-visible manual-picker principles remain
authoritative

## Context

Phase 6 needs a bounded language suggestion for long, fixed-language imported
recordings. The suggestion exists because fixed-language ASR routes require an
explicit locale; it is not permission to silently choose a provider, locale, or
saved user preference.

The first implementation used SpeechBrain ECAPA in an isolated Python/Torch
component and sampled up to two 15-second regions. It established useful
containment and confirmation boundaries, but it retained a large Python/Torch
runtime solely for one classifier, sampled too little of long-tail recordings,
and did not share the exact released AmberNet family already accepted for
bounded local acoustic language evidence.

Focused development evidence for the exact NVIDIA AmberNet 1.12.0 static INT8
QDQ export found that:

- the graph has one fixed three-second `[1, 80, 304]` input and one 107-label
  logits output;
- the independently reconstructed NeMo frontend and full logits were identical
  across Windows AMD64 and disposable Linux ARM64 ONNX Runtime executions;
- a strict five-region rule caught every exercised midpoint and tail language
  switch without creating a fixed-language suggestion for those mixed files;
- relaxed majority rules created false tail suggestions and were rejected; and
- one one-thread Windows session added roughly 43 MB RSS in the focused smoke.

The exact executable commit later built on the ARM64 Spark and ran the real
verify-only artifact through Yap's actual `ContainerLidWorker` boundary. Under
one CPU, 512 MiB, 64 PIDs, no network, a read-only root, and one-thread runtime
settings, the synthetic contract workload peaked at 111,591,424 cgroup bytes
(about 106.4 MiB), six PIDs, and 682,363 CPU microseconds with no throttling,
memory-limit event, OOM, or retained container. Cold container wall time was
0.842 seconds. The owner-private receipt is outside Git; the synthetic silence
workload is execution/resource evidence, not language-accuracy evidence.

Those are implementation-selection observations, not locale qualification,
target-client proof, production capacity, or completion of the Phase 6 gate.

The released model is governed by NVIDIA NGC terms. Redistribution authority
has not been established. Yap therefore cannot bundle, mirror, or automatically
download the model merely because it can verify and execute an operator-provided
export.

## Decision

### 1. Use one exact verify-only AmberNet artifact

The server batch preflight uses:

- model identity `nvidia/nemo/langid_ambernet`;
- release `1.12.0`;
- the exact static classifier artifact
  `ambernet-1.12.0-classifier-int8-qdq.onnx`;
- an immutable byte size, SHA-256, 107-label order, graph signature, and frontend
  revision recorded by `server/lid-component.lock.json`; and
- an operator-controlled import directory containing exactly that artifact.

The application has no model URL, fetch, synchronization, fallback-artifact, or
first-use download path. Startup verifies the directory contents, regular-file
identity, size, and SHA-256 before an inference session is created. The image
does not contain the model. Redistribution remains `not-approved` until an
explicit license review changes that fact in a later accepted decision.

### 2. Keep the runtime small, isolated, and CPU-only

The component uses pinned Linux ARM64 Python 3.12, NumPy, and CPU ONNX Runtime.
It runs networkless, non-root, read-only, without an ASR GPU device, with one
intra-op thread, one inter-op thread, sequential execution, bounded memory,
bounded PIDs, bounded temporary storage, and a one-CPU container limit.

The current service starts one disposable worker container per admitted
preflight and admits at most one running plus two queued requests. That boundary
keeps untrusted media, model loading, cancellation, output, and teardown
contained while Phase 6 is unauthenticated. It is not a claim that per-request
loading is the final multi-user topology. Authenticated ownership/fairness
belongs to Phase 7, and a resident or cross-request-batched LID service requires
its own correctness, isolation, cancellation, memory, and sustained mixed-load
evidence no later than the Phase 10 production gate.

### 3. Sample five deterministic six-second regions

For a canonical mono PCM16 16-kHz source of `S` samples, with a six-second
region length `W = 96,000`, the client and server independently compute five
starts:

```text
start(i) = round_half_up((S - W) * i / 4), i in 0..4
```

The integer implementation is `(maximum_start * i + 2) / 4`. The first region
begins at source sample zero and the fifth ends at the exact source tail. At the
minimum accepted duration of 30 seconds the five regions are contiguous; for a
longer recording they are stratified near 0%, 25%, 50%, 75%, and 100%.

Each region must:

- be exactly six seconds and preserve its source offsets and source identity;
- contain at least 51,200 samples (3.2 seconds) of advisory VAD speech evidence;
- materialize as a bounded, hash-verified PCM WAV under the private request
  root; and
- remain evidence only—the corresponding source audio is never removed.

Any recording under 30 seconds, or any one of the five regions without enough
speech, skips model execution and opens the manual language path. The selector
accepts source lengths up to four hours so it can sample the exact tail without
duration-sized memory or work. That bound is a selector-safety contract, not a
claim that four-hour capture, upload, ASR, or result publication has passed
end-to-end.

### 4. Aggregate only inside a region; require agreement across regions

Each six-second region is split into two independent contiguous three-second
windows. Yap reconstructs the locked NeMo frontend for each window, executes
the fixed graph separately, averages the two 107-label logit vectors, then
applies a stable log-softmax. It records the raw top label, top log probability,
runner-up margin, source offsets, VAD count, and probe digest.

The five regions are never concatenated into one tensor, never padded with data
from another request, and never batched across users. A language suggestion is
valid only when all of the following are true:

1. exactly five independently verified observations are present;
2. every top-label margin is strictly greater than zero;
3. all five normalized ISO language codes agree;
4. that language maps to exactly one currently enabled fixed-locale ASR route;
5. the server decision matches the client's independent recomputation; and
6. the user explicitly confirms the suggested locale before the ASR job commits.

Missing or malformed evidence, zero-margin output, disagreement, unsupported
language, multiple enabled regional variants, timeout, cancellation, component
failure, or response mismatch opens the manual picker. The score is described
as a log-probability/margin under `mean-logit-log-softmax`, never as calibrated
confidence. A suggestion never mutates the saved primary locale.

### 5. Preserve the replaceable boundary

AmberNet does not own job identity, durable state, capture, transcript text,
provider selection, or the language picker. The Rust client owns source
selection and independently validates the response. The server owns immutable
artifact verification, isolated inference, bounded admission, and result
validation. Both sides consume the versioned capability and policy contract.

A later model may replace AmberNet only by introducing a new immutable artifact
and frontend contract, proving client/server compatibility and representative
behavior, recording license/provenance, and amending this ADR. It must not reuse
the AmberNet policy revision while changing the executed semantics.

## Consequences

### Positive

- The server removes Torch, TorchAudio, SpeechBrain, Hugging Face download code,
  and multiple model artifacts from this isolated component.
- Five source-stratified regions make midpoint and tail changes fail visible
  instead of allowing a start/middle plurality to masquerade as a fixed file.
- The exact frontend, label order, graph, artifact, policy, and response decision
  are independently checked at both trust boundaries.
- User confirmation and provider-neutral durable ownership survive future model
  replacement.

### Costs and limitations

- Strict five-region agreement abstains more often than a majority rule.
- Five regions require ten fixed graph executions, although work remains bounded
  independently of recording duration.
- The fixed three-second graph requires an exact maintained frontend; an
  ordinary variable-duration export was not accepted.
- Verify-only delivery requires an operator to acquire and import the model
  under applicable NVIDIA terms.
- The disposable-container topology favors containment over warm multi-user
  latency until later authenticated and production-capacity gates justify a
  resident service.
- AmberNet's publisher evaluation and Yap's focused development evidence do not
  certify every advertised ASR locale, noisy domain, accent, or meeting type.

## Rejected alternatives

- **Keep SpeechBrain as the executing batch service:** rejected because it
  retains a much larger dependency/runtime surface for a bounded classifier and
  preserves the weaker two-region long-tail policy.
- **Use majority agreement:** rejected because focused development evidence
  produced false fixed-language suggestions for tail switches.
- **Use only the first/middle or first/tail regions:** rejected because either
  can miss long-recording changes elsewhere in the source.
- **Silently use AmberNet's top label:** rejected because LID is advisory and
  regional locale ambiguity cannot be inferred safely.
- **Bundle or auto-download the NGC artifact:** rejected until explicit
  redistribution authority exists.
- **Move main ASR to CPU:** out of scope. CPU-only applies to this bounded
  preflight; server ASR remains on its provider-specific GPU runtime.

## Implementation and evidence boundary

The executing files include the component lock and isolated runtime under
`server/runtime/lid`, the AmberNet frontend/classifier and preflight policy under
`server/src/yap_server/lid`, and the mirrored Rust selection/response contract
under `desktop/src-tauri/src/server_connector/lid`.

Focused unit, contract, materialization, transport, and real-model smokes may
support this ADR while the branch changes. The final source-exact ARM64
repetition used the production `ContainerLidWorker` command builder at executable
head `a21964c19e56648e9fddcb5200de419e59a7687c`: one CPU, 512 MiB memory/swap,
64 PIDs, no network, a read-only root, and one-thread pools. It completed five
synthetic contract observations in 788 ms wall time, consumed 670,672 CPU
microseconds, reached 111,902,720 bytes current/peak cgroup memory and six peak
PIDs, emitted no memory events, and left no owned container, network, process,
listener, or request directory. The private evidence aggregate has SHA-256
`37fb2cad6c83c5e4084d07af18e1c9645cb758a29867d443bea368bdaf42bad7`;
audio, transcripts, host paths, and raw receipts remain outside Git.

That closed the earlier frozen-head component repetition, not representative
language-suggestion quality. Because the suggestion is assistive, requires
explicit user confirmation, and falls back visibly to the manual picker on
every ambiguous or failed outcome, Phase 6 does not make or require a broad
accuracy-promotion claim for it. Exact executable candidate
`e4a62f4b8914e9233cd5229fa8f134f0c59fdbbb` subsequently passed the frozen
local/native/server/private-runtime matrix, including the connected advertised
route and duration/lifecycle channels. Documentation lineage, hosted review, and
merge remain separate; no component or phase gate is relabeled as production
multi-user proof.
