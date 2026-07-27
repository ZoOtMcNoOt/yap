# Tenant-scoped identity and job authorization plan

**Status:** Active on `feat/phase7-identity-access`.

**Branch:** `feat/phase7-identity-access`

**Base:** Reviewed post-Phase-6 checkpoint merge
`15f9c8ac00211b9d2f28845d419258ae2c8de8e4`.

**Current closure state:** The original Phase 7 implementation and exactly-three
review closure exist. Candidates
`134ec08002aeb1deca83547d511528b282966731` and
`7046d98d61fec90d4c639e92aff09ff8f6a2083a` are consumed. The first candidate's
fresh private children validated, but its one complete matrix exposed a
post-hoc Windows `taskkill /T` timeout in the release-contract command limiter.
The replacement uses suspended creation, nested Job assignment, kill-on-close,
and authoritative Job accounting-zero proof. The second candidate passed all
13 fresh private children, then its one complete matrix exposed that the new
supervisor declared PowerShell 7.4 without also requiring the Core edition.
Follow-up runtime review then proved that dynamically created script blocks do
not enforce `#requires`. The corrected encoded-command boundary checks both
Core edition and version 7.4 before creating the loader script block. Thirteen
focused Windows/installer contracts and the complete affected release-contract
cell pass 81/81, and same-three closure found no P0–P2 issue. A new exact-head
admission, fresh private evidence, the one
complete replacement matrix, first-attempt hosted closure, the focused PR, and
merge remain open.

**Scope:** Add the authenticated principal and authorization boundary required
for a multi-user private server without changing local/offline dictation,
implementing Phase 8 speaker inference, pulling Phase 9 knowledge/agent work
forward, or claiming IT-controlled enterprise deployment.

## Executable outcome

1. `/v1/health` remains public and truthfully advertises whether authentication
   is required. Every other server route is protected when the Entra profile is
   enabled.
2. The server validates only Yap API access tokens. It checks the configured
   signing authority and keys, fixed algorithm allow-list, exact issuer,
   audience, tenant, expiry/not-before, delegated scope, allowed client actor,
   and stable `tid` and `oid` claims before constructing an immutable
   principal.
3. Server job creation, chunks, status, results, retry, cancellation, LID, and
   later live admission receive that principal from middleware. Client-supplied
   owner text and the desktop installation namespace are never authorization.
4. Durable jobs, idempotency keys, artifact paths, audit events, and
   authorization records are tenant-and-subject scoped. Cross-principal lookup
   returns the same not-found projection as an absent resource.
5. The desktop has one narrow Rust-owned native access-token-provider
   interface, keeps tokens out of renderer and ordinary app-data persistence,
   and owns bearer injection, expiry, account-plus-authentication binding,
   sign-out fencing, and connector generations. Production currently has no
   installed provider and fails closed; an enterprise-approved adapter remains
   an explicit handoff.
6. Purpose grants and principal access revocation have one durable,
   append-only audit owner. Sign-in does not create a voice profile or imply
   enrollment, matching, adaptation, knowledge access, or speaker naming.
7. The loopback development profile remains explicit and usable without
   enterprise credentials. It uses a fixed development principal only when
   `YAP_SERVER_CONFIGURATION=development` and
   `YAP_AUTH_MODE=development_loopback`; that principal can never be selected
   by a client or accepted on an externally bound server. The default
   disabled-auth configuration fails closed for protected work.

## Architecture decisions

### Native client

`NativeAccessTokenProvider` is the only desktop authentication seam. It models
silent acquisition, interactive sign-in, session status, and sign-out while
Rust owns request correlation, connector generations, account-and-authentication
configuration-bound durable work, expiry fences, and bearer injection.
Fake-provider tests exercise that contract without storing tokens in renderer
or ordinary app-data state.

The production manager intentionally has `provider: None` and reports
authentication unavailable. No MSAL.NET/WAM helper, system-browser adapter,
protected broker cache, or other production provider is shipped or approved.
Selection and conformance belong to the
[Entra identity conformance handoff](../../runbooks/entra-identity-conformance-handoff.md).

### Server authentication

Authentication is dependency-injected ahead of route dispatch. The
provider-neutral OIDC owner performs bounded discovery and same-origin JWKS
retrieval, caching, rotation retention, and unknown-`kid` refresh. The Entra
profile derives its issuer from the configured tenant rather than accepting a
production override. Pinned `PyJWT[crypto]` performs JOSE validation behind a
Yap-owned verifier. The Entra policy fixes `RS256`, issuer, Yap API audience,
`access_as_user` delegated scope, allowed `azp` client, time claims, `tid`, and
`oid`, and rejects app-only or wrong-resource tokens. Focused tests use
process-generated keys; the pinned mock provider exercises standards-based
discovery/JWKS without an Entra tenant or checked-in credential.

