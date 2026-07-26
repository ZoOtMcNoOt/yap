# Independent transcript-reference review

This runbook turns one frozen, private natural-speech source packet into an
adjudicated reference that Yap's promotion loader can trust. It does not create
model evidence, replace the frozen provider gate, or make a locale promotable
by itself.

Audio, upstream and reviewed transcripts, assignments, participant records,
legal snapshots, hypotheses, receipts, registries, and raw scores stay in an
owner-only external evaluation cache. Git, pull requests, hosted CI, and public
documentation receive only transcript-free aggregate status after review.

The machine-enforced contract lives in:

- [`transcript_reference_review.py`](../../server/src/yap_server/evaluation/transcript_reference_review.py);
- [`reference_review_registry.py`](../../server/src/yap_server/evaluation/reference_review_registry.py);
- [`corpus_manifest.py`](../../server/src/yap_server/evaluation/corpus_manifest.py); and
- [`manifest_scoring.py`](../../server/src/yap_server/evaluation/manifest_scoring.py).

The [evaluation corpus and runtime matrix](../research/2026-07-17-asr-evaluation-corpus-and-runtime-matrix.md)
defines source independence and scoring policy. If this runbook and the checked
code disagree, stop and reconcile the checked code before collecting evidence.

## Roles and independence

Authorize named private participant IDs for the minimum required roles:

1. **Listener A** and **Listener B** independently review the same blind source
   assignment. They must be different people and must not see each other's
   work, model hypotheses, provider scores, or model-generated corrections.
2. **Adjudicator** reviews both completed listener receipts and must be
   independent of both listeners.
3. **Locale reviewer** establishes an exact BCP 47 locale when the proposed tag
   has a subtag. A source marker such as `es` cannot establish `es-ES`,
   `es-419`, or another regional tag.
4. **Rights decision owner** binds the exact legal notice and records audio,
   reference, commercial-use, redistribution, attribution, and
   reidentification decisions.

One person may hold multiple non-listener roles only where organizational
policy permits and the executable registry accepts it. Never collapse the two
listeners or use either listener as the adjudicator.

## 1. Freeze and verify the source packet

The assignment coordinator begins with a new owner-only directory beneath the
private evaluation root. The packet must contain only the exact case inputs and
their source/derivation records. It must not contain peer reviews, provider
results, model hypotheses, or scoring output.

Before assignment:

- verify the candidate-set and model-freeze receipts;
- verify the source item's recorded time is strictly after every candidate
  freeze when using `created_after_model_freeze`;
- verify canonical mono PCM16 audio at 16 kHz, duration, byte length, raw WAV
  SHA-256, and decoded-PCM SHA-256;
- verify the upstream-reference, source-index, trim, preprocessing, legal, and
  attribution identities;
- record the base source-language marker without inventing a regional locale;
- verify every packet file against a byte/hash inventory; and
- make the packet and every containing directory inaccessible to other local
  users.

A failed, missing, mutable, out-of-root, or unexpectedly duplicated artifact is
a stop condition. Do not repair identity by editing a receipt after review has
started; freeze a new packet revision instead.

## 2. Create the blind assignment

The assignment receipt binds:

- case ID;
- Listener A and Listener B participant IDs;
- canonical-audio SHA-256;
- upstream-reference SHA-256;
- exact packet revision; and
- explicit exclusion of `modelHypotheses` and `peerReviews`.

Give each listener a private copy or independently access-controlled view of
the same frozen audio, upstream reference, and assignment. Do not include the
other listener's identity beyond what the assignment contract requires, and do
not reveal provider output or aggregate WER before both reviews complete.

## 3. Complete two independent listens

Each listener hears the complete source audio and checks the upstream reference
against literal delivery. The listener creates a reviewed reference and a
receipt containing the assignment, audio, upstream-reference, reviewed-
reference, completion-time, participant, and decision identities.

Use these dispositions:

- `pass` only when the listener considers the reviewed reference suitable for
  the frozen scoring policy;
- `hold` when another listen, locale decision, source clarification, or rights
  decision is needed; and
- `exclude` when the item cannot become reliable promotion evidence.

Do not silently normalize away spoken omissions, additions, numbers, names,
technical terms, interruptions, disfluencies, or source defects. Record known
defects for adjudication. A listener may use ordinary playback controls, but
must not use a candidate ASR hypothesis as a transcription aid.

## 4. Adjudicate after both reviews

Only after both listener receipts are complete may the adjudicator compare
them and produce the final reference. The adjudication receipt binds both
listener-receipt hashes, the final-reference hash, disposition, known defects,
locale evidence, completion time, and adjudicator identity.

If the final disposition or reference differs from either listener's result,
the adjudicator records bounded override-reason codes. If nothing changed, an
override reason is forbidden. The final disposition cannot be `pass` while a
required rights or exact-locale decision remains unresolved.

## 5. Bind locale, rights, attribution, and exposure

The locale-basis receipt records the final canonical BCP 47 tag and its basis.
Tags with subtags require `humanLocaleAdjudication`; a base source-language
marker is sufficient only for the same base tag.

The rights receipt must bind the exact legal-notice hash. A passing case
requires approved audio and reference decisions and allowed commercial use.
Redistribution and reidentification restrictions remain explicit even when
evaluation use is approved. Attribution, source identity, preprocessing, and
candidate exposure each receive their own hash-bound receipts.

Do not infer post-freeze status from a release name. The exposure receipt must
bind the exact model ID/revision, candidate lock, freeze evidence, source item,
recording time, and one allowed status: `created_after_model_freeze` or
`contractually_excluded`.

## 6. Assemble and validate the private registry

The coordinator assembles the case receipt and every supporting artifact into
the private promotion registry. The registry must authorize each participant
for the role claimed by an artifact and must bind the complete frozen candidate
set. Set `YAP_EVAL_PROMOTION_REGISTRY_SHA256` from a separately calculated
registry digest; a digest copied from the registry cannot attest to itself.

Load the manifest through `load_promotion_corpus_manifest`, not a generic JSON
parser. The checked loader rejects missing roles, mismatched or raced files,
duplicate identities, wrong candidate sets, stale freeze/exposure evidence,
unsafe paths, invented locale subtags, incomplete reviews, and self-attested
registry state.

The case is review-complete only when the checked loader accepts the exact
manifest and registry from the owner-only cache. Scoring then runs through
`score_manifest_case`, which independently rechecks the audio, adjudicated
reference, candidate, inference-result, scorer, and optional critical-token
policy identities.

## Stop, invalidate, and escalate

Stop the review and retain a `hold` disposition when source identity, model
freeze ordering, exact locale, rights, reviewer independence, or artifact
integrity cannot be established. Escalate locale questions to the authorized
locale reviewer, reuse questions to the rights decision owner, and candidate or
registry mismatches to the evaluation owner. None of those decisions may be
filled in by the model under evaluation.

If audio, reference, preprocessing, candidate set, scorer policy, assignment,
or any bound receipt changes after assignment, mark that packet revision
superseded and create a new frozen revision. Do not overwrite the old artifacts
or edit their hashes into agreement. Retain or delete superseded private
artifacts only under the approved evaluation-retention policy; never move them
into the repository as a rollback shortcut.

## Completion and claims

Record only public-safe completion facts after review: case count, covered
locale, review disposition, checked head, and whether the frozen promotion gate
passed. Never publish private paths, participant identities, audio, transcripts,
hypotheses, receipt hashes, raw scores, or registry details.

Preparing a source packet is not a review. Two listener receipts without
adjudication are not a final reference. One accepted case is not broad locale,
noise, meeting, long-form, or production certification. Provider and catalog
promotion still require every frozen Phase 6 slice and the complete checked-
head gate.
