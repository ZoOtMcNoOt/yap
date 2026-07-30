# Tenant-scoped identity and job authorization plan

**Status:** Active on `feat/phase7-identity-access`.

**Branch:** `feat/phase7-identity-access`

**Base:** Reviewed post-Phase-6 checkpoint merge
`15f9c8ac00211b9d2f28845d419258ae2c8de8e4`.

**Current closure state:** The original Phase 7 implementation and exactly-three
review closure exist. Candidates
`134ec08002aeb1deca83547d511528b282966731`,
`7046d98d61fec90d4c639e92aff09ff8f6a2083a`,
`dae316ceab60fe395a1899290ca184148f0e9b27`,
`e6fcabd0f77a604092997839e45e6cada09304f9`,
`59267c46a60ab9bb77494fc03d5666c1d1471f98`, and
`2bd43b33638685ff2caccd7fdcf01c157a229c45` are consumed. The first candidate's
fresh private children validated, but its one complete matrix exposed a
post-hoc Windows `taskkill /T` timeout in the release-contract command limiter.
The replacement uses suspended creation, nested Job assignment, kill-on-close,
and authoritative Job accounting-zero proof. The second candidate passed all
13 fresh private children, then its one complete matrix exposed that the new
supervisor declared PowerShell 7.4 without also requiring the Core edition.
Follow-up runtime review then proved that dynamically created script blocks do
not enforce `#requires`. The corrected encoded-command boundary checks both
Core edition and version 7.4 before creating the loader script block. Thirteen
focused Windows/installer contracts and the 81-case release-contract cell
passed on that consumed encoded-loader supervisor identity, and same-three
closure found no P0–P2 issue. The third
candidate passed Windows, mock-OIDC, target-client, and GB10 qualification, but
the private connected-server readiness poll called `String.Contains` on its
initially empty redirected stdout file and failed before WDIO. Graceful remote
cleanup and independent zero-owner checks passed. That infrastructure failure
consumes the candidate. The fourth candidate passed Windows, mock-OIDC,
target-client, GB10, and connected WDIO. Its wrapper emitted cleanup PASS and
independent local and remote zero-owner checks passed, but the directly owned
SSH process returned `1` rather than the controller's required `143`. The
wrapper's old PASS marker did not prove whether its TERM trigger remained
authoritative or one cleanup helper had changed the final status, so the
candidate is consumed. The fifth candidate's admitted Linux mock-OIDC flow
passed, but the receipt inherited mode `0664` instead of the required
owner-only private-evidence boundary, so that private child consumes the
candidate. The sixth candidate passed all 13 private children and the complete
matrix through strict Clippy. Every Rust test then passed, but the Cargo root
exited while the Windows Job remained nonzero beyond the former
250-millisecond natural-drain allowance. The supervisor terminated the Job and
consumed the candidate. Its private failure did not preserve the lingering PID,
so this plan does not attribute the race to a particular Rust test or process.

Exact head `2f8b127fe20ec3cb1d62879532f20e3e220c4ca6` was admitted but
withdrawn before GB10, connected-server, or complete-matrix execution.
Pre-execution adversarial review rejected its unbounded command cells, ambient
SSH alias and mutable remote-helper trust, terminal-carried attempt secret, and
incomplete Windows private-artifact boundary. No passing evidence from that
head is replacement evidence. Exact head
`a7df6bfa0511ddd1ca59d7e1389a6c17eb133ebe` was later admitted; mock OIDC and
target-client passed, but GB10 failed before creating a remote owner because
the fixed controller parent was absent. Successor
`30b18c8c4a26266210657d11cf66b1a5e0c2a893` was not admitted after its
pre-reservation causal test exposed legitimate empty-stream binder failures.

Exact head `3f9a8b7195dad3afd8b66034349c0482caef0a4a` repaired those binders,
passed admission review and all fresh private children, then consumed its sole
complete matrix in a stale release contract: the inventory did not encode the
one intentional system Windows PowerShell 5.1 DACL-host exception. Head
`4dc572f120f7e284f7453dfd11bd817a2c034104` fixed only that inventory and
documentation contract. It was freshly packaged and prequalified but was
never admitted. Connected-path review exposed a fork-before-exec interval in
which `/proc/<pid>/environ` could not yet prove the runtime token, and the
then-current cancellation fallback could return without signalling the exact
pending child. Runtime and assurance review therefore rejected `4dc572f` as a
NO-GO before any admitted evidence or complete matrix.

