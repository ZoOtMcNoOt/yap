# ADR 0025: Provider-specific ASR serving runtimes

**Date:** 2026-07-21
**Status:** Accepted; Cohere vLLM and Nemotron NeMo adapters, checked
container/launcher contracts, and a sequential lifecycle-gate composition are
implemented under focused tests; the frozen GB10 execution and both promotion
decisions remain incomplete
**Amends:** [ADR 0014](0014-server-tier-compute-topology.md) and
[ADR 0024](0024-global-language-routing.md)
**Meeting serving amended by:** [ADR 0027](0027-tiron-joint-speaker-attributed-meeting-transcription.md) (Phase 8 selects a separate Tiron joint speaker-attributed worker without changing the Phase 6 Cohere/Nemotron gates)

## Context

ADR 0014 and the first ADR 0024 implementation treated NVIDIA Triton Inference
Server as a common ASR execution plane. Focused implementation showed that the
abstraction did not match the models:

- Cohere Transcribe is explicitly supported by vLLM's transcription API and its
  model card recommends vLLM for production serving.
- Nemotron 3.5 ASR Streaming is a cache-aware FastConformer-RNNT model exposed
  through NVIDIA NeMo and a Transformers `AutoModelForRNNT` reference. It is not
  a supported vLLM transcription architecture.
- The rejected Triton Python-backend experiment serialized model calls to retain
  output parity, duplicated request scheduling already owned by Yap and the
  model runtime, and added a large backend/client/evidence surface without a
  demonstrated performance advantage.
- SGLang is still useful for later agent/LLM workloads. It is not an ASR runtime
  for either selected ASR model.

One universal model server would therefore be a false simplification. The stable
abstraction is Yap's provider-neutral job, route, result, admission, and
cancellation contract; the model-serving implementation remains provider
specific behind that seam.

## Decision

1. **Cohere batch uses vLLM.** The candidate runtime is NVIDIA vLLM 26.06 on
   Linux ARM64/Python 3.12, pinned by repository digest and exact package
   versions. Yap calls the authenticated, loopback-only
   `/v1/audio/transcriptions` interface with one independent request per job.
   vLLM owns model residency, continuous batching, and GPU scheduling. Yap owns
   bounded admission, durable job state, routing, cancellation intent, result
   validation, and publication.
2. **Nemotron is not sent through vLLM.** The pinned Transformers/BF16 path
   remains the correctness and rollback reference. A resident NVIDIA NeMo
   candidate now executes behind the same provider-neutral job/result contract
   because NeMo is the model-native runtime. It remains unselected until its own
   frozen correctness, streaming, cancellation, latency, memory, concurrency,
   duration, and lifecycle gate passes.
3. **Local Nemotron remains sherpa-onnx.** The Q4-or-better local artifact and
   CPU-first fallback contract are unchanged by this server decision.
4. **Triton Inference Server is retired from the current Yap ASR serving plane.**
   Its implementation-only backend, client, scheduling, parity, and benchmark
   machinery are removed. Private focused evidence remains historical evidence
   for the rejected candidate and is not published as product data.
5. **SGLang remains the Phase 9 agent/LLM serving candidate.** Prefix caching and
   structured generation apply to agent workloads, not to Cohere or Nemotron
   audio decoding.
6. **Rust remains the target orchestration authority.** The current Python
   service preserves the same bounded contracts until that later migration is
   justified and gated; this ADR does not move model inference into Rust.

## Runtime and security constraints

- The vLLM endpoint must be an explicit numeric loopback HTTP authority. DNS
  names, user information, paths, non-loopback addresses, and implicit ports
  fail closed.
- A private API key is mandatory and is passed only as process/container
  environment, never committed or written to evidence.
- Startup verifies the exact vLLM version, single served model identity, and all
  immutable model artifacts before admitting work.
- The launcher rejects root and runs the container as the invoking model-owner
  UID/GID so private host model directories do not need broader permissions.
