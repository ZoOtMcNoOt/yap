# Coordinator proposal-bundle verification

**Status:** Merged internal core. Exact executable candidate
`fed729b3dcbb7bba4c89daaa9d857bf57976ab8e` privately qualified the
internal Coordinator core. Hosted head
`53ee0152a7244c7706f26b89c86d1fe2843dd5df` passed all 12 required checks,
and PR #171 merged the core as
`67d836daef9f1c64b840185f82a1fd777aad0523`. HTTP/native/renderer/UI
exposure, production operation, and deployment remain pending.

## Exact qualified candidate

- Outcome: `coordinator-proposal-bundle-selection-qualified`.
- Public-safe evidence SHA-256:
  `1bce03b6844d633b09504d9c27ddeac8c96521c569d1eedeecf4f0de2cef5334`.
- Acceptance-plan SHA-256:
  `34f7152da6eeeb7c21018bcfb4581cfea89d794414ffe15e7a690e43d64d5b04`.
- Frozen synthetic corpus-v2 SHA-256:
  `e427bb41a7cd351e0b092333a6ce800a4abd931fa7593e3b9d6f127f9b95895f`.
- Eight cases across eight authenticated owners ran in three synchronized
  repeat waves. All 24 normal service calls exactly matched, all three waves
  were exact, and all 29 unique invocations reached the frozen terminal result
  with zero mismatch.
- The exact results contained 15 server-derived proposal bundles, 18 selected
  proposal items, and 18 server-owned citations. Every returned bundle was
  noncanonical and review-required. The model selected only ordered indexes;
  it could not author proposal text, proposal identity, citations, or a free-
  form plan.
- Exact terminal arithmetic was 15 complete, 10 evidence-unavailable, one
  failed invalid-output control, and three cancelled controls. Hidden-only and
  absent evidence were indistinguishable, and unavailable/cancelled/failed
  results contained no bundle.
- One production Coordinator ticket was created for every invocation. Exactly
  28 tickets were submitted, 26 completed, one client cancellation and one
  deadline expiry were acknowledged to their exact terminal outcomes, and the
  sole pre-cancelled ticket was never submitted. Every submitted ticket was
  terminal and no nested agent-service lease was used.
- The gate independently compiled current knowledge, published its synthetic
  input proposals through the production Curator runtime, reauthorized exact
  Curator lineage and current citations, and read back exact Coordinator,
  Curator, and knowledge-tool audit cardinality. Two owned PostgreSQL restart/
  read-back boundaries and all six database teardown assertions passed.

## Warm complex-route boundary

The qualified complex profile has SHA-256
`4c5e5da836355e57ec43c6f1270eb9eb5839c6fd91e6dbf73389e37ce4cdf6a8`.
It retains the full Gemma limits: eight maximum sequences, 8,192 maximum
batched tokens, 8,192 maximum model length, `0.70` GPU-memory utilization,
7,680 maximum input tokens, and a 512-token output cap. Batch invariance was
enabled, prefix caching was disabled, request seed `0` was fixed, and the
provider and admission broker identities remained unchanged through the
workload. The exact broker binary SHA-256 was
`0e71b9253eb3ebf29e83f6b222a67ba0f38caea2d36666fb6b408769d87e9d03`.

The live capacity probe held eight distinct complex-route owners, observed a
ninth owner queued, and contained every probe ticket without changing provider
or broker identity. The three exact synchronized repeats prove repeatability
inside one unchanged already-warm provider process. They do not prove
simultaneous inference, cross-start or global determinism, sustained throughput
or fairness, or a production latency SLO.

## Public verification

At exact clean head `fed729b3...`:

- the portable server suite ran 1,449 tests: 1,404 passed and 45 declared
  platform/real-PostgreSQL skips;
- the governed fixed set ran 173 tests: 169 passed and four declared skips;
- the focused Coordinator qualification/domain/service/audit matrix and the
  Rust admission-contract reread were green;
- whole-tree Ruff check, changed-file format check, `git diff --check`, and
  clean admission of all 336 protected candidate inputs passed.

The owner-private receipt was mode `0600`; its embedded public evidence hash
recomputed exactly and matched the gate's public stdout. Private tenant/run
identities, prompts, model outputs, proposal content, citations, database rows,
paths, DSN, and individual latency measurements remain outside Git.

## Terminal predecessor

Exact `11f325bb...` completed the workload but failed closed before evidence
publication because the new admission verifier treated the deliberate deadline
expiry as an ordinary client cancellation. It emitted no Coordinator
qualification receipt and established no admissible Coordinator success
evidence. Its owner-private harness nevertheless completed exact provider,
broker, container, network, and process cleanup. The attempt is terminal and
is not reused. Exact successor `fed729b3...` changes only the gate verifier and
its regression to bind the broker's real deadline cancellation reason and
terminal acknowledgement.

## Deliberate limits

Coordinator is a qualified merged internal core, not a product-exposed
workflow. The merged roster contains Scribe, Archivist, Student, Curator,
Librarian, Analyst, Coordinator, and Auditor.
Coordinator accepts an explicit authenticated request, considers only the
caller's current open Curator proposals, and returns a source-cited selection
bundle. It writes no plan, task, proposal, source, or active knowledge and
performs no autonomous action.

No evidence here proves simultaneous Qwen/Gemma residency, sustained
multi-user capacity/fairness, production p50/p95/p99 or availability, external
endpoints, enterprise networking, deployment, or approval to act on a bundle.
One Spark can run the unchanged full Qwen and Gemma profiles only sequentially;
a second owned GPU node and IT-controlled private route remain required for
simultaneous warm two-route promotion.