Committed and pushed head
`9defb4a2202b5743f161dafb40f8fb2bc41b8fde` retained the reviewed Windows Job
boundary and replaced the Linux initial-launch inference with one
function-named supervisor under system Python 3.12. It forks the target behind
an explicit release barrier, immediately retains a pidfd, publishes immutable
PID/start-time identity, releases `exec`, and reaps the exact child through
`waitid(P_PIDFD)`. Explicit `STOP`, controller loss, deadline expiry, and exec
failure remain bounded; numeric PID signals are forbidden, and process-group
signals are allowed only after the retained leader and every live token-owned
member are reverified. The resident provider launchers, resource sampler, and
loopback proxy use this same lifecycle owner.

Fresh prequalification of `9defb4a...` passed the unaffected focused controller
and lifecycle checks, then failed before connected provider startup because the
proxy rejected the stock GB10 `/usr/bin/socat -> /usr/bin/socat1` package link.
That committed head is preserved as rejected pre-admission evidence; it has no
admitted receipt or complete matrix. The corrected successor canonicalizes the
PATH-selected `socat` command with GNU `readlink -f`, then requires the captured
target to be absolute, regular, and executable before container mutation. All
14 focused proxy contracts, the real root-owned GB10 target proof, and exact
architecture/runtime/assurance re-review passed with no P0–P2 finding. That
proof remains in the later consumed lineages described below; it is not current
merge authority. The later `9446730...` lineage completed that private and
candidate evidence before exposing a workflow-parse defect during hosted
closure, as recorded below. Its narrow workflow successor and subsequent
target-client repair are also recorded below; final exact-tree admission, the
first valid hosted closure, PR update, and merge remain open.

Later admitted heads `c4df39f305f739d3eb2987f24ba8387e54627902`,
`7f047c6a1a2838f70908a7c0f5ee106fd84d5fb2`,
`c5d826ffb85a841e412e41155a3c6c82a2fbe3e4`, and
`dece4265e052d775d2d11f1883cd8cc4b2b25191` are consumed. The first exposed a
private mock-OIDC receipt-publication parser defect. The second passed mock
OIDC but failed target-client qualification because an equivalent canonical
language-routing save retired the warm model. `c5d826f...` fixed that runtime
no-op, passed focused verification, three-lens exact-head review, all private
prequalification, and GitHub-backed admission. Its first admitted controller
failed before starting mock OIDC because orchestration incorrectly required
the fixed `/srv/yap-server/private` ancestor itself to be mode `0700`.
Readback proved it was a real admin-owned, non-group/world-writable `0755`
directory; the receipt parent, per-head child, receipt, container, and network
were absent. `dece426...` corrected that ancestry rule, passed focused
verification, three-lens exact-head review, complete private prequalification,
and GitHub-backed admission. Its first admitted mock-OIDC controller then
failed before the locked `uv sync` command or owner flow because the
non-interactive SSH `PATH` did not expose the reviewed absolute `uv` executable
to portable PowerShell. The mode-`0700` per-head directory existed, but the
receipt remained absent and no runtime owner started. The following exact head
therefore had to retain the safe owner-only receipt boundary, authenticate
every real component of the selected absolute `uv` path plus the executable,
and prove that the identical non-interactive admitted invocation resolved it
before reservation.