- Docker publishes no provider-container port. Each foreground launcher owns a
  `setsid`-isolated `socat` process group with a fixed 32-connection child and
  backlog ceiling that forwards one numeric `127.0.0.1` port to the
  container-private address. The unauthenticated Yap development service also
  remains loopback-only. SSH tunneling is the current LAN-development boundary
  until Phase 7 authentication and later enterprise network controls exist.
  The proxy starts with a cleared environment and therefore does not inherit
  either provider API key.
- Each resident launcher also requires an existing internal Docker bridge whose
  owner and exact revision labels match the checked head. The checked lifecycle
  wrapper owns that temporary network and removes it before evidence
  publication; the provider containers have no external egress through it. The
  launcher requires `socat`, `setsid`, `ss`, and `ps`, validates the exact
  loopback listener, and terminates the complete proxy process group before
  returning.
- The vLLM worker rejects punctuation-off requests because the pinned Cohere
  decoder currently fixes the `<|pnc|>` control token.
- HTTP request bodies and responses are bounded. Cancellation explicitly shuts
  down the active socket so a thread blocked in the response read wakes and the
  server observes the disconnect. The pinned vLLM route then cancels its handler
  and calls the engine abort boundary. Yap requires bounded acknowledgement; an
  unaccounted request fences the pool.
- The NeMo candidate accepts only an exact checked `.nemo` artifact, pinned
  NeMo/Torch/CUDA identity, and the checked 1.12-second cache-aware profile with
  `[56, 13]` attention context. All shared model/pipeline mutation stays on one
  scheduler owner; Yap admits at most eight active and eight queued jobs.
- The pinned unified NeMo wrapper accepted prompt vectors without applying them
  in the exercised path. Yap validates prompt IDs against the checkpoint's
  `num_prompts` bound and applies the per-request prompt projection after the
  encoder and before RNNT decode. That correction is regression-tested against
  the pinned source and is not represented as an upstream NeMo behavior.
- The resident NeMo service reads only hash-bound regular WAV/utterance-plan
  files under the same private storage root, requires its own API key, publishes
  only numeric loopback, rejects duplicate identities and excess admission,
  and cancels a job without cancelling its siblings.
- Provider startup transfers worker ownership incrementally: if a later provider
  fails to build, every earlier worker is closed before startup returns the
  error. No partially built multi-provider registry survives.
- NeMo connection creation is inside the bounded containment interval. If it
  cannot be interrupted before a connection object exists, shutdown fences the
  pool, cancels pending futures, reports `WorkerContainmentError`, and does not
  wait forever on the blocked executor thread.
- The schema-4 runtime plan names this executable internal boundary
  `nemo-nemotron-finalized`: it processes bounded finalized utterances and
  recordings through the provider-neutral worker contract. It is not the
  unimplemented client-facing `/v1/live` WebSocket transport. The committed
  capability catalog continues to omit unpromoted Nemotron routes; an
  end-to-end candidate-catalog qualification must use an explicit lock outside
  the repository and cannot be treated as promotion.
- NVIDIA's 26.06 vLLM image omits TorchAudio even though its Cohere processor
  imports one TorchAudio function. Yap carries only an attributed BSD-2-Clause
  Mel-filter-bank compatibility function. A mismatched compiled TorchAudio wheel
  is forbidden because it fails against the image's CUDA 13.3 Torch build.
- Production Transformers, NeMo, and LID images remove the
  `yap_server.evaluation` package. WER helpers needed by a runtime contract live
  in the neutral `transcript_metrics` module; evaluation code and private media
  enter only through the explicit evaluation image or qualification mount.
- The initial GB10 candidate permits at most eight 1,024-token sequences, fixes
  the KV cache at 1 GiB, and retains a 512 MiB upload envelope. The explicit
  cache bound avoids vLLM's whole-device percentage heuristic reserving unified
  memory for hundreds of impossible requests. These are frozen benchmark
  inputs, not production capacity or four-hour performance claims.
