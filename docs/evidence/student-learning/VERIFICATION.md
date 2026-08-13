# Student learning-question verification

**Status:** Exact head `428d6e48690621cc2242944c049e06ccfd2e45e2`
is complete-portable-test green and privately qualified. Hosted-green head
`b03c6e79f19bad451437c3f0c495daa67bb7171f` passed all 12 required checks and
PR #166 merged the internal core as
`2254605ed19a592d2db1747d576762ccf11a5cc0`. HTTP/native/UI exposure, Curator
integration, and product promotion remain pending. The later profile-capacity
successor was freshly qualified with Student at exact head
`7cd24deb1131ecf89258ddb821c6bffae8e0cd25`; PR #168 remains draft, so that
successor is not yet hosted-green or merged.

## Current candidate contract

- Work class and route: `BACKGROUND_LLM` / rapid automation.
- Student reads one authenticated owner-scoped, permission-safe admitted
  conversation generation. It cannot accept caller-authored evidence, read
  another owner, mutate the source, write a proposal, or activate knowledge.
- The request carries bounded topic text rather than a caller-authored target
  question. Topic and evidence are explicitly untrusted model inputs.
- The model sees only ordered `{sourceEvidenceIndex,text}` entries and must
  return exactly one `{sourceSubject,sourceEvidenceIndex,supportQuote}` record.
  The server rejects a Boolean, negative, or out-of-range index, selects the
  frozen evidence object itself, binds the complete citation identity, resolves
  the quote to one unique substring, and derives its span. The model never
  receives authority to create, copy, narrow, or rewrite citation identity.
- The prompt explicitly forbids promoting topic text into `sourceSubject`
  unless identical bytes occur in the selected quote, requires an exact
  contiguous subject-inside-quote-inside-evidence chain, and forbids combining
  or paraphrasing source phrases. The unchanged server validator remains the
  executable authority.
- The server alone renders `What should you remember about {sourceSubject}?`.
  It requires the exact subject at lexical boundaries in every support and
  rebinds every support to the frozen evidence object. The model cannot change
  the selected subject's bytes, order, case, or punctuation and cannot write
  question wording; invalid output publishes no questions. Topic text is
  untrusted context, not executable authority. This is not a claim that every
  possible numeric or linguistic fragment has independent semantic meaning.
- The workload still requires the unchanged full Qwen rapid profile: GPU-memory
  utilization `0.40`, four maximum sequences, 8,192 maximum batched tokens, and
  a 512-token Student output cap. Neither Student nor its gate launches, stops,
  swaps, substitutes, or reduces a model.

## Current public verification

- The focused Student set ran 34 total tests: 32 passed and two were declared
  local database skips. It includes multi-chunk cases whose required evidence
  appears at index zero and at a nonzero index, so always-first and always-last
  selection both fail qualification.
- The focused Student set remains green at 34 total tests: 32 passed and two
  were declared local database skips. Changed-file Ruff and `git diff --check`
  passed.
- The current successor passed the complete portable server suite at 1,241
  total tests: 1,207 passed and 34 were declared skips. Because the prompt and
  its contract test are protected inputs changed from exact `0970d74c...`, this
  rerun is the current public verification; the predecessor result is historical.
- Exact clean head `428d6e48690621cc2242944c049e06ccfd2e45e2`
  returned `student-learning-questions-qualified` with public-safe evidence
  SHA-256
  `f597cca728d261caad66d6629332c76ffd900bc78f6be20aa7bb0c849275ebe8`.
  All eight distinct owners completed with one grounded question each, zero
  terminal failures, zero forbidden-term hits, and no output-budget exhaustion.
  The unchanged full warm profile, provider generation, broker process,
  synchronized eight-owner queue wave, PostgreSQL restart, exact cross-owner
  denial and durable audits, and all six teardown checks held.
- The persisted private receipt was independently read back as exactly one
  owner-private `0600` regular file with one link, the exact checked head and
  public evidence hash, and clean repository state. No private path, raw model
  output, case content, latency, or private measurement is published here.
- This qualifies only the internal bounded Student core. It does not prove
  HTTP/native/UI integration, sustained multi-user capacity, simultaneous
  Qwen/Gemma residency, production SLOs, or deployment readiness.
- Exact hosted head `b03c6e79f19bad451437c3f0c495daa67bb7171f`
  passed all 12 required checks and PR #166 merged the internal core as
  `2254605ed19a592d2db1747d576762ccf11a5cc0`. The hosted closure does not add a
  product surface or extend the exact `428d6e48...` private receipt to later
  broker/model-client changes.

## Profile-capacity successor qualification