Exact head `63600096cd8afe9f4435f6302c584f89dbdb5915` satisfied that `uv`
boundary, passed the same three review lenses, complete private
prequalification, GitHub-backed admission, all four admitted private
controllers, and independent validation of all 13 private receipt children.
Its one complete matrix failed in `frontend.release-contracts` because the
installed `@floating-ui/core@1.7.5` notice was a Windows reparse point; that
failure consumed the head.
The exact lockfile, generated inventory, and MIT notice hash were already
correct; the private checkout's default pnpm hardlink shared a reparse-tagged
inode with the content store and another OneDrive-managed checkout. Exact head
`d4adc832da90ef5a65ca8e6a9d702d833e55dbe8` corrected that materialization,
passed the same review, prequalification, admission, and 13-child private
boundary, and reached `native.tests` in its one complete matrix. Every Rust test
passed, but Visual Studio Build Tools retained its `vctip.exe` diagnostic helper
inside the owned Windows Job, so the supervisor failed closed and consumed the
head.
The approved Build Tools `OptIn=0` change was applied and read back, but a clean
default-MSVC link still launched Microsoft's signed `VCTIP.EXE` from
`link.exe` and retained it beyond the five-second drain. Microsoft documents
that VSCEIP opt-out disables optional diagnostics while required diagnostics
remain unaffected. The successor therefore keeps strict Job containment for
Yap runtime and ordinary candidate commands, requires the fail-closed
optional-diagnostics registry preflight locally, and runs native compile/link
evidence on the exact reviewed head in fresh GitHub-hosted Windows VMs.

Exact head `944673071804d8178776efa1d1e13651c87df6fb` passed the same
three review lenses, complete private prequalification, GitHub-backed
admission, all four admitted private controllers, independent validation of all
13 private receipt children, and its one complete 25-cell matrix. PR #69 opened
on that exact head. GitHub then rejected its first CI dispatch during workflow
parsing, before any job or runner started, because job-level `env` evaluated
`${{ runner.environment }}` before runner assignment. Under the exact-head
rule, that workflow-authoring defect consumes the head as merge authority
without changing or relabeling its private results. Its protected private
package and receipts remain historical evidence.

Exact workflow successor `cafbe307e7203e09050fdbe2eb080d5d84b65026`
step-scoped the runner binding and added the job-level-context regression
contract. It passed focused verification and the same three review lenses and
is preserved at `origin/phase7-admission-cafbe307`. Its fresh target-client
controller then exposed a real local-start defect before the complete matrix:
the 1,024-frame pending-ASR queue saturated during cold model warmup, 11
local-ASR frames dropped, and adapter stop reached its 12-second bound. The
recording consumer itself reported zero drops. That private failure remains
immutable and consumes `cafbe307...` as merge authority.

Exact repair `32cf52891c277a4a3d47aa9fb3cab105ca58af98` retains independent
recording ownership and replaces one-frame, real-time-speed forwarding with
bounded FIFO batches so accepted pre-roll catches up after adapter start.
Focused Rust runtime tests passed 93/93, strict Clippy and format passed, the
prepared-audio validator passed, and the same three read-only review lenses
reported no P0–P2 finding. Fresh private qualification then passed all 12
repeated resource sessions, all nine 250-ms-through-30-second prepared-audio
cases, and the 30-second physical-microphone/rendered-UI lifecycle with zero
audio drops. The first resource attempt is preserved as a failed environmental
measurement because one of 2,936 scheduler probes woke at 300.172 ms against
the frozen 250-ms maximum during cycle 11; that cycle's p99 was 0.816 ms, all
3,000 frames arrived, and the identical fresh rerun passed with a 9.525-ms
maximum. No complete Phase 7 matrix or hosted closure is claimed for this
repair yet.

Exact documentation successor `dc6359162fb16909d38f410cdb75c2729d83972f`
then passed its one complete private 25-cell matrix and independent receipt
validation. All four CodeQL analyses passed. Hosted CI run `30574652702`
nevertheless consumed that exact head:
the Linux pre-install executable-bit probe loaded the `yaml` package before
dependency materialization, GitHub Windows temp artifacts reported an owner
different from the current runner identity, and two checkout contracts
compared the equivalent `RUNNER~1` and `runneradmin` path spellings as
different strings. Those three causes account for every failed hosted job.
Stock NSIS was not dispatched after CI failed.

