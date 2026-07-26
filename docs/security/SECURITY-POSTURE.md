# Public Security Posture

This document describes implemented controls and explicit handoffs without
publishing private security evidence. It is not a penetration-test report,
certification, production authorization, or substitute for enterprise review.

## Implemented controls through the active Phase 7 branch

### Local data and filesystem

- Tauri's canonical app-data directory owns runtime data. Legacy migration is
  serialized, bounded, non-following, conflict-aware, and hash-verifies staged
  and destination data before source retirement.
- External recordings are admitted through native picker/drop and path identity
  checks. Cancel, retry, retention, and cleanup do not delete source media.
- Private files use owner-controlled locations and atomic publication. Reads
  and mutations reject unexpected file types, links/reparse points, path escape,
  replacement identity, size/extent mismatch, and invalid hash/schema lineage.
- Shared Rust and Python readers cap persisted-file bytes and bind reads to an
  opened regular-file descriptor; install identity and server artifacts apply
  their additional schema, exact-extent, and hash contracts.
- Destructive recording/result operations use explicit intent, quarantine, and
  revalidation. Recovery preserves ambiguous evidence rather than guessing.
- Renderer playback and transcript actions require native admission/authorization;
  a path string alone is not capability authority.

### Runtime and process

- Audio callback work is preallocated/non-blocking and queues/resources are
  bounded. Loss and worker failures become explicit state instead of fabricated
  successful audio.
- Session and periodic native work has explicit cancellation/join ownership.
  Shortcut and native-import dispatchers are fixed process-lifetime workers
  with bounded queues, not per-event thread creation.
- The server reference worker runs non-root, without network, with read-only and
  bounded mounts/resources, dropped privileges/capabilities, immutable
  image/model identity, bounded output, and unconditional cleanup.
- Installer-only custom containment has been retired. Stock Tauri NSIS behavior
  is tested in a disposable Windows environment; genuine runtime process safety
  remains in product/server code.

### Network and protocol

- The current application server binds to numeric loopback. The development
  private-node path uses an explicitly managed SSH local forward and no
  application-controlled alias failover.
- Desktop configuration validates/approves origins and binds in-flight work to
  a configuration generation. Stale-origin responses cannot mutate current
  job state. One settings-save lease spans confirmation, durable publication,
  origin approval, generation invalidation, and applied-state projection.
- Persisted connector settings and origin approval use a 64 KiB admission
  bound, no-follow regular-file opens (including Windows reparse rejection),
  and no-follow lock files. Server URL input is limited to 2,048 bytes before
  parsing.
- HTTP requests/responses, headers, bodies, chunks, files, jobs, retries,
  workers, queues, durations, retention, and transcript/model metadata are
  bounded and contract-validated.
- Create/upload/commit/cancel/result behavior is idempotent or conflict-visible;
  server result identity/hashes/authority are reverified before native History
  publication.
- Health advertises capability only when the runtime is ready. Private
  WebSocket admission is not advertised as live ASR or production availability.
- Authentication fails closed by default for every non-health operation. The
  fixed development principal is permitted only by explicit development-only
  loopback configuration.
- The common OIDC verifier enforces fixed algorithms, issuer/audience/time/key
  claims, bounded discovery/JWKS retrieval, and single-flight refresh. Entra
  mode supplies the tenant, delegated-scope, allowed-client, role, claim,
  canonical `tid`/`oid`, and token-type policy.
- Server jobs, LID requests, idempotency, artifacts, revocation, purpose-control,
  and audit events are scoped by the validated `(tid, oid)` principal.
  Cross-owner and absent resources use the same non-disclosing response.
- The `Yap.IdentityAdministrator` role gates same-tenant access and purpose
  mutations. Enrollment, matching, and adaptation require their declared active
  purpose-grant combinations; both allowed and denied decisions are redacted and
  audited. No voice profile or embedding implementation is implied.
- Entra mode starts an authenticated private WebSocket listener on numeric
  loopback, port `18766` by default, separate from HTTP. Exact `yap.live.v1`
  negotiation, connection/message/queue/replay bounds, token expiry, and access
  revocation fail closed. The native lower actor uses the same token source and
  session lease; sign-out or account/configuration change cancels handshake and
  I/O.