Exact protected successor `7cd24deb1131ecf89258ddb821c6bffae8e0cd25`
returned `student-learning-questions-qualified` with public-safe evidence
SHA-256
`d3561e1a03653fa7c8adb887cb161eb13a59f1573b15cd7f861731a71449c305`.
All eight distinct owners completed with one source-grounded question each and
zero terminal failures. The gate held the unchanged rapid route at four active
distinct owners, observed a fifth owner queued, required unchanged warm-provider
and broker identities, exercised PostgreSQL restart/read-back and exact owner
boundaries, and completed exact teardown. Student still launches, swaps,
substitutes, or reduces no model.

This new exact-head receipt qualifies the protected admission successor without
relabeling PR #166's historical merge receipt. It is internal candidate evidence,
not PR #168 hosted review/merge or product exposure. See the
[profile-capacity evidence](../agent-admission-profile-capacity/VERIFICATION.md).

## Terminal private evidence

Exact head `0970d74c7961a63bd1b2366bc0ecef6b5fc55714` returned
`deterministic-no-student` with public-safe semantic evidence SHA-256
`316631d593e51477d855ed146e2a5bea49eec236b0753655bdd4814a20a0cb99`.
Seven of eight cases completed and one failed closed. The unchanged full warm
profile, provider generation, broker, synchronized eight-owner queue wave,
PostgreSQL restart, cross-owner and audit boundaries, and exact teardown all
held. A bounded follow-up diagnostic found valid structured selection of the
server-owned evidence but a source subject absent from the selected quote and
evidence; no raw response or measurement is published. The receipt is terminal
and inadmissible for the prompt-repaired successor.

Exact head `476f7a9c38287f8c6ba08cd9be4a70addabe3069` returned
`deterministic-no-student` with public-safe semantic evidence SHA-256
`9c2f68ffe411d1333c6799158fa28db30ffa0ced6359eb9f291528ded4c0d0d4`.
Six of eight cases completed and two failed closed. The unchanged full warm
profile, provider generation, broker, synchronized eight-owner queue wave,
PostgreSQL restart, cross-owner and audit boundaries, and exact teardown all
held. The receipt is terminal and inadmissible: it cannot authorize or be
relabeled for the evidence-index successor, which changes protected inputs and
requires its own exact-head qualification. No failed output or measurement is
published or reused.

Exact head `452c8b76a9a60681a962048caed12749e8bb80d0` originally returned
`student-learning-questions-qualified` with public-safe semantic evidence
SHA-256
`3e1ddc61bf0c8d009a25b06ef261f0b6f7dcd8d7c1f58eeb666ba31e98420c41`.
Its acceptance-plan SHA-256 was
`99471659c91618028a3c2e5d58739b8f2635aee1a7d3800c445ac7c855aa6e67`,
and its frozen-corpus SHA-256 was
`b9d300137b2720e91dcafc1fae8dcda15d4fa4febb79623b4ddd453c6d857962`.
The run did prove the unchanged full profile, an unchanged warm-provider
generation and broker, one synchronized eight-owner workflow wave, real
PostgreSQL restart/cross-owner/audit behavior, and exact owned-database teardown.

Post-gate adversarial review then demonstrated that a caller-controlled focus
could contain a target question and that the decoder accepted an unsupported
question premise when it copied an unrelated but exact visible citation. The
qualification corpus also embedded each expected question in that focus text,
so the run proved citation copying and lifecycle behavior but did not prove
source-grounded question generation. That receipt is therefore terminal and
inadmissible; it cannot authorize merge or be relabeled after the repair.

Exact predecessor `ffe9088573a1a8453a3cb529f1fc62c8ef9d7dda` remains terminal
`deterministic-no-student` evidence with public-safe SHA-256
`bc65dd55dc3c751caa340312fc6435beba5ba0c0d7a2fa43e323297cadf32c3d`.
Seven of eight cases completed; `instruction-is-data` failed closed because the
model altered one citation span. No failed or invalidated output, measurement,
or candidate result is reused. The repair changes no model, resource profile,
output cap, timeout, queue bound, or acceptance threshold.

## Deliberate limits

Student is a merged internal core. There is no Student HTTP endpoint, native
adapter, renderer/UI workflow, user review surface, or production deployment.
The current development branch's profile-capacity admission successor changed
protected broker/model-client inputs and therefore received its own exact-head
route and affected-workflow qualifications; the historical PR #166 receipt is
not relabeled. Current evidence does not prove sustained multi-owner throughput,
route p95/p99 SLOs, simultaneous full Qwen/Gemma residency, or a two-node warm
topology. Curator is a qualified internal candidate pending hosted review/merge;
the four later workflows (Auditor, Librarian, Analyst, and Coordinator), and
aggregate Phase 10 completion remain open. A fresh post-aggregate observation
on 2026-08-12 found the unchanged full Qwen rapid route warm on the current
single Spark. Full-strength two-route promotion requires a second owned GPU
node and private routing rather than throttling or model swapping.