- `--max-num-seqs 8` bounds vLLM's active scheduler work but does not establish
  an HTTP rejection boundary; vLLM can queue additional requests. Yap's
  executable capacity contract therefore stays with `BatchAsrPool`: eight
  running plus eight queued reservations and one aggregate four-hour PCM-byte
  budget. The seventeenth slot request, or the first request beyond the PCM
  budget, must fail before release with retryable pool backpressure and then
  succeed after the accepted work drains. NeMo separately owns an authenticated
  eight-active service limit and returns typed HTTP 429 for the ninth request.
- Specialized private qualification runners distinguish typed cancellation
  from generic failure and prove immediate recovery. The pinned vLLM
  client-disconnect path calls the engine abort boundary, but externally freed
  requests do not enter its finished-request histogram; the runner therefore
  distinguishes that one-stop accounting shape from a counted abort, provider
  completion after cancellation, and ambiguous metrics. The NeMo runner proves
  the distinct fixed/automatic language-evidence contracts at c1 and c8 while
  recording lexical and rendered-text parity for later provider promotion.
  These are executable gate mechanics; no checked-head capacity or promotion
  claim exists until the frozen GB10 runs pass.
- Exact readiness retries only typed transport/startup unavailability. A wrong
  API key, runtime version, served model, or malformed readiness response fails
  immediately instead of being hidden behind the startup timeout.

## Consequences

### Positive

- Cohere uses a runtime that natively exposes its supported transcription API
  and continuous scheduler, eliminating Yap-owned cross-request tensor assembly.
- Nemotron now keeps its model-native cache-aware state resident instead of
  reloading the checkpoint per job or being forced through an LLM runtime.
- Removing Triton-specific backend and client code reduces the Phase 6 surface
  while preserving reusable domain contracts and process safety.
- Provider runtimes can be replaced independently after parity and promotion
  evidence, without changing client/server job contracts.

### Costs and limitations

- There are intentionally two server ASR runtime families rather than one.
- The Cohere vLLM image needs a small, explicit compatibility shim until the
  upstream image closes its dependency gap.
- Nemotron carries a small pinned-source prompt-projection correction because
  the exercised unified wrapper did not consume its accepted prompt vectors.
- vLLM readiness proves the API/model/version surface; the checked launcher and
  immutable image inspection remain responsible for the container identity.
- Nemotron representative locale/duration behavior, frozen checked-head
  capacity, persistent supervision, and enterprise deployment remain unproved.

## Focused Cohere evidence (not promotion)

A dirty-head development image with immutable ID
`sha256:6adba2d79f26f57e3391cc60d4070e3ed655f1f6e02c315fb0ff0b918872279e`
and an explicit non-gate revision label exercised the actual
`CohereVllmBatchWorker -> authenticated loopback vLLM transcription service`
path on GB10. Readiness matched the locked vLLM version and Cohere model. The
public fixture produced zero normalized word errors and the exact transcript
hash of the Transformers reference. After the initial 2,067-ms request, c2,
c4, and c8 waves completed in 145, 370, and 303 ms respectively while retaining
one independent result identity and one identical reference hash per request.
Observed container memory was 3.09 GiB of the 32-GiB bound.

The first cancellation probe exposed a Yap client bug: closing an
`HTTPConnection` from another thread did not wake a Linux response read, so the
1,892-ms acknowledgement reflected inference completion rather than prompt
abort. Explicit socket shutdown corrected the boundary. The focused rerun
waited until vLLM reported an active engine request, acknowledged cancellation in
18 ms, observed the engine return to idle, recorded vLLM's abort log, published
no result, recovered in 104 ms with the reference hash, and removed the container
and loopback listener. Seventy-one affected local provider tests then passed with
one expected platform skip.

This evidence is sufficient to retain vLLM as the Cohere promotion candidate and
to reject the earlier cancellation result. It does not consume the frozen Phase
6 gate, qualify representative durations/locales or p95/p99 capacity, or promote
the service.

A later sustained dirty-head control repeated the same immutable 30-second input
200 times through the authenticated adapter. All 200 results retained the same
92 case-folded lexical tokens, while 11 results omitted four commas and therefore
formed a second rendered-text identity. Disabling the V1 engine subprocess
reproduced the same 189/11 split at the same request ordinals. The pinned
runtime's batch-invariant CUDA mode also retained two renderings and therefore
was rejected as a remedy. Its source confirms that `temperature=0` is greedy
FP32-logit `argmax`, so adding a request seed would not affect this path. Exact-
track load qualification consequently requires one lexical identity per audio
duration and records exact rendering variance separately. Punctuation remains a
scored representative-quality dimension; this does not waive its frozen
threshold.