Reviewed portability repair
`558fed05e0f959a28fbe4d92499bbe185b0532d6` lazily loads workflow YAML only
for tests that inspect workflows, corrects a mismatched Windows owner in the
same descriptor as the protected private DACL, and confines canonical
path-identity comparison to checkout tests. Pre-admission preparation of exact
descendant `c95cfe02a4a1df81dfc4aaed58ac15f61247c4f4` then exposed that an
unnecessary same-owner rewrite could require elevation under inherited
development-root ACLs. No admission capability was created and no matrix cell
ran for that head. Repair `a823b28...` writes the owner only when the observed
SID differs from the current identity and retains the exact post-write
owner/DACL verification. The three Windows ACL behaviors, all 16 applicable
hosted-portability contracts, and the clean-tree admission fixture pass. The
same three independent architecture, assurance, and runtime lenses report no
P0–P2 finding. A fresh exact-tree package/prequalification/admission, one
complete replacement matrix, and exact-head hosted closure remain required;
none of `dc635916...`'s private evidence may be retried or relabeled.

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
- [x] Correct the stale tracked-PowerShell inventory by naming the one pinned
      system Windows PowerShell 5.1 ACL-host exception while retaining the
      PowerShell Core 7.4 requirement for every other tracked entrypoint.
- [x] Replace fork-before-exec token inference in the Linux resident-provider
      lifecycle with retained-pidfd supervision, migrate every affected
      launcher/proxy/sampler owner, and close the exact working tree through the
      same architecture, runtime, and assurance review lenses.
      The working-tree successor now uses `/usr/bin/python3.12 -I -S`, an
      exclusive regular-file output boundary, a release barrier, retained
      pidfd, contained control writes, bounded pidfd/setup failure, and exact
      reap. Post-reap proof failures remain latched, and denied zombie
      environment reads require causal identity recheck. Missing/failed results
      can recover only after the direct supervisor exits and every surviving
      group member verifies the run token. The proxy bounds Docker calls below
      the outer supervisor deadline, splits Docker create from start, and writes
      an exclusive container-ID file plus a private pre-create recovery record.
      It reconciles fixed name, immutable container ID, and run token before
      stopping/removing only that verified container. Unknown interrupted
      creation retains recovery identity and fails instead of treating timed
      absence as proof. Recovery retires only after direct immutable-ID absence;
      renamed or relabeled state is retained and refused. Deletion failure is
      propagated, and normal gate teardown independently requires all three
      recovery artifacts absent before clearing their path. Docker auto-removal
      is disabled so bounded logs are captured before exact-ID removal. It has
      no raw numeric-PID log follower. Causal owned/foreign recovery,
      closed-pipe, FIFO, ambient-site, repeated exec-failure, post-reap,
      missing-result, sampler-handle, delayed-create, retained-recovery,
      renamed-container, created-container, normal-exit log ordering, and
      hung-probe tests execute. The same architecture, runtime, and assurance
      reviewers returned GO on that exact repair tree with no P0-P2 finding.
- [x] Preserve and push the retained-pidfd successor as
      `9defb4a2202b5743f161dafb40f8fb2bc41b8fde`, reject it before admission when
      connected prequalification exposes the stock GB10 `socat` package-link
      incompatibility, and retain its private outputs only as failed
      prequalification evidence.
- [x] Canonicalize the PATH-selected `socat` command to its absolute regular
      executable before container mutation. Prove the synthetic package-link
      layout, all 14 focused proxy contracts, and the actual
      `/usr/bin/socat -> /usr/bin/socat1` root-owned GB10 target, then obtain
      GO from the same architecture, runtime, and assurance reviewers with no
      P0–P2 finding.
- [x] Freeze, push, package, prequalify, and admit the canonical-`socat`
      successor lineage through `c5d826f...`; preserve the first three consumed
      admissions and their private evidence without retry or relabeling.
- [x] Freeze, push, package, prequalify, and admit `dece426...`, which accepts a
      safe admin/root-owned, non-group/world-writable mock-OIDC receipt ancestor
      while requiring the receipt parent and per-head child to be mode `0700`
      and the receipt to be mode `0600`. Preserve its failed first-child
      evidence without retry or completion: the admitted non-interactive
      controller did not resolve the reviewed `uv` executable.
