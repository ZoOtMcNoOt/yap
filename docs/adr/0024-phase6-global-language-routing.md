# ADR 0024: Phase 6 global language routing and timing evidence

**Date:** 2026-07-16
**Status:** Accepted decision; Phase 6 implementation and per-locale promotion
evidence remain incomplete
**Deciders:** Yap product owner and implementation owner
**Builds on:** [ADR 0003](0003-long-term-voice-architecture.md),
[ADR 0004](0004-background-diarization-okf-agents.md),
[ADR 0006](0006-silero-agents-state-machine.md),
[ADR 0007](0007-forced-alignment-engine.md),
[ADR 0008](0008-speechbrain-lid-gate.md), and
[ADR 0014](0014-server-tier-compute-topology.md)
**Amends:** ADR 0003's English-only future-language description, ADR 0007's
historical Canary/Wav2Vec2 engine choice, and ADR 0008's fixed confidence
threshold, raw-window strategy, and desktop-side delivery assumption
**Constrained by:** [ADR 0019](0019-local-streaming-model-selection.md),
[ADR 0020](0020-meeting-capture-diarization-authority.md), and
[ADR 0023](0023-bounded-live-priority.md)

## Context

The merged Phase 5 path requires one explicit language and sends every accepted
recording to the locked Cohere batch worker. That is a valid narrow vertical
slice, but it is not the intended global product:

- Cohere covers 14 languages and remains the accuracy-first batch choice where
  it is supported.
- NVIDIA Nemotron 3.5 ASR Streaming 0.6B exposes 19 transcription-ready and 13
  broad-coverage locales out of the box, supports streaming and batch use, and
  can emit language tags in `target_lang=auto` mode.
- Nemotron lists eight additional locales as adaptation-ready. Those require
  fine-tuning and are not current Yap capabilities.
- Short snippets do not contain enough speech for dependable language
  identification. Silence, meeting prompts, hold audio, mixed-language virtual
  recordings, and closely related languages also make a start-only classifier
  unsafe.
- The approved ASR image is `nvcr.io/nvidia/pytorch:26.06-py3`, with Python
  3.12, NVIDIA PyTorch 2.13 alpha, and Transformers 5.13.1. It intentionally has
  no matching TorchAudio package. Installing public TorchAudio 2.11 into that
  image would create an unsupported ABI/version mixture.
- Cohere does not return dependable word timestamps. Downstream meeting
  evidence needs timing, but invented or structurally invalid word intervals
  are worse than an explicit unavailable result.

The product therefore needs separate decisions for the user's default language,
long-recording language suggestions, explicit dynamic-language transcription,
provider selection, and timing evidence. A single opaque "auto" switch would
conflate all five.

## Decision

### 1. Make language and timing support data-driven capabilities

The server owns a versioned capability catalog. The desktop renders that catalog
and may retain a last-known verified snapshot for offline explanation, but it
does not hard-code a permanent model/language matrix.

Each provider revision records at least:

- provider and immutable model revision;
- BCP 47 locale;
- mode: local live, server live, fixed-language batch, or dynamic batch;
- quality tier: `transcriptionReady`, `broadCoverage`, or `preview`;
- whether language suggestion, per-segment language tags, and word alignment
  are available;
- license/provenance identity; and
- the benchmark/evidence revision that promoted the capability.

For fixed-language work, provider choice happens only after a user language
decision. Dynamic work requires an equally explicit mode choice. Models remain
replaceable behind the capability and worker contracts; changing a model must
not change durable job, result, or UI ownership.

For fixed-language batch work, prefer Cohere for its supported languages when
the user selects accuracy-first processing. Use Nemotron for enabled locales
outside Cohere's matrix and for an explicit fast/broad-coverage choice. An
automatic/mixed-language job stays on Nemotron for its complete lifetime; Yap
does not silently switch ASR providers between utterances.

### 2. Expose the honest global language catalog

Nemotron's 32 out-of-box locales are eligible for the Phase 6 catalog:

| Tier | Locales |
| --- | --- |
| Transcription-ready | `en-US`, `en-GB`, `es-US`, `es-ES`, `fr-FR`, `fr-CA`, `it-IT`, `pt-BR`, `pt-PT`, `nl-NL`, `de-DE`, `tr-TR`, `ru-RU`, `ar-AR`, `hi-IN`, `ja-JP`, `ko-KR`, `vi-VN`, `uk-UA` |
| Broad-coverage | `pl-PL`, `sv-SE`, `cs-CZ`, `nb-NO`, `da-DK`, `bg-BG`, `fi-FI`, `hr-HR`, `sk-SK`, `zh-CN`, `hu-HU`, `ro-RO`, `et-EE` |

Cohere adds accuracy-first overlap and one useful non-overlapping current
capability, Greek (`el-GR`). The resulting catalog can represent 33 locale
entries across 29 language families. Availability is not the same as an
enterprise accuracy certification: broad-coverage entries must retain their
visible tier until Yap's own fixtures justify promotion.

The following Nemotron adaptation-ready locales are intentionally excluded:
`el-GR`, `lt-LT`, `lv-LV`, `mt-MT`, `sl-SI`, `he-IL`, `th-TH`, and `nn-NO`.
Greek remains available only through Cohere. Yap does not build a fine-tuning
pipeline, advertise these eight as Nemotron support, or infer support from a
tokenizer/prompt dictionary.

### 3. Require a primary language during setup

Setup asks the user to confirm one primary language/locale from the current
capability list. The OS locale may preselect a suggestion, but it is not saved
as the user's decision until confirmed. The setting remains editable.

- Outside explicit dynamic mode, recordings with less than eight voiced seconds
  use the primary language and do not run the separate SpeechBrain LID probe.
- Live dictation uses the primary language only when the selected live runtime
  advertises that locale. Otherwise Yap explains the limitation and retains the
  supported fallback rather than pretending the language works.
- Every imported job has a visible language override. Recent and favorite
  languages may be placed near the top of the picker.
- A per-job override or detected suggestion never rewrites the saved primary
  language.
- Country/locale is never inferred from IP address or physical location.

### 4. Use SpeechBrain only for bounded batch preflight

The accepted LID candidate is
`speechbrain/lang-id-voxlingua107-ecapa` at immutable revision
`0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9`, under Apache-2.0.

It runs in a separate CPU-only Python 3.12 component pinned to SpeechBrain
1.1.0 and the matched PyTorch/TorchAudio 2.11 CPU pair. It does not modify the
NVIDIA 26.06 ASR image, consume an ASR GPU slot, or enter the desktop installer.
Production images and weights are staged and hash-verified before the networkless
runtime starts; an implicit production download is prohibited.

SpeechBrain is assistive preflight, not routing authority:

1. Select a continuous window of at most 15 seconds near the first usable speech
   and, for a long recording, another near the temporal middle.
2. Use advisory Silero VAD intervals to require at least eight voiced seconds in
   each probe. Energy alone cannot prove speech.
3. Cap work at two windows and preserve their source offsets as decision
   provenance. Never remove the corresponding source audio.
4. A recording shorter than the threshold uses the primary/manual language. A
   long recording needs mapped-language agreement across both usable windows.
5. Missing speech, disagreement, an unsupported label, or an ambiguous locale
   opens the manual picker. No "closest" language is selected automatically.
6. Store the model/revision, raw label, mapped locale, window offsets, top score,
   score margin, and user disposition. The model's softmax-like score is not
   called calibrated confidence.
7. A supported suggestion merely pre-fills the picker. The user confirms it
   before a fixed-language ASR job is committed.

This replaces ADR 0008's fixed `0.70` threshold and raw start-window shortcut.
Systematic related-language confusions cannot be made safe by one scalar
threshold.

### 5. Use Nemotron auto mode for explicit dynamic detection

Dynamic detection is a separate user-selected mode. The server Nemotron worker
uses `target_lang=auto` and preserves the emitted BCP 47 language tag on each
finalized speech segment.

- VAD/endpointing defines bounded utterance candidates. A tag may change only
  when the prior segment is final; partial text never changes provider or
  language underneath the user.
- Nemotron auto mode may evaluate a short finalized utterance because its tag is
  produced by the same transcription pass. The eight-voiced-second SpeechBrain
  threshold is not applied to this path, and Yap does not describe the emitted
  tag as calibrated confidence.