A later four-repeat c8 resource control completed 1,600 Cohere requests without
failure. The first/warm repeats processed 303.7/321.3-322.4 audio-seconds per
wall second. Cgroup current and peak remained below 3.12/5.75 GiB, the last-half
cgroup and entrypoint allocation-extent medians were flat within 0.7 MiB, and
memory-event deltas were zero. This selected a predeclared GB10 vLLM ceiling; it
does not replace the frozen representative gate.

## Focused Nemotron evidence (not promotion)

A dirty-head development image with immutable ID
`sha256:555f9148431310266fa8e9d48fb93c5dd8879396164ac47202e561ebe38483bd`
and an explicit non-gate revision label exercised the real
`NemotronNemoBatchWorker -> authenticated loopback adapter -> one resident NeMo
engine` path on GB10. Eight simultaneous, independently identified fixed/auto
requests completed in 1,150 ms; the scheduler formed a model batch of eight.
Fixed `en-US` matched all 23 normalized reference words but omitted one comma;
automatic mode matched the exact public golden transcript after locale tags
were treated as metadata. A separate long request was cancelled in 13 ms,
published no result, and was followed by successful immediate recovery. The
container and loopback listener were then absent. A follow-up focused local
native/service/runtime/infra set passed 68 tests with two expected platform
skips.

This evidence corrects the earlier apparent server/reference difference: that
comparison used mismatched prompt handling and counted locale metadata as
spoken text. It does not consume the frozen Phase 6 gate, qualify other locales
or durations, establish production capacity, or select NeMo as the default.

A later focused exact-duration control used the new privacy-safe aggregate
qualification path with repeated licensed-fixture audio. Both candidates
completed a 30-second c2 wave plus c1 2-minute, 15-minute, two-hour, and exact
four-hour inputs. At four hours, vLLM completed in 49,896 ms with 4.272 GiB
current usage under 32 GiB; NeMo completed in 279,865 ms, including 275,702 ms
inference and 2,688 ms accumulated queue time, with 2.356 GiB current usage
under 96 GiB. Every focused run published one bounded result and removed its
container/listener. The repeated source cannot prove transcript completeness,
sentinel order, natural long-form quality, or comparable throughput. Those
claims remain in the frozen sentinel-rich gate.

The wall-time gap is consistent with the two deliberately different execution
shapes. Yap sends Cohere/vLLM one offline API request, and vLLM internally splits
long audio into bounded engine chunks that it can schedule concurrently. A
focused 120-second request produced four successful engine-request observations
while remaining one Yap/API request. The native NeMo candidate instead advances
the cache-aware streaming checkpoint in 1.12-second frames across bounded
finalized windows, so work along one recording timeline remains sequential even
when independent recordings can batch. The current Yap service publishes only
the finalized result; it does not expose partial transcripts. This control
therefore gives NeMo no user-visible streaming-latency credit and must not be
cited as client-facing streaming proof. It currently favors Cohere/vLLM for
long-form offline throughput while leaving short/finalized-utterance latency and
a future live transport as separate gates. vLLM queue/inference histograms are
reported per engine request; Yap wall latency remains per API request. Those
units are never merged or mislabeled.

At exact executable commit `2caf1969000154ffba24511a5c35b57f7f975036`, a
natural long-meeting comparison used both 17.49-minute AMI `ES2004a` conditions
after the desktop production normalizer and Silero VAD,
then rebuilt the exact chunk stream and 37-window plans through the server's
production input-preparation boundary. Cohere/vLLM completed close/far in
8.615/4.473 seconds; NeMo/Nemotron completed them in 18.065/16.858 seconds.
The lexical result did not follow the synthetic throughput ordering:
NeMo/Nemotron measured 26.046%/37.919% normalized WER versus
Cohere/vLLM at 46.250%/42.367%. Cohere/vLLM retained higher punctuation F1.
The reference is public, exposure-unknown, known-defective, flat-ordered across
overlap, and not independently reviewed, so this is descriptive evidence only.
It proves that throughput and task accuracy require separate gates and that no
provider may be labeled the universal quality route.

