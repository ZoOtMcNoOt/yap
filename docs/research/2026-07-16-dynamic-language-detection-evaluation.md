# Dynamic language detection evaluation

**Date:** 2026-07-16

**Status:** Studied; no donor source or model artifact was added

**Decision owner:** [ADR 0024](../adr/0024-phase6-global-language-routing.md)

## Question

Can Yap dynamically identify language without forcing every user to choose a
language before every recording, including mixed-language recordings?

The answer depends on the temporal claim:

1. **Clip-level LID** returns one language for an input clip.
2. **Finalized-segment LID** returns one language for each VAD/endpointed
   utterance and may change only between finalized segments.
3. **Language diarization** locates language switches inside one utterance at
   frame, token, word, or span resolution.

These are not interchangeable capabilities.

## Current decision

Retain ADR 0024's two explicit user paths:

- fixed work uses the confirmed primary/manual language, with SpeechBrain only
  as an optional long-recording suggestion; and
- dynamic work is a separately selected server mode. Its current candidate is
  Nemotron 3.5 `target_lang=auto` on bounded finalized VAD segments.

Nemotron is the only current candidate whose documented output directly fits
that second contract: its 600M streaming model appends one detected locale tag
to each utterance, and its 32 transcription-ready or broad-coverage locales
work out of the box. The eight adaptation-ready locales remain excluded. This
does **not** establish within-utterance code-switching.

No dynamic capability enters Yap's executable catalog until its immutable
runtime/model lock, public multilingual fixtures, tag parser, unknown-tag
behavior, resource ceiling, cancellation/restart behavior, and exact evidence
revision pass the Phase 6 gate.

## Candidate comparison

| Candidate | What it documents | Fit for Yap | Decision |
| --- | --- | --- | --- |
| NVIDIA Nemotron 3.5 ASR 0.6B | Optional automatic detection; one terminal locale tag per utterance; 19 transcription-ready, 13 broad-coverage, and 8 adaptation-ready locales | Direct match for bounded finalized-segment detection; same transcription pass supplies text and tag | Phase 6 dynamic candidate; benchmark and lock before advertising |
| Qwen3-ASR 0.6B HF | One parsed language plus transcription per input; 30 languages and 22 Chinese dialects; offline and streaming; Apache-2.0 | Strong lightweight clip/segment challenger and useful additional-language coverage, but the documented contract is one language per input rather than span labels | Benchmark challenger; do not call it language diarization |
| Microsoft VibeVoice-ASR | 9B BF16; 51 languages; up to 60-minute input; speaker, timestamp, transcript output; claims native code-switch handling; MIT | Promising long-form batch challenger, but much heavier and its documented structured output does not establish per-span language labels | Benchmark for mixed long-form transcription; not the LID component |
| SAGE-LD | Research architecture produces fine-grained language diarization from 25 ms features and reports gains on language-diarization benchmarks | It addresses the correct within-utterance problem | Research only: official repository has no release, published checkpoint, or visible license |
| SpeechBrain VoxLingua107 | One clip-level language estimate | Useful bounded suggestion for longer fixed-language imports | Never continuous routing authority |

## Required dynamic fixtures

A promotion benchmark must contain at least:

- every advertised out-of-box locale with multiple speakers and acoustic
  conditions;
- related-language confusions and unsupported/adaptation-ready speech;
- silence, music, noise, extremely short utterances, and missing tags;
- language changes at VAD boundaries, with exact source-time provenance;
- same-speaker intra-utterance switches as an explicit negative claim for the
  Phase 6 segment-level implementation; and
- restart, cancellation, retry, memory, latency, and clean-teardown evidence on
  the locked GB10 runtime.

Only a later accepted decision plus a released, licensed model and switch-point
benchmark can promote language diarization. Concatenating monolingual clips or
observing two utterance tags is insufficient evidence.

## Primary sources

- [NVIDIA Nemotron 3.5 ASR Streaming 0.6B model card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [Qwen3-ASR 0.6B Transformers model card](https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf)
- [Microsoft VibeVoice-ASR model card](https://huggingface.co/microsoft/VibeVoice-ASR)
- [SAGE-LD paper](https://arxiv.org/abs/2510.00582)
- [SAGE-LD official code appendix](https://github.com/sanghyang00/sage-ld)
- [SpeechBrain VoxLingua107 ECAPA](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa)