- [x] Freeze, push, package, prequalify, and admit `63600096...`, which retains
      the corrected receipt
      ancestry, authenticates every real directory component plus the
      executable in the selected absolute `uv` path, and proves the identical
      non-interactive admitted invocation resolves that exact path inside the
      pinned portable PowerShell process. Preserve its passing 13 private
      receipt children and failed one-shot release-contract cell without retry,
      completion, or relabeling.
- [x] Freeze and push `d4adc832...`, whose active dependency cell requires
      `--force`, `--no-optimistic-repeat-install`, and
      `--package-import-method=copy`; begin from an absent private
      `desktop/node_modules`, hydrate it with those options, run the complete
      release-contract cell before reservation, then freshly package,
      prequalify, and admit it once. Preserve its passing 13 private receipt
      children and failed one-shot native-test containment cell without retry,
      completion, or relabeling: Visual Studio Build Tools retained its
      `vctip.exe` diagnostic helper after every Rust test passed.
- [x] Require the admission workstation to pass the read-only Build Tools
      optional-diagnostics registry preflight before reservation and again in
      the candidate manifest. The reader now roots helper resolution in the
      kernel object-manager SystemRoot and rejects conflicting environment
      roots before launch. Require all five CI closure jobs to explicitly check
      out the reviewed head without persisted credentials and verify it before
      and after execution on the declared fresh hosted OS. Use an absolute
      no-space System32 bootstrap for the absolute Windows PowerShell host and
      launch the absolute Linux host directly. Capture deterministic PowerShell
      and Git executable identities, the exact guard source, the Git index, and
      an index-independent tracked-content manifest during initial admission.
      Final verification must reuse that shell chain, replay the verified guard
      bytes in memory, reject hidden index state and linked tracked ancestors,
      force Linux executable-bit comparison, rehash tracked content, and reuse
      the admitted Git identity rather than resolving a mutable workspace helper
      or post-project `PATH`. Bind native
      formatting, Clippy, compilation, tests, dependency checks, and WDIO build
      to the existing `rust` and `Native WDIO smoke (required, no hardware)`
      `windows-latest` jobs. Keep connector and required WDIO runtime trees in
      kill-on-close Jobs, prepopulate the locked Python environment, strip
      GitHub credentials, verify the embedded WDIO build SHA, and require
      active-process-zero evidence. Reject self-hosted or wrong-OS
      substitution.
- [x] After focused verification and same-three exact-tree review, freeze,
      push, package, prequalify, and admit exact successor `9446730...`.
- [x] Run all four admitted private controllers, independently validate the 13
      private receipt children, and run the complete 25-cell candidate matrix
      exactly once for `9446730...`; open focused PR #69 only after those
      results passed.
- [x] Preserve `9446730...` without retry, completion, or relabeling after
      GitHub rejected its first CI dispatch before job creation because
      job-level `env` referenced `runner.environment` before runner assignment.
- [x] Move the runner-owner binding onto only the three contained-runtime
      steps and add a release contract forbidding `runner.*` in job-level
      environments. Preserve admitted `cafbe307...` after its fresh
      target-client controller exposed bounded pending-ASR saturation; do not
      relabel or reuse that private evidence.
- [x] Implement bounded batched pre-roll catch-up at `32cf528...`, pass focused
      runtime/validator verification and same-three exact-tree review, and pass
      fresh repeated-resource, nine-case prepared-audio, and physical
      microphone/rendered-UI qualification while preserving the first isolated
      scheduler-outlier attempt as failed evidence.
- [x] Commit documentation-reconciled descendant
      `e019036184398833ebfd5fef25aa9e0148fadc49`.
- [x] Obtain final same-three exact-tree closure, freeze, package, prequalify,
      and admit exact successor `dc635916...`; run its complete 25-cell matrix
      exactly once and independently validate its private receipt.
- [x] Preserve `dc635916...` without retry or relabeling after all four CodeQL
      analyses passed but hosted CI run `30574652702` exposed the pre-install
      YAML import, Windows temp-owner mismatch, and equivalent
      8.3/long-path spelling assumptions. Do not dispatch NSIS for that failed
      head.