This result is not comparable to Cohere's much lower Open ASR Leaderboard AMI
number. The published leaderboard runner uses the immutable
`hf-audio/esb-datasets-test-only-sorted` AMI revision
`470b2948906c624f828a7349d92b92ec80e84fe0`: 12,643 duration-sorted,
individual-headset utterance rows from 0.04 through 26.2 seconds, not a complete
mixed close-talk or far-field meeting. The original Cohere runner at
`f73e3a2ce10b37dfab10af0e115707ca8791da8e` batches 64 rows, supplies fixed
English, and scores English-normalized row references; follow-up
`b6117f86f73edbca3b5dfc9960d0eb65d685258e` removes its pre-release model
revision override. Cohere's model-card table reports 8.15% AMI WER while the
Hub evaluation metadata reports 8.13%; the gated raw evaluation receipt is not
publicly readable. Those short-form values neither diagnose the Yap long-form
runtime nor waive its representative meeting gate. A separate full public
leaderboard replay would remain exposure-unknown comparator evidence, so it is
not added to the frozen promotion workload.

The AMI run completed both results and shut down its engine, container, and
listener, but its pinned upstream Torch/vLLM process emitted a weakref-time
`UnicodeDecodeError` plus one leaked-semaphore warning during interpreter exit.
No result or teardown invariant failed. Investigation reproduced the same
finalizer traceback by invoking the pinned vLLM CLI without a GPU, before a Yap
request or model load, and traced it to PyTorch upstream commit
[`c5f8ebc91a8727a9056734f73329c217328b8989`](https://github.com/pytorch/pytorch/commit/c5f8ebc91a8727a9056734f73329c217328b8989).
Exact executable commit `da9f7682d6337df0d1bfb26e069781d8a64ec726`
applies that exact BSD-3-Clause one-line behavior change at image build time and
fails closed if the digest-pinned PyTorch source differs.

A private source-exact ARM64 follow-up built image
`sha256:e8f3540f84e15eb1e4532fd63bab03e6b5f5e4744d393d3645172ea6e0da4905`,
verified every locked model artifact, served the public fixture with zero
normalized word errors, observed 2.968 GiB container usage, and completed both
EngineCore and FastAPI shutdown with launcher exit zero. Neither the finalizer
traceback nor a semaphore warning recurred, and the container and loopback
listener were absent afterward. The separate no-device CLI reproducer retained
its expected device-selection failure but also exited without the finalizer
trace. Transcript-free private log/summary receipts are bound by SHA-256
`60d31fffbb0e780cbe84a04be13cfffc7b7b8610361393f761879fe1ea275bd4`,
`e9c691a483deb8f5d51675b6f9ebc12300c6e9768cc02eaa49f494bdc0880c2f`,
and `d3888d7c25965066c0ede37cc34d2abeb742d27abb2137055ace703ff484206c`.
This closes the focused exit diagnostic without hiding it; the frozen provider
gate must still repeat log-clean lifecycle and resource assertions on its own
exact candidate.

A four-repeat c8 NeMo resource control likewise completed 1,600 requests with
one exact transcript identity at 268.9-274.2 audio-seconds per wall second.
CUDA allocation stayed near 1,296 MiB (1,312 MiB maximum) and reservation stayed
at 4,956 MiB. Cgroup current/peak stayed below 3.66/6.04 GiB. Anonymous RSS
oscillated as GB10 unified-memory pages became resident and were reclaimed, but
the entrypoint virtual allocation extent stabilized near 11.70 GiB with only
0-8 KiB last-half median growth across the focused controls. Python collection
plus `malloc_trim(0)` released
no material RSS, and all NeMo stream/state owners were empty on completion. The
HTTP boundary now uses bounded reusable workers instead of a fresh native thread
per request; warm median queue time fell from about 24 ms to 3-5 ms without
changing the independent eight-request model admission boundary.

Runtime-plan schema 5 now freezes separate c8/1,600 GB10 resource contracts
before promotion. Each requires a 60-second/200-sample tail, zero memory-event
increments, bounded tasks/threads, fixed current/peak ceilings, and no more than
64 MiB absolute tail growth in entrypoint virtual allocation extent. Descriptive
physical-RSS slope remains visible, but unified-memory residency oscillation is
not mislabeled as a live-object leak. These are dirty-head threshold-selection
results; the checked-head qualification remains required.

Both current-source profiles subsequently passed their executable eleven-check
qualification: exact c8/1,600 request/concurrency identity, minimum tail
coverage, current/peak and allocation-extent ceilings, allocation plateau,
task/thread ceilings, and zero high/max/OOM/OOM-kill events. Each container and
listener was absent afterward. This focused pass validates the contract but does
not consume the one-time checked-head gate.

A later private natural-speech intake screen used 19 original-language July
2026 European Parliament speeches after exact media-envelope removal and the
desktop's production Silero preprocessing path. Cohere/vLLM completed its nine
supported locales and 711 seconds of audio at c8 in 6,919 ms model-ready wall
time (102.76 audio-seconds/second), with 4,801/6,354/6,354-ms p50/p95/p99 API
latency and no failures. NeMo's first run exposed a Yap policy defect rather
than cross-request corruption: four locales deterministically failed even at
c1 because fixed routes rejected valid alternate locale metadata emitted by the
model. Fixed-route parsing now keeps the selected prompt authoritative, strips
every known emitted tag, and reserves tag evidence for automatic mode. Focused
tests passed, and the corrected c8 run completed all 18 NeMo-supported locales
and 1,380 seconds in 9,024 ms model-ready wall time (152.93 audio-seconds/second),
with 3,074/3,996/3,996-ms p50/p95/p99, a true maximum model batch of eight, and
zero failed or busy requests. Its reported CUDA allocation/reservation remained
bounded at 1,306/4,956 MiB maxima; both provider runs removed their container
and listener.

The Parliament text is revised upstream material rather than literal,
independently adjudicated gold. Its 15.86% Cohere and 22.06% NeMo normalized
word-error aggregates cover different locale sets and are diagnostic only;
they neither rank the providers nor promote a locale. Source audio, references,
per-case results, and diagnostics remain in the private external screen. Two
independent listens, adjudication, complete source attribution, and the frozen
representative gate remain required.

The shared promotion loader now has an executable case-level review contract:
both post-freeze and contractually excluded cases require two registry-authorized
listeners, an independent adjudicator, an authorized locale reviewer and rights
decision owner, and separately hash-pinned support artifacts. This prevents
either provider's model exposure record from doubling as human-reference
proof. No such real private
receipt or trust anchor exists yet, so neither provider's evidence status or ADR
completion score changes.

## Source-exact image smokes (not promotion)

At executable commit `fcccf21e785b116b92cd8e46150a36b9b5ee91db`, the full
locked Cohere model ran through Yap's real `VllmTranscriptionClient` in the
non-root image
`sha256:761d78efa390f84168827fb5f1075faa7720053efbc122fa74d76273d4a483bf`.
It produced one bounded hash-receipted public-fixture result and removed its
container and listener. The full locked Nemotron model separately ran through
`NemotronNemoBatchWorker` in image
`sha256:174003c3ae20347be46df255a3965ffaf5d0dd08ab21c77c2e07a9736611bfeb`
against an exact 30-second track, produced a bounded `en-US` result, and also
tore down cleanly. Owner-restricted receipts remain outside Git.

These focused smokes establish source-exact container, model, adapter, and
teardown integration. They do not satisfy the frozen reference comparison,
representative locale/duration, p50/p95/p99, resource, capacity, failure,
cancellation, recovery, rollback, or promotion requirements below.

## Executable lifecycle composition

The checked `resident-provider-lifecycle-gate.sh` now composes the frozen
resident-service mechanics without merging the provider runtimes. It verifies
already-present Cohere and Nemotron artifacts, builds exact-head ARM64 images,
creates one temporary internal bridge, and runs vLLM and NeMo sequentially. For
each service it verifies absent Docker port publication, blocked external
container reachability, the launcher-owned loopback proxy, exact-model
readiness; the plan-owned duration,
candidate-safety load, cancellation, capacity, and language cells; and a c8/1,600
cgroup profile. The finalizer rejects a partial concurrency ladder, an omitted
four-hour batch boundary, a changed duration suite/head, failed child evidence,
an unclean launcher exit, or any remaining provider container, proxy, launcher,
listener, or network.

The replaceable Cohere candidate must pass c1 duration transport, short-tail
c1/c2/c4 request/result isolation, c8/1,600 resource bounds,
cancellation/recovery, slot and PCM admission, and exact teardown. These
Phase 6 request-lifecycle cells record lexical variance but do not require
identical model output from repeated audio. The plan retains `vllm-long-waves`
and `vllm-mixed-eight` for provider-promotion comparisons, but the Phase 6
lifecycle wrapper does not require them. Phase 8 can reuse those cases when deciding
whether pinned Tiron is meeting-only, replaces Cohere batch more broadly, or is
rejected.

All source audio, transcripts, raw resource series, logs, and host snapshots
stay in the owner-private external cache. The aggregate contains only bounded
facts and child-evidence hashes. Focused portable tests and shell syntax checks
prove the orchestration contract.

The first checked-head GB10 attempt at
`e7d322fc07c6e1a39e69c2eec4d45e2c94d79e3a` passed Cohere readiness, its c1
duration ladder, and short-tail c1/c2/c4 isolation. It then failed closed before
NeMo when four completed c2 copies of the same accuracy-ineligible 15-minute
AMI-derived control did not retain transcript identity. Pairwise normalized edit
ratios were 6.9% through 21.6%; each c2 result differed from the c1 result by
22.4% through 23.4%. Teardown removed the provider container, proxy, listener,
launcher, and temporary network. The private receipt remains negative Cohere
promotion evidence. It points to long-form provider/model stability but does not
alone prove or disprove cross-request ownership mixing. The corrected exact-head
lifecycle run remains open and neither provider is promoted.

The next exact-head attempt at
`5b56929889925c933c63374a8d7ab282b6b82a3f` passed Cohere readiness, duration,
short-tail c1/c2/c4, cancellation/recovery, slot admission, and PCM admission.
The c8 resource workload completed 1,600/1,600 requests and passed every memory,
allocation, task, thread, and memory-event ceiling. It failed before NeMo because
its 116.317-second observation produced only 57.798 seconds in the last-half tail
against the frozen 60-second minimum, while one resource-only repeat reported
three lexical identities. Cleanup was exact.

This exposed conflated gate semantics rather than a reason to lower a ceiling.
The resource workload now declares `resource-lifecycle`: it still requires every
request/result, provider-idle read-back, the frozen resource thresholds, and
teardown, while reporting lexical variance without treating it as model
promotion. Its observation remains open for at least 125 seconds so the last-
half tail exceeds 60 seconds even when inference is faster. A new exact-head run
is required and neither provider is promoted.

At exact head `63318e51d569a1851f1a6daf8d1b707c353f2fa8`, the complete corrected
Cohere lifecycle passed and tore down before NeMo began. NeMo exact-model
readiness passed, but the finalized-duration cell reported only 2/9 completions
although the worker wrote all nine result files. Seven short/silent cases carried
canonical empty transcripts, which Yap's production result contract explicitly
allows; the generic runtime observer had incorrectly reclassified them as
execution failures. Cleanup was exact.

The observation boundary now preserves that production semantic. A published
canonical empty transcript counts as completed for
`duration-transport-and-lifecycle`, which carries no accuracy claim. Provider-
behavior, request-lifecycle, and resource-lifecycle speech fixtures still
require non-empty output.
The private failed receipt remains regression evidence, a new exact-head run is
required, and neither provider is promoted.

At exact head `4ffec120f212d20a26e314108940989c1b6e93a5`, Cohere passed its complete
corrected lifecycle and clean teardown. NeMo then passed readiness and both
duration ladders, including the exact four-hour transport boundary. Its
c1/c2/c4 short-tail cell completed and published 600/600 non-empty results;
c1 and c2 each had one lexical identity, while two of 200 c4 results differed
from the other 198 by one word. Every worker result remained bound to its job,
audio hash, model lock, and output path, and cleanup was exact. Repeated copies
of one audio input cannot establish cross-request mixing, so requiring one
lexical identity here was a misplaced model-determinism promotion test.
Phase 6 now labels its short/long standard cells `request-lifecycle`, requires
all identity-rich results and idle-provider read-back, and records rather than
promotes lexical stability. `provider-behavior` remains available for the
Phase 8 Tiron comparison. No request, capacity, resource, or teardown boundary
was weakened, and a new exact-head run is required.

Exact head `27108e1f591920b5a62496f988ae9ee7b335f2ce` then passed the complete
Cohere lifecycle and exact teardown. NeMo passed readiness, both duration
ladders, the 600-result short-tail cell, and the four-result 15-minute cell. The
15-minute results retained three lexical identities but every request/result
contract passed, as required by `request-lifecycle`. The next fixed/automatic
cell completed 16 fixed and 16 automatic results across c1/c8. Every automatic
result carried detected `en-US` source-time evidence, but automatic segmentation
changed wording, so none matched the fixed transcript lexically. The runner had
incorrectly included lexical equality inside its language-contract predicate;
cleanup was exact and no final aggregate published.

That cell is now named `nemo-finalized-fixed-auto-contract` and expects
`fixed-and-auto-language-contract`. It requires all fixed and automatic
identity/language/span contracts and records lexical/rendered parity with
`lexicalParityRequired: false`. This keeps the Phase 6 automatic-route contract
real without promoting Nemotron wording; Phase 8 compares that behavior with
Tiron. The changed runtime-plan identity requires a new hash-bound private
duration-suite envelope and exact-head rerun.

The cgroup profile measures the provider container; it does not attribute the
launcher-owned host proxy's CPU or RSS to the model. End-to-end request wall
latency does traverse the proxy. Whole-route/whole-host capacity and persistent
proxy supervision remain part of the Phase 10 system gate.

## Required evidence before promotion

Each frozen GB10 comparison must cover exact model/runtime identity, reference
transcript behavior, representative locale and duration ladders, c1/c2/c4/c8
latency and throughput, batching/state isolation, cancellation and immediate
recovery, bounded admission, current/peak/slope memory, clean shutdown, and
private evidence handling. Cohere and NeMo receive separate frozen gates and
cannot inherit one another's evidence or either focused result above.

## Sources

- [Cohere Transcribe model card](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)
- [Open ASR Leaderboard Cohere runner](https://github.com/huggingface/open_asr_leaderboard/tree/b6117f86f73edbca3b5dfc9960d0eb65d685258e/cohere_asr)
- [Immutable Open ASR AMI utterance set](https://huggingface.co/datasets/hf-audio/open-asr-leaderboard/tree/470b2948906c624f828a7349d92b92ec80e84fe0/ami)
- [vLLM supported transcription models](https://docs.vllm.ai/en/latest/models/supported_models/)
- [vLLM speech-to-text serving API](https://docs.vllm.ai/en/stable/serving/online_serving/speech_to_text/)
- [vLLM security guidance](https://docs.vllm.ai/en/latest/usage/security/)
- [NVIDIA vLLM 26.06 release notes](https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-26-06.html)
- [Nemotron 3.5 ASR Streaming model card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [NVIDIA NeMo ASR inference documentation](https://docs.nvidia.com/nemo/speech/nightly/asr/inference.html)
- [NVIDIA NeMo cache-aware streaming configuration](https://docs.nvidia.com/nemo/speech/nightly/asr/configs.html)
- [TorchAudio v2.11.0 source and BSD-2-Clause license](https://github.com/pytorch/audio/tree/v2.11.0)
