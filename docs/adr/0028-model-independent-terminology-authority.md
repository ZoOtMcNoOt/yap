# ADR 0028: Model-independent terminology authority and frozen projections

**Date:** 2026-08-09  
**Status:** Accepted (canonical Phase 9 terminology boundary)  
**Builds on:** [ADR 0016](0016-auth-identity-bridge.md), [ADR 0017](0017-knowledge-base-compiler.md), [ADR 0022](0022-google-okf-permission-safe-projections.md), and [ADR 0024](0024-global-language-routing.md)

## Context

Yap needs personal spellings, team vocabulary, and organization terminology to
remain consistent across dictation, batch transcription, deterministic
normalization, grammar correction, knowledge retrieval, and agent workflows.
Provider-native prompts and word boosts are useful projections, but making a
provider, tokenizer, ASR model, or grammar model authoritative would couple user
data to a replaceable runtime and allow different stages to apply different
revisions.

Terminology can contain sensitive product, project, person, and clinical terms.
Its ownership and visibility therefore require the same tenant-scoped identity
and compiled-permission discipline as other governed knowledge.

## Decision

### One canonical domain

Yap owns one model-independent, append-versioned terminology domain. Each record
has a tenant, stable record ID, scope, owner, locale, canonical form, explicit
variants, sensitivity, monotonic version, deletion tombstone, audit revision,
and timestamp.

The supported scopes and owners are:

| Scope | Owner | Precedence |
|---|---|---|
| `organization` | tenant | lowest |
| `team` | tenant-scoped team | middle |
| `personal` | token-derived subject | highest |

Precedence applies only when the same case-folded variant is visible and valid
for the requested locale. Equal-precedence variants resolving to different
canonical forms are a conflict and fail snapshot creation. Deletion is a new
versioned tombstone; history is not overwritten.

The user-facing controls belong under Dictation/Personalization, but UI
placement does not own or reshape the domain.

### Freeze one snapshot per job or session

At job/session admission, the server resolves the token-derived tenant and
subject, explicit tenant-scoped team memberships, requested locale, and latest
record versions into one immutable snapshot. The snapshot has a deterministic
SHA-256 identity and source revision. ASR, normalization, grammar correction,
result evidence, knowledge compilation, and agents use that exact identity for
the lifetime of the job/session; an in-flight job never observes later edits.

Snapshot construction rejects cross-tenant records, invalid owners/locales,
duplicate versions, equal-precedence conflicts, and malformed or unbounded
data. Models do not participate in authorization or conflict resolution.

### Compile bounded projections

The snapshot compiles into four replaceable projections:

1. Provider-specific ASR hints, contexts, or word boosts only when the pinned
   provider capability explicitly supports them. Entry, character, token, and
   locale bounds fail closed; prompts or language dictionaries are not
   mislabeled as terminology support.
2. Deterministic exact-form normalization for configured variants. Raw ASR text
   remains immutable; every replacement records the raw span, original text,
   replacement, and snapshot identity and can be undone.
3. Grammar-model preservation constraints. A grammar model may improve a
   separate revision but may not invent, delete, or semantically rewrite
   protected critical terms. Its output is never the terminology source.
4. Google OKF `Term` concepts carrying snapshot provenance. They enter the
   ordinary compiled permission ledger and are searchable only through the
   permission-safe retrieval boundary. Suggestions remain non-canonical until
   accepted by an authorized owner.

### Privacy and audit

Only the terminology owner or an authorized tenant/team administrator may
create a new record version or tombstone. Query and projection APIs receive a
validated principal; callers cannot supply a different owner. Logs and public
receipts contain identities, counts, hashes, reason codes, and timings—not term
text, variants, prompts, or transcript content.

## Consequences

- Replacing an ASR or reasoning model does not migrate canonical terminology.
- All stages can prove they used the same revision.
- Personal overrides do not mutate team or organization data.
- Conflicts fail explicitly instead of producing provider-dependent behavior.
- A terminology update affects only newly admitted jobs/sessions and newly
  compiled knowledge generations.
- Provider projections may reject an oversized snapshot; they do not silently
  truncate it or weaken ownership.

## Required verification

- deterministic snapshot identity and repeatability;
- personal/team/organization visibility, precedence, conflicts, and tombstones;
- locale and cross-tenant isolation;
- bounded provider capability and unsupported-provider failure;
- raw-preserving exact-form edits and undo evidence;
- grammar preservation identity;
- permission-filtered OKF glossary compilation and revocation;
- concurrent job/session revision pinning;
- redacted audit and failure output.

The active Phase 9 candidate implements these boundaries through a
server-derived immutable authorization context, owner-scoped append-only ledger,
job-bound snapshot identity, four deterministic projections, and governed-agent
snapshot consumption. Focused tests cover forged membership/admin claims,
cross-owner and cross-tenant access, precedence/conflicts/tombstones, stale or
wrong-owner job snapshots, projection bounds, revocation, and redacted evidence.
Exact candidate `a4f34678ea9980379b18266d40d3347b818ac57e` passed the one complete
Phase 9 gate. Hosted review and merge remain pending; this is not a production
retention, administration, or enterprise-directory claim.

Enterprise group resolution, administrator policy, retention periods, and
production audit export remain IT/security handoffs. Their absence does not
authorize Yap-native credentials or caller-selected ownership.