- Missing, disabled, adaptation-ready, or structurally invalid tags produce an
  `Unknown` language segment and visible review state.
- The result retains per-segment language provenance and derives display text
  without discarding those tags.
- The primary language remains a visible manual re-run/fallback choice. Yap does
  not silently relabel an unknown dynamic segment as the primary language, and
  dynamic mode does not alter the saved setting.
- Intra-utterance code-switching is not a Phase 6 support claim. It needs a
  dedicated multilingual fixture gate; concatenating two languages and seeing
  some tags is not sufficient proof.

The current local `sherpa-onnx` export exposes encoder, decoder, joiner, and token
paths but no equivalent language-prompt/tag contract. Dynamic mode is therefore
server-only until a separately pinned local export passes the same behavior and
resource gates. ADR 0019's one-local-model/no-desktop-router rule remains intact.

### 6. Align raw transcripts and fail closed by capability

ADR 0007's raw-text alignment principle remains accepted. Its historical
Canary/Wav2Vec2 engine choice is not.

The first implementation candidate derives Cohere word boundaries from its
decoder cross-attention without adding another alignment model:

- run ordinary BF16 generation and a teacher pass;
- capture decoder/encoder hidden states;
- reconstruct query/key attention in FP32;
- apply finite checks, normalization, median filtering, and monotonic DTW; and
- reconcile every emitted word with the raw transcript before publication.

This path is enabled per provider/language only after fixtures meet boundary
error, monotonicity, coverage, transcript-reconciliation, latency, and memory
gates. English is the first validated candidate. Unsupported or failed
provider/language pairs publish `alignedWords: []` plus an explicit unavailable
reason; they never fabricate even spacing, confidence, or speaker attribution.

Qwen3 ForcedAligner remains a benchmark challenger for its supported languages.
MMS 300M is rejected as the enterprise baseline because its current model
license is non-commercial. Nemotron decoder durations are not treated as forced
alignment for a Cohere transcript.

### 7. Keep the pipeline durable and source-authoritative

Normalization, VAD, LID preflight, user confirmation, ASR, alignment, and result
publication are distinct durable stages. Each stage records an input fingerprint,
provider revision, attempt, terminal outcome, and retryability. Retrying one stage
does not rewrite capture history or re-authorize a language choice.

Client VAD remains advisory under ADR 0020. The server may recompute boundaries
from retained source audio. False-negative VAD decisions never remove bytes from
the official ASR/reprocessing input. New server work remains subject to ADR
0023's bounded live preference and existing owner fairness/backpressure rules.

## Measured decision evidence

All audio fixtures used for this decision were public. Raw benchmark output and
host-specific paths remain outside Git; the numbers below are aggregate design
evidence, not language certification.

| Candidate | Result on the same public fixture shape | Resource observation |
| --- | --- | --- |
| Nemotron automatic LID | 78/84 correct across 28 out-of-box language families; 23/28 perfect | Mean 134 ms/probe; 1.293 GiB peak GPU allocation; emitted no calibrated confidence |
| SpeechBrain VoxLingua107 | 77/84 correct across the same 28 families, plus 3/3 Greek | CPU-only mean 179 ms and p95 234 ms per probe; about 760 MiB peak RSS, 1.1 GiB environment, and 82 MiB model |
| SpeechBrain probe length | 2 s: 39.3%; 3 s: 71.4%; 5 s: 86.9%; 8 s: 94.0% on this small sample | Supports an eight-voiced-second minimum; does not prove a universal optimum |
| Cohere attention alignment | Held-out English start MAE 92.2 ms, end MAE 80.3 ms, minimum coverage 91.8%; selected-head combined mean 77.8 ms | Warm alignment pass 35–47 ms; English-only evidence |

SpeechBrain confidently confused examples of Russian/Belarusian,
Czech/Slovak, Bokmål/Nynorsk, and Croatian/Bosnian. It also emitted arbitrary
language labels for silence and noise. Nemotron sometimes emitted no tag and
made one related-language error in the same small set. These observations are
why speech presence, multiple windows, explicit tiers, and user confirmation
are architectural requirements.

