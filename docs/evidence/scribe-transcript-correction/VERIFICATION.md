# Scribe transcript-correction verification

**Status:** Exact private qualification gate and hosted review passed. PR #164
merged the Scribe slice; this evidence does not promote a production service or
close the other seven Voice OS roles.

## Exact candidate

- Executable and source-lock head:
  `e585842485a7cd38b2935cc8f79314b19b37f7fd`
- Gate outcome: `scribe-transcript-correction-qualified`
- Public-safe semantic evidence SHA-256:
  `5e187ed4f33e7a84c53824afb5a2af4b5ad0afcb3b7b7b36cb0b01692c74b3cb`
- Acceptance-plan SHA-256:
  `45d0f478f8792f0be38482b901643d6f5acde91711a223be6a60c276d680ff37`
- Frozen corpus SHA-256:
  `1c901eb8c66974a44997da28c63658942bd51c2f42b8b8494e163f370e5c8913`
- Full English source-evidence SHA-256:
  `3ad2ba5ccafffc9a916cb2493ad6786363690ca528d1f7f61d2ba46a99c8f3f4`
- Hosted-green head:
  `bc9a88bc3d3ee3fd767dbfee1497b6bc61733ce6`
- Merge head: `ec3af506da68bbb7a0ce855369dd09c8a791742d`
  through PR #164 after all 12 required hosted checks passed

The private corpus, model output, detailed measurements, credentials, database
content, process records, and filesystem locations remain outside Git.

## What the gate proved

- All 24 cases reached one terminal outcome across eight distinct authenticated
  owners and 16 unique real-audio inputs: eight English, eight Spanish, and
  eight safety/failure cases.
- The gate observed eight corrected references, eight source-preserved
  references, six exact unchanged outcomes, and two uncertainty outcomes.
- Every measured correction came from a server-authorized terminology mapping
  applied to the exact source span, optionally composed with separately
  validated bounded model edits. The model cannot invent an authorization.
- Raw ASR stayed immutable. Uncertainty, invalid output, timeout, cancellation,
  overload, unavailable service, or unsafe edits publish no corrected revision
  and return the source unchanged.
- Correction benefit passed its frozen WER requirement. Entity, number, date,
  unit, medication-like term, negation, insertion, deletion, source-coverage,
  and no-regression checks all passed.
- Three waves of eight owner-distinct requests used one unchanged warm rapid
  route generation and one unchanged admission broker. The model was not
  launched, swapped, or silently replaced during request handling.
- Queue-inclusive p95 latency passed the frozen Scribe bound.
- The owned PostgreSQL runtime, transcript-correction bindings, broker-facing
  workflow, provider observation, listener/process state, and Docker resources
  all satisfied their exact teardown/zero-residue checks.

## Public verification at the same head

- The complete portable server suite ran 1,198 tests with 30 declared platform
  skips and no failures.
- The focused Scribe/source-evidence set ran 86 tests with one declared platform
  skip and no failures.
- Server-wide Ruff passed.
- The local and private-server checkouts were exact, clean, and bound to the
  same candidate head before and after the gate.

## Deliberate limits

This gate proves a bounded manual finalized-transcript correction workflow. It
does not prove general acoustic error recovery, ASR n-best/confidence use,
automatic live correction, meeting summarization, simultaneous Qwen and Gemma
residency, sustained mixed-route capacity, p50/p95/p99 production SLOs,
observability, external serving, enterprise deployment, or the other seven
Voice OS workflows. Those remain separate Phase 10 slices and gates.