- [x] Implement portability repair `558fed0...`, pass focused checkout,
      private-artifact, server-output, and SSH-profile contracts, obtain the
      same three independent review approvals, and reconcile the resulting
      evidence and IT boundary in current documents.
- [x] Preserve pre-admission descendant `c95cfe0...` without claiming a
      consumed attempt after ordinary development-root ACLs exposed the
      redundant same-owner write. Implement `a823b28...`, retain mismatch-owner
      correction plus exact read-back, pass focused ACL/hosted/admission
      contracts, and obtain the same three independent review approvals.
- [ ] Freeze, push, package, prequalify, and admit the resulting exact
      documentation successor.
- [ ] Run the complete applicable local/server/target-client/private-server
      replacement matrix exactly once for that admitted successor.
- [ ] Update PR #69; require the five exact-head CI cells, CodeQL, and
      disposable-Windows stock-NSIS closure exactly once on the checked head,
      or record equivalent local evidence and explicitly disclose unavailable
      hosted checks.
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
- The same `ubuntu-latest` `mock-oidc` job runs the Linux supervisor,
  resident-lifecycle, and proxy behavior modules with
  `YAP_REQUIRE_LINUX_LIFECYCLE_TESTS=1`; an unavailable Linux process model is
  a hosted failure rather than a successful skip.

The complete matrix is reserved for the frozen candidate. Focused tests may run
repeatedly while implementation is changing.

The focused identity implementation and original exactly-three review closure
are complete. The mock-OIDC harness suite is 8/8 green. The replacement Windows
command boundary has a twelve-case functional contract covering
invocation-bound status, pre-assignment cleanup, typed-error preservation,
private-file cleanup, launch and immutable supervisor-source integrity, bounded
watchdog settlement, causal natural descendant drain, retained descendants,
nested Jobs, and batch-command and exact-environment fidelity. After the second
consumed candidate exposed the missing
`#requires -PSEdition Core` declaration, follow-up runtime review proved that
dynamic script blocks ignore `#requires`. The corrected encoded-command
boundary passed 13 focused Windows/installer contracts and the complete
affected release-contract cell 81/81 with no same-three P0–P2 finding. That
count remains historical evidence for the consumed supervisor identity. The
current natural-drain replacement passes the causal paired contract three
consecutive times, the new 14 focused Windows/installer contracts, the affected
release-contract cell 82/82 under nested Job ownership, and the exact Cargo
cell under the repaired supervisor. This remains focused evidence, not a rerun
of the consumed complete phase matrix. A Docker 29 ARM64
diagnostic
proved the bounded Linux loopback proxy against the locked provider on an
internal bridge, but it did not produce an exact-head owner-flow receipt.
The later `4dc572f` prequalification was rejected before admission because
`/proc/<pid>/environ` is not an initial fork-to-exec ownership authority.
Focused successor tests now exercise retained-pidfd pre-exec cancellation,
one monotonic five-second ownership deadline, controller death, complete
descendant teardown, natural exit, contaminated pending-child rejection, and
an unowned sentinel negative case. They also exercise the migrated resident
launcher, sampler, and loopback-proxy contracts. Committed successor
`9defb4a...` preserved that repair but failed connected prequalification before
provider startup because it rejected GB10's system `socat` package link. The
corrected successor passes the synthetic link replay, all 14 focused proxy
contracts, and the actual canonical/root-owned GB10 executable proof, with
three-lens GO and no P0–P2 finding. These are focused development results, not
the reserved complete Phase 7 matrix or hosted first-attempt evidence.

The consumed `d4adc832...` prequalification also exercised the private
connected-server controller against absent and zero-length redirected stdout
files. Both states remained ordinary not-ready observations rather than
`$null` method calls, and that no-server preflight finished before admission.

The remote wrapper must emit cleanup PASS only when its trigger status is the
expected TERM result, every checked process-group helper succeeds, and final
owner inspection is empty. Before admission, exercise one exact connected
request followed by the bounded stop control and independently verify the
wrapper marker, Windows SSH exit interpretation, and zero local and remote
owners. Exit `1` may be normalized only when the strengthened wrapper emitted
exactly one PASS marker, wrote no cleanup error, and the independent teardown
checks pass.

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