The native client does not validate access tokens. The Yap API is the resource
server and owns token validation.

Authenticated private live admission shares the REST principal policy and
rechecks access revocation. The current runtime still has two loopback
listeners: REST on `127.0.0.1:18765` and live WebSocket admission on
`127.0.0.1:18766`. The desktop does not infer or discover the live origin from
the REST origin. No production same-origin HTTPS/WSS edge or discovery contract
exists, and this admission boundary does not promote a server live-ASR
provider.

### Identity and authorization persistence

Phase 7 introduces an `IdentityRepository` boundary with one SQLite durable
development implementation. SQLite is an application-owned executable
baseline, not a production database approval or the Phase 9
Postgres/pgvector knowledge store. The schema owns:

- minimal principals keyed by `(tenant_id, subject_id)`;
- a durable principal access-disabled latch plus revocation epoch, which
  immediately stops new Yap operations until an explicit administrative
  restore without claiming instantaneous Entra token revocation;
- purpose grants with deployment-supplied legal-basis and privacy-review
  references;
- immutable grant/revoke/access events; and
- a tamper-evident audit chain that excludes tokens, audio, transcripts,
  embeddings, and optional Graph claims.

Purpose grants store control-plane authorization only. No voice embedding,
enrollment artifact, match, speaker name, or knowledge permission is created in
Phase 7.

Production database topology, encryption-at-rest, backup, administrative
retention, and deployment remain explicit infrastructure approvals. A later
Postgres adapter must implement the same repository contract rather than
creating a second authorization source. The Phase 7 code and migration boundary
must not pretend those approvals exist.

### Phase boundary

Phase 7 implements identity, authenticated ownership, authorization/revocation
primitives, and purpose-grant records. Phase 8 owns voice enrollment material,
speaker profiles, biometric matching, reconciliation, and named speaker
publication. Phase 9 owns knowledge permission compilation and agents. Phase 10
owns production supervision, enterprise network integration, full security
scanning, capacity/SLO promotion, and deployment evidence.

## Ordered implementation slices

- [x] Create the focused branch from the reviewed checkpoint merge and inspect
      current executable ownership, ADRs, roadmap, dependencies, and official
      identity-platform support.
- [x] Reconcile the completed checkpoint status and record this active plan
      without changing executable behavior.
- [x] Add typed server auth configuration, immutable principal context,
      authentication middleware, bounded Entra signing-key validation, and
      focused claim/route tests. Keep `/v1/health` public.
- [x] Add the identity repository, principal upsert, access revocation,
      purpose-grant lifecycle, redacted append-only audit behavior, schema
      migration tests, and explicit production-storage handoff.
- [x] Make job state, idempotency, artifacts, service calls, and lookup
      authorization principal-scoped. Migrate legacy development state only to
      the disabled-auth development principal; never attach it to the first
      authenticated user.
- [x] Carry the authenticated principal through LID and server job-service
      admission, with non-disclosing cross-owner tests and no Phase 8 speaker
      behavior. Owner-fair provider-pool/router admission remains Phase 10.
- [x] Add the narrow native token-provider interface, fake-provider lifecycle
      tests, connector-generation/account fencing, zeroizing token ownership,
      and bearer injection for capabilities, LID, batch, and live admission.
      Preserve local dictation and offline history when authentication is
      unavailable.
- [x] Add focused end-to-end fixtures for two tenants, two users in one tenant,
      token expiry/not-before, wrong resource/scope/issuer/tenant/algorithm,
      wrong/app-only client actor, unknown-key single-flight refresh, access
      revocation, grant revocation, restart, cancellation, idempotency, and
      cross-owner non-disclosure.
- [x] Reconcile ADR 0016, ADR implementation scores, Voice OS architecture,
      roadmap, executable ownership, current status, provenance, runbooks, and
      IT handoffs with observed behavior. Do not mark biometric, knowledge, or
      enterprise work complete.
- [x] Repair focused implementation findings: tenant-specific account
      authority,
      schema-13 quarantine for ambiguous older authenticated bindings,
      schema-14 durable account/configuration binding for remote cleanup,
      protected readiness, durable access disable/restore, read-only steady
      principal admission, rollback on failed first-principal commit,
      revoked-principal migration backfill, truthful OpenAPI/health,
      post-publication settings cleanup, live settings status, accessible async
      status, provider-neutral OIDC discovery/JWKS ownership, and
      revocation-aware private live admission.
- [x] Add the digest-pinned mock-OIDC owner-flow harness, bounded public-safe
      receipt contract, and reviewed `ubuntu-latest` `mock-oidc` job. Focused
      static and workflow/gate contracts are green; the Docker-backed flow
      still awaits hosted execution on the final reviewed head.
- [x] Run exactly three bounded antagonistic reviews of the ready executable
      branch, repair all P0-P2 correctness/security/privacy/maintainability
      findings, and run focused verification for those repairs.
