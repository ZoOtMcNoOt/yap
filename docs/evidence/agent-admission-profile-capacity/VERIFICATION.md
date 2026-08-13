# Agent admission profile-capacity verification

**Status:** Exact protected route qualification and the aggregate governed-
knowledge gate passed for the profile-derived admission successor. The public
lock is committed at `7f896b341c31fcabb3f894a8d693764c8bc30600`. PR #168 is
draft; hosted review, merge, simultaneous two-route residency, sustained
capacity/SLO evidence, product promotion, and deployment remain open.

## Qualified route evidence

- Exact route-qualification head:
  `dab19fe7563a9d596cbe7d861460a5c6fed7025c`
- Outcome: `required-workload-routes-qualified`
- Public-safe evidence SHA-256:
  `962289148143174073b99fcc62ddd240ea0dae9f36fef09a9449a8022a4a3d13`
- Public-lock commit: `7f896b341c31fcabb3f894a8d693764c8bc30600`
- Rapid-profile SHA-256:
  `14712e6951802daaae323a3a7d69e78a8b3d5ac32ad52cbd0f546df327649da8`

The gate admitted the exact Qwen rapid and Gemma complex candidates
sequentially on their unchanged full profiles and proved exact teardown after
each route. It did not reduce either service profile, start or swap a model per
request, substitute one route for another, or claim that both models were
resident simultaneously.

The successor derives active admission limits from those immutable profiles:
four distinct active owners for rapid automation and eight for complex
orchestration, while Server IO remains one and the global one-active-request-
per-owner rule remains intact. The rapid and complex workflow gates separately
held their selected route at its full limit, observed a fifth or ninth distinct
owner queued, contained every probe lease, and required unchanged provider and
broker identities.

## Affected workflow and aggregate read-back

- Exact Scribe/Student/Curator workflow head:
  `7cd24deb1131ecf89258ddb821c6bffae8e0cd25`
- Scribe outcome: `scribe-transcript-correction-qualified`; public-safe
  evidence SHA-256
  `9c3c44c58befe1f2c2985956bad6fa5703b4b7668bd5a546a0bdf11bcb92263e`.
- Student outcome: `student-learning-questions-qualified`; public-safe
  evidence SHA-256
  `d3561e1a03653fa7c8adb887cb161eb13a59f1573b15cd7f861731a71449c305`.
- Curator outcome: `curator-knowledge-proposals-qualified`; public-safe
  evidence SHA-256
  `b60df1e2c044b0f4771038830fb086413239555345893f6e863697d7e4b3cf03`.
- Exact aggregate/public-lock head:
  `7f896b341c31fcabb3f894a8d693764c8bc30600`.
- Aggregate outcome: `governed-knowledge-gate-passed`; public-safe evidence
  SHA-256
  `fd197b9883d8e3b96e7abd9c8e994b416ac20ed2dafc0bca20c114c54258a3bb`.

The aggregate admitted the matching route lock, ran the fixed public suite and
lint, exercised the required real-PostgreSQL tests and process restart,
preserved the local/offline product boundary, and completed exact teardown.
The current complete portable server read-back is 1,282 tests: 1,245 passed and
37 declared platform/capability skips. The governed fixed set is 172 tests.

## Terminal route evidence

Exact head `9551532dae823df2c84217204344445d798634ca` returned terminal
`deterministic-no-model` with public-safe evidence SHA-256
`4a70cc173cdffea67a97939fe43f85a4a907e4ddf6546e532006219b8c1004c1`.
It exposed an ambiguity between prompt refusal and tool selection. Exact head
`98fb89f9809f178e18fb5ac529eb35d3378d16c5` also returned terminal
`deterministic-no-model`, with public-safe evidence SHA-256
`bbf9e67ccd61b50f833b7f16d73e7f41f68529e9a5bd7c16be0706977dd7e795`.
It exposed ambiguous ownership of answer and citation fields. Both receipts are
terminal and inadmissible; neither is resumed, relabeled, or reused. Raw model
output, private measurements, logs, credentials, and private locations remain
outside Git.

## Current operational boundary and limits

A fresh post-aggregate operational observation on 2026-08-12 found the Qwen
rapid service warm and the admission broker active against the exact rapid
profile above. Its configured and qualification-probed limit is four active
distinct owners; it was not throttled to one. This transient read-back is not a
sustained-load result or availability commitment.

Gemma's eight-owner complex admission limit is proved for its selected-route
qualification, but Gemma is not claimed simultaneously resident with Qwen. One
Spark cannot keep the unchanged `0.40` rapid and `0.70` complex profiles resident
together. A second owned GPU node and IT-controlled private route remain
required before warm two-route promotion. No generic TPS, p50/p95/p99,
sustained-capacity, production-SLO, enterprise-network, or deployment claim is
authorized by this evidence.
