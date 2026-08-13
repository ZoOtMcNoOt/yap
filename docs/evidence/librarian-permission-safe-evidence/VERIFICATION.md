# Librarian permission-safe evidence verification

**Status:** The no-LLM Librarian internal core qualified at exact head
`56b7f5d06f70f02cce79a422dd75b15c0a0bff10`; hosted head
`7505247e120a4008aa4245840b424961dbe62796` merged through PR #169 as
`d7a7e0033c976838ab1d28982da2c3f94eaf8e3e`. HTTP/native/renderer exposure,
production operation, and deployment remain pending.

At lock-only successor
`8fee7a5c4969d482e5248b72013935e3f6f83b3c`, the unchanged executable
inputs freshly returned
`librarian-permission-safe-evidence-qualified` with public-safe evidence SHA-256
`ca7ead2a0b8ac282e3c832350421ce4c534b36b00202fba2c46b453518f62ff4`.
The frozen permission, failure, database, audit, admission, and teardown
boundaries passed against the changed route/runtime. This does not relabel the
PR #169 merge receipt below.

## Exact qualified candidate

- Outcome: `librarian-permission-safe-evidence-qualified`
- Public-safe evidence SHA-256:
  `def8e6483bfcd0883d2e081362381fb0e0c7ec99379aeee89eaf050e0b0517e0`
- Acceptance SHA-256:
  `06a4e62af58b8903b564d0872b3a44017ff0bc11b0d7b35ecd262ba5b9845360`
- Synthetic corpus SHA-256:
  `928c4053d2237e1ca64e990402520e296b27ef1d8378747083fb622f6d031ffe`
- Eight cases and eight authenticated owners produced ten exact, unique
  invocations: four complete, three evidence-unavailable, one stale-generation
  failure, and two cancellations. Four packs were nonempty; no output budget
  was exhausted and no terminal result differed from the frozen expectation.
- The actual synchronized wave admitted all eight normal owners through the
  broker. The queue-inclusive p95 remained within the frozen 16-second bound.
- Hidden results were filtered before limiting, hidden links were suppressed,
  hidden-only and empty results were indistinguishable, successor revocation
  held, and stale-generation, deadline, and cancellation cases failed closed.
- The Server-IO route admitted one active owner, queued the second, completed
  cancellation and acknowledgement, contained every probe lease, and retained
  broker SHA-256
  `50b0d6bb6ad54e41b0da7a45a088386e29d3dea759e1bcbb8a8de8a46639077c`.
  Librarian acquired no model-route lease.
- Two owned-PostgreSQL restart/read-backs preserved the two exact generations
  and source admissions, exact tool/result audits, zero proposal writes, and
  all six teardown assertions.
- Owner-private publication read-back found one matching mode-0600 receipt and
  one link beneath a mode-0700 parent. Private paths, identifiers, envelope
  hashes, content, and individual latency measurements remain outside Git.

The frozen pre-Analyst public read-back ran 1,330 portable server tests: 1,290
passed and 40 were declared skips. Its governed fixed set ran 172 tests: 168
passed and four were declared skips. The focused Librarian command ran 50
tests: 45 passed and five were expected skips. Ruff and diff checks were clean.
The current successor-wide public counts are recorded in the
[profile-capacity evidence](../agent-admission-profile-capacity/VERIFICATION.md).

## Terminal predecessor

Exact predecessor `ecdcb8eedc007e4da15e83c679fbec219ccf7c7e` produced evidence
SHA-256 `83f618c6f60d54012ce58e44eafad01f6e1562575fa4ea31338668c9b614afb9`,
but post-run adversarial review proved that its nominal eight-owner wave sent
only seven owners through broker submission. That receipt is terminal and
inadmissible and is not reused. A separate initial invocation at that head
failed closed only at final create-once publication because the destination
parent was not owner-private; it minted no qualification receipt. Database
teardown had already been checked. No private destination or output is
published.

## Deliberate limits

This is a merged internal permission-safe read workflow, not a user-facing
product capability. It is not sustained capacity,
production p95/p99, availability, enterprise-networking, or deployment
evidence. The merged baseline is Scribe, Archivist, Student, Curator, Librarian,
and Analyst. Coordinator is a privately qualified internal candidate; Auditor
remains the final later bounded workflow.