- [x] Obtain bounded read-only closure from the same three reviewers on the
      exact repair head; do not add a fourth reviewer or consume the full gate.
- [x] Obtain bounded closure from those same three reviewers on the
      function-named Windows bounded-command Job supervisor repair. Preserve
      the typed primary failure, prove nested active-process-zero, and keep the
      archived installer implementation recoverable without restoring its
      NSIS-specific machinery.
- [ ] Freeze one exact candidate and run the complete applicable
      local/native/server/target-client/private-server Phase 7 matrix once.
- [ ] Open a focused PR; require first-attempt hosted CI, CodeQL, and
      disposable-Windows stock-NSIS closure on the checked head, or record
      equivalent local evidence and explicitly disclose unavailable hosted
      checks.
- [ ] Merge only the reviewed green SHA, then create the separate post-Phase-7
      ownership/maintainability checkpoint before Phase 8.

The production native provider/protected cache is an IT-backed conformance
handoff, not a developer-owned Phase 7 completion criterion. The production
same-origin HTTPS/WSS edge or live-endpoint discovery contract remains a later
transport/deployment decision, principally Phase 10. Phase 7 closes only the
fail-closed interfaces and authenticated admission baseline that those owners
will consume.

## Focused verification during development

- Python auth/config/repository/request/job tests through the locked Python 3.12
  `uv` environment and the narrow Ruff baseline.
- Rust connector/auth-adapter/unit and server-connector integration tests with
  generated short-lived tokens; never persist test tokens.
- Migration/restart tests using disposable private directories and databases.
- Negative authorization tests that assert identical absent/cross-owner
  projections and redacted logs.
- Native token-provider and connector lifecycle tests with a fake provider.
  Production adapter packaging and enterprise sign-in remain open.
- A registration-independent synthetic issuer/JWKS integration gate with two
  principals and real asymmetric signatures. It proves the resource-server and
  ownership boundary, not Entra consent, Conditional Access, WAM, or a final
  production audience. The digest-pinned Docker provider is exercised by the
  hosted `mock-oidc` job, not by this Docker-less local host.

The complete matrix is reserved for the frozen candidate. Focused tests may run
repeatedly while implementation is changing.

The focused identity implementation and original exactly-three review closure
are complete. The mock-OIDC harness suite is 8/8 green. The replacement Windows
command boundary has an eleven-case functional contract covering invocation-bound
status, pre-assignment cleanup, typed-error preservation, private-file cleanup,
launch and immutable supervisor-source integrity, bounded watchdog settlement,
retained descendants, nested Jobs, and batch-command and exact-environment
fidelity. After the second consumed candidate exposed the missing
`#requires -PSEdition Core` declaration, follow-up runtime review proved that
dynamic script blocks ignore `#requires`. The corrected encoded-command
boundary passed 13 focused Windows/installer contracts and the complete
affected release-contract cell 81/81 with no same-three P0–P2 finding. This remains focused
evidence, not a rerun of the consumed complete phase matrix. A Docker 29 ARM64
diagnostic
proved the bounded Linux loopback proxy against the locked provider on an
internal bridge, but it did not produce an exact-head owner-flow receipt.
These are focused development results, not the reserved complete Phase 7
matrix or hosted first-attempt evidence.

## IT, security, privacy, and deployment handoffs

The authoritative decision and evidence checklist is the
[Entra identity conformance handoff](../../runbooks/entra-identity-conformance-handoff.md).
Yap can implement and test the application boundary, but the following remain
external approvals or inputs:

- Entra tenant and native/API app registrations, redirect URIs, exposed Yap API
  scope, assignment policy, Conditional Access, broker/token-protection policy,
  and production revocation expectations;
- approved tenant, client, and audience identifiers;
- production database service, encryption keys, backup/deletion SLA,
  administrator roles, and audit retention/export;
- legal basis, special-category condition, approved notice version, privacy
  assessment reference, and jurisdiction-specific deletion requirements before
  any biometric purpose can be enabled;
- TLS, certificates, DNS, ZPA, firewall, synchronized time, service identity,
  monitoring, capacity authorization, and deployment approval.

No branch substitutes developer-owned identity, networking, certificates, or
policy for these handoffs.

## Gate rules

- No full Codex Security scan before Phase 10. Phase 7 uses focused threat
  modeling, diff review, dependency audits, and executable negative tests.
- Never commit or publish access/refresh tokens, tenant-private identifiers,
  private audio/transcripts, raw evaluation data, host paths, process ledgers,
  scan output, or private receipts.
- Preserve external dependency provenance and licenses.
- Do not consume the complete phase matrix until the executable candidate and
  documentation are ready.
- Do not retry, resume, or relabel a consumed candidate gate or first-attempt
  hosted closure.