- The Windows desktop exposes a narrow in-process native token-provider
  interface, but no production adapter is selected or approved. Rust keeps
  tokens in zeroizing memory, marks bearer headers sensitive, and hashes both
  the selected account identity and normalized tenant/client/API-scope
  configuration before durable binding. Raw tokens and account IDs never enter
  React, ordinary app-data configuration, the job ledger, or logs; the ledger
  receives only the configuration digest, not copied tenant/client/scope
  values. Missing provider support fails closed.
- Durable remote work is immutably account-and-authentication-bound before
  dispatch. Account/configuration switching, sign-out, and attempts to claim
  ambiguous pre-Phase-7 authenticated work fail before another bearer can be
  sent. Schema 14 quarantines older authenticated account-only bindings while
  preserving paired `development-loopback` authority for unauthenticated local
  work.

### UI and local control

- Tauri command authorization is window-aware and domain owners validate
  untrusted invoke data before mutation.
- One native tray/island owner controls window bounds and the visible hit region;
  no duplicate invisible window catches clicks.
- Shortcut enrollment is deliberate and bounded so ordinary typing is not
  captured as configuration. Runtime events/actions use fixed-capacity queues.
- Native drops have one fixed worker and one-batch backlog; a single picker
  lease prevents stacking blocking OS dialogs.
- Reduced-motion preference is honored on the renderer's first state as well as
  subsequent OS preference changes.
- User-visible errors use stable state/codes and avoid private audio/transcript
  content. Private diagnostic and scan material stays outside Git/PR/hosted logs.

### Supply chain and release

- Node, pnpm, Rust, Python, container, model, and critical tool/action identities
  are constrained by manifests, lockfiles, hashes, reviewed revisions, or
  immutable digests as appropriate.
- Directly adapted third-party source has a pinned upstream revision, verified
  license, local file hashes, notice, and an executable provenance contract.
- The mock OIDC provider is pinned by version and immutable image digest.
  Focused discovery/JWKS/signed-token owner-flow checks are green; hosted Docker
  execution remains an open phase-gate item.
- Release contracts bind cache use, build inputs, artifact hash, evidence, and
  immutable commit identity. The staged release workflow creates a draft only
  from the verified commit/artifact transaction.
- Focused tests run during development; exact-head phase/checkpoint gates and
  hosted PR checks precede merge.

## Known boundaries, not hidden controls

The current loopback/SSH development profile and focused Phase 7 evidence do
not provide:

- an approved production native token adapter, real enterprise tenant/app
  registration, Conditional Access, MFA, consent, token-protection, guest, or
  offboarding conformance;
- production identity storage, encryption/keys, backup/deletion, audit
  retention/export, production administrator-role assignment, or legal/privacy
  approval;
- live ASR over the private admission seam, product endpoint discovery, an
  external same-origin WSS/TLS endpoint, HTTP/3, enterprise certificate, or
  internal DNS;
- an IT-approved firewall policy or ZPA application segment;
- persistent production service supervision, backup/restore, disaster recovery,
  monitoring/SIEM integration, or measured multi-user capacity; or
- enterprise deployment/publication approval.

These are accepted Phase 7/10 and IT/security/network handoffs in the
[roadmap](../roadmap/ROADMAP.md). Developer-owned infrastructure must not be
described as satisfying them.

Phase 7 final review, the full phase gate, hosted PR closure, and merge are
still open. Focused green evidence is not release or production authorization.

## Security review and disclosure handling

- Correctness and security findings must be resolved before checkpoint/phase
  merge or recorded as an explicit later owner/handoff.
- Private scans, scan identifiers, exploit details, machine paths, private
  audio/transcripts, and raw host evidence are never committed or summarized in
  public PR/CI output.
- A full Codex security plugin scan is intentionally deferred until the accepted
  Phase 10 enterprise gate. Normal development still requires focused threat
  reasoning, code review, tests, dependency audits, and safe design.
- If a vulnerability is suspected, stop publication, preserve private evidence,
  fix and validate the affected boundary, and disclose only through the
  repository owner's approved private channel.
