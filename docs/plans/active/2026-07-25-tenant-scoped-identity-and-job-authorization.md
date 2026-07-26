# Tenant-scoped identity and job authorization plan

**Status:** Active on `feat/phase7-identity-access`.

**Branch:** `feat/phase7-identity-access`

**Base:** Reviewed post-Phase-6 checkpoint merge
`15f9c8ac00211b9d2f28845d419258ae2c8de8e4`.

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
5. The desktop obtains Yap API tokens through an official MSAL native-client
   adapter, keeps access tokens out of renderer and ordinary app-data
   persistence, attaches bearer authorization at the connector boundary, and
   handles silent refresh, interactive sign-in, sign-out, expiry, and
   reconfiguration without duplicating connector ownership.
6. Purpose grants and principal access revocation have one durable,
   append-only audit owner. Sign-in does not create a voice profile or imply
   enrollment, matching, adaptation, knowledge access, or speaker naming.
7. The existing loopback development profile remains explicit and usable
   without enterprise credentials. It uses a fixed development principal only
   inside the disabled-auth loopback profile; that principal can never be
   selected by a client or accepted on an externally bound server.

## Architecture decisions

### Native client

Microsoft does not publish a supported Rust MSAL implementation. The Windows
desktop therefore uses a small official MSAL.NET public-client adapter rather
than implementing OAuth/OIDC token acquisition in Rust or using renderer
`localStorage`. Rust owns adapter lifecycle, request correlation, connector
generation, and bearer injection. MSAL owns interactive Authorization Code +
PKCE, its encrypted token cache, silent acquisition, refresh, and broker/system
browser behavior.

The adapter has a versioned bounded stdin/stdout protocol, no arbitrary command
surface, no token logging, no client secret, and no ability to choose a server
origin. Packaging and teardown use the ordinary Tauri runtime-sidecar boundary;
they do not restore retired installer-only containment.

### Server authentication

Authentication is dependency-injected ahead of route dispatch. Production
configuration is single-tenant and derives the metadata/JWKS authority from the
configured tenant identifier rather than accepting an arbitrary discovery URL.
Pinned `PyJWT[crypto]` performs JOSE validation behind a Yap-owned verifier. The
verifier fixes `RS256`, enforces the tenant-specific issuer, Yap API audience,
`access_as_user` delegated scope, allowed `azp` client, time claims, `tid`, and
`oid`, and rejects app-only or wrong-resource tokens. Key documents are fetched
with bounded size/time, cached for a bounded lifetime, and refreshed once
through a single-flight path for an unknown `kid`. Tests use process-generated
asymmetric keys and never require an Entra tenant or checked-in credential.

The native client does not validate access tokens. The Yap API is the resource
server and owns token validation.

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
- [x] Add the official MSAL native adapter, encrypted cache integration,
      bounded Rust protocol owner, connector-generation token acquisition, and
      bearer injection for capabilities, LID, and batch calls. Preserve local
      dictation and offline history when sign-in or the server is unavailable.
- [x] Add focused end-to-end fixtures for two tenants, two users in one tenant,
      token expiry/not-before, wrong resource/scope/issuer/tenant/algorithm,
      wrong/app-only client actor, unknown-key single-flight refresh, access
      revocation, grant revocation, restart, cancellation, idempotency, and
      cross-owner non-disclosure.
- [x] Reconcile ADR 0016, ADR implementation scores, Voice OS architecture,
      roadmap, executable ownership, current status, provenance, runbooks, and
      IT handoffs with observed behavior. Do not mark biometric, knowledge, or
      enterprise work complete.
- [x] Repair the initial adversarial findings: tenant-specific MSAL authority,
      schema-13 quarantine for ambiguous older authenticated bindings,
      protected readiness, durable access disable/restore, read-only steady
      principal admission, rollback on failed first-principal commit,
      revoked-principal migration backfill, truthful OpenAPI/health,
      post-publication settings cleanup, live settings status, accessible async
      status, and complete self-contained .NET runtime-pack inventory.
- [x] Run exactly three bounded antagonistic reviews of the ready executable
      branch, repair all P0-P2 correctness/security/privacy/maintainability
      findings, and run focused verification for those repairs.
- [x] Obtain bounded read-only closure from the same three reviewers on the
      exact repair head; do not add a fourth reviewer or consume the full gate.
- [ ] Freeze one exact candidate and run the complete applicable
      local/native/server/target-client/private-server Phase 7 matrix once.
- [ ] Open a focused PR; require first-attempt hosted CI, CodeQL, and
      disposable-Windows stock-NSIS closure on the checked head, or record
      equivalent local evidence and explicitly disclose unavailable hosted
      checks.
- [ ] Merge only the reviewed green SHA, then create the separate post-Phase-7
      ownership/maintainability checkpoint before Phase 8.

## Focused verification during development

- Python auth/config/repository/request/job tests through the locked Python 3.12
  `uv` environment and the narrow Ruff baseline.
- Rust connector/auth-adapter/unit and server-connector integration tests with
  generated short-lived tokens; never persist test tokens.
- Migration/restart tests using disposable private directories and databases.
- Negative authorization tests that assert identical absent/cross-owner
  projections and redacted logs.
- Native adapter protocol and lifecycle tests with a fake adapter, followed by a
  disposable-Windows MSAL packaging smoke that does not require an enterprise
  login.
- A registration-independent synthetic issuer/JWKS integration gate with two
  principals and real asymmetric signatures. It proves the resource-server and
  ownership boundary, not Entra consent, Conditional Access, WAM, or a final
  production audience.

The complete matrix is reserved for the frozen candidate. Focused tests may run
repeatedly while implementation is changing.

The accepted-review repair head passed the narrow Ruff baseline, 25 focused
server authorization/health/OpenAPI/owner-flow tests, 129 connector tests plus
the final access-denied state check, 17 desktop migration tests, 31 ledger
tests, 35 drain tests, the self-contained broker publish/protocol smoke,
TypeScript compilation, 16 focused settings/accessibility tests, exact
dependency inventory (88 JavaScript, 296 Rust, 10 .NET packages, 224 notice
documents), and all 59 release-contract tests. This is development evidence,
not the reserved complete Phase 7 matrix.

## IT, security, privacy, and deployment handoffs

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