The existing English ASR comparison also remains relevant: Cohere used about
3.85 GiB and produced 1.302% mean WER on eight fixtures; Nemotron used about
1.19 GiB and produced 5.446% mean WER while loading much faster. That evidence
supports provider choice rather than replacing either model with the other.

## Options considered

### Primary language plus guarded LID and explicit dynamic mode — accepted

This gives short audio a deterministic path, long single-language recordings an
assistive suggestion, and multilingual traffic a model designed to emit tags.
It costs one isolated CPU LID component and a second server ASR pool, both behind
existing boundaries.

### SpeechBrain for continuous dynamic switching — rejected

VoxLingua107 is an utterance classifier, not a calibrated streaming or
code-switching router. Re-running it on overlapping windows would add flicker
and would still confidently label silence/noise and related languages.

### Nemotron auto mode for every request — rejected

Short utterances and Greek need different handling, auto mode has no calibrated
confidence, and Cohere retains a material accuracy advantage on its supported
batch languages. The user's chosen primary language is a stronger prior for
short snippets.

### Two-model voting on every probe — deferred

Agreement can raise precision, but it makes a lightweight batch hint depend on a
GPU model and complicates Cohere-only languages. Add it only if a larger
benchmark proves a material product benefit.

### Sliding-window or token-level language diarization — deferred

True within-utterance code switching is a language-diarization problem, not an
utterance-labeling option. The examined work is research- or language-pair-
specific and does not prove a private, production-ready classifier over Yap's
global catalog. A future candidate must preserve source-time boundaries and pass
multilingual switch-point, overlap, latency, and license gates before Yap can
claim word- or phrase-level switching.

### Manual language only — retained as fallback, rejected as the only UX

Manual selection is always available and is the failure-safe behavior. It does
not by itself serve global users handling long or unknown recordings.

### Whisper or MMS LID/alignment stack — rejected for Phase 6

Whisper adds another complete ASR runtime without measured benefit here. The
examined MMS alignment/LID weights are too large for this role and their current
non-commercial license is incompatible with the enterprise baseline.

## Consequences

### Positive

- Yap can expose broad global capability without claiming unmeasured quality.
- Short snippets remain stable and fast.
- Dynamic language changes stay inside one model and occur only at reviewable
  segment boundaries.
- The NVIDIA ASR image remains internally consistent.
- Models, aligners, and language catalogs can evolve without changing ownership
  or durable job identity.
- Missing timing remains truthful and recoverable.

### Negative

- Phase 6 adds an isolated CPU runtime and another pinned model lock.
- Broad-coverage languages require much more representative quality gates.
- The UI must explain fixed, suggested, dynamic, unsupported, and timing-
  unavailable states without implying certainty.
- Dynamic local fallback and within-utterance code-switching remain absent.

### Neutral

- Phase 7 authentication, Phase 8 diarization/identity, Phase 9 knowledge, and
  Phase 10 enterprise networking/repo split are unchanged.
- This ADR changes no IT-controlled DNS, certificate, firewall, ZPA, identity,
  or deployment requirement.

## Action items

1. [ ] Implement the versioned provider/language/timing capability catalog.
2. [ ] Add setup/Settings primary-language confirmation and per-job override.
3. [ ] Produce advisory Silero VAD segments without deleting source audio.
4. [ ] Package the pinned CPU SpeechBrain component and immutable model lock.
5. [ ] Add fixed-language Cohere/Nemotron routes and explicit Nemotron auto mode.
6. [ ] Extend result contracts with source-bounded per-segment language evidence.
7. [ ] Implement fail-closed Cohere attention alignment behind per-language gates.
8. [ ] Validate every advertised locale/tier on representative public and
       approved private-domain fixtures before changing a quality claim.
9. [ ] Run the complete Phase 6 local/native/server/GB10 matrix exactly once on
       the ready head, then require hosted exact-head review before merge.

## References

- [Nemotron 3.5 ASR Streaming 0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [SpeechBrain VoxLingua107 ECAPA](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa)
- [Cohere Transcribe 03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)
- [Qwen3 ForcedAligner 0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)
- [Local audio preprocessing stack](../specs/local-audio-preprocessing-stack.md)
- [Testing strategy](../specs/testing-strategy.md)
