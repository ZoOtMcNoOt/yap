# Integrated identity and access gate

Use this gate for the complete identity-and-access delivery candidate. Its
behavior identity is `integrated-identity-access`. It is separate from the
historical Phase 6 gate and the earlier whole-product checkpoint, so neither
their admissions nor their pass receipts can be relabeled or reused.

**Current status:** candidate
`134ec08002aeb1deca83547d511528b282966731` is consumed. Its fresh private
children validated, but its one complete matrix exposed a Windows command-tree
cleanup race in `frontend.release-contracts`: post-hoc `taskkill /T` exceeded
its own bound and masked the typed output-limit failure. The replacement
working tree owns every Windows command from suspended creation through a
nested kill-on-close Job Object, requires signaled root exit plus authoritative
zero-active-process Job accounting before settlement, and is focused-green.
Its same-three review closed with no P0–P2 findings and the post-review complete
release-contract cell passed 80/80. A new exact head and admission, fresh
private evidence, the one complete replacement matrix, first-attempt hosted
closure, the focused PR, and merge remain open.

The authoritative manifest is
[`verification/integrated-identity-access-gate.json`](../../verification/integrated-identity-access-gate.json).
It retains the complete frontend, native, server, target-client, GB10, and
desktop-to-private-server matrix. The local inventory includes the
receipt-backed mock-OIDC owner flow, and hosted closure includes the dedicated
`mock-oidc` job. No production desktop-provider job is listed because no
production provider is selected or shipped.

## Evidence boundary

Repository tests prove the provider-neutral OIDC discovery/JWKS boundary, Entra
tenant/audience/client/scope/role policy, tenant-specific principal IDs,
durable access disable/restore, purpose enforcement, redacted audit behavior,
cross-owner isolation, restart behavior, protected readiness, and desktop
connector fencing. Authenticated private WebSocket admission shares the REST
principal policy and rechecks revocation. The executable private topology still
uses separate loopback listeners—REST `18765` and live `18766`; no production
same-origin HTTPS/WSS edge or discovery mechanism exists. The private GB10 and
connected-server receipts continue to qualify the physical ASR lifecycle
through the development access mode.

That is not evidence of real enterprise enrollment. Entra application
registrations, tenant policy, assignment/consent, test principals, certificates,
DNS, ZPA policy, and production identity-store operations remain explicit IT
inputs. Do not substitute developer-created infrastructure or claim that this
gate proves those controls.

The desktop currently has a narrow native access-token-provider interface but
production installs no provider and fails closed. No MSAL.NET/WAM helper or
protected production cache is shipped. Adapter selection, tenant enrollment,
and real-provider evidence are governed by the
[Entra identity conformance handoff](entra-identity-conformance-handoff.md).

Private audio, transcript text, host paths, raw metrics, process ledgers,
tokens, command output, and receipts must remain outside Git. Only public-safe
hashes, counts, and pass/fail status may be reconciled into documentation after
independent receipt validation.

## Sole candidate attempt

Select and prove the mock-OIDC executor **before** reserving the candidate.
`test-mock-oidc-owner-flow.ps1` requires PowerShell 7.4+ Core, Docker with a
reachable daemon and pinned-GHCR-image pull access, Python 3.12, and an `uv`
cache that can complete the script's offline locked exact sync. Resolving the
command names on the admission workstation is not evidence that another
executor has them. Before reservation, verify the selected checkout is exact
and clean, then run the complete harness in no-receipt mode by omitting both
`CheckedHead` and `ReceiptOutput`. Require its pass marker and verified
teardown. No transferable receipt may be produced during pre-admission.

If the workstation does not have Docker, use a Docker-capable exact-clean
Linux executor and copy only its bounded receipt to the new path frozen in the
private plan. A hash-verified portable PowerShell archive may be prepared
privately on that executor; it is gate tooling, not a Yap runtime dependency.
Do not discover a missing executor dependency after admission and then retry
the same checked head.

On the exact clean Windows admission workstation, qualify the checked-head
command supervisor before reservation:

```powershell
node --test `
  .\desktop\tests\scripts\release-contract\bounded-command-windows-job.contract.mjs `
  .\desktop\tests\scripts\release-contract\windows-command-job-protocol.contract.mjs `
  .\desktop\tests\scripts\release-contract\windows-command-supervisor-watchdog.contract.mjs
```

Require all ten contracts to pass. They prove invocation-bound atomic status
validation, pre-assignment cleanup semantics, typed primary-error preservation,
private-file cleanup, launch-spec and immutable supervisor-source integrity
before execution, bounded watchdog settlement with late-status cleanup,
retained-descendant rejection and cleanup, nested outer/inner Job ownership,
and batch-command argument/exact-environment/byte fidelity. The supervisor
creates the target suspended, assigns and verifies the inner Job before resume,
and accepts post-assignment cleanup proof only after the retained root handle
signals and `QueryInformationJobObject` reports zero active processes.
Completion-port notifications are not used as proof because Windows does not
guarantee their delivery. This is release-gate process
ownership, not a return to the retired custom installer boundary. The earlier
implementation remains recoverable on
`archive/phase3-contained-process-pre-lean-20260713`.

Qualify the connected-server executor from the same non-login SSH shape used
by the admitted controller. The private wrapper must receive an explicit
absolute `YAP_UV_EXECUTABLE` plus its byte length, SHA-256, and exact version
output. The wrapper forwards the checked-head
`infra/yap-server-node/checked-uv-executor.py` as `YAP_UV_BINARY`. Every actual
`uv` invocation rejects an unexpected or over-limit size, copies and hashes the
configured file once within that frozen bound, seals that exact in-memory image
against mutation, verifies its version from the sealed image, and executes the
same image by file descriptor. The wrapper records the observed size and digest
reported by that helper rather than restating unobserved input.
Resolving `uv` only from an interactive shell is not evidence. Verify the
private wrapper's exact hash, the configured `uv` identity, the clean release,
and absent run roots and owners before reservation.

Start from the exact clean reviewed candidate. Push that exact candidate branch
without opening the pull request so GitHub can address the commit. Use a
dedicated `GH_TOKEN` limited to commit-status read/write for admission. Prepare
a new private plan for that head with new absent evidence destinations outside
the repository. Runtime preparation receipts and every private result must also
bind to that head.

The identity gate requires private-plan schema version 2 and a new absolute
`mockOidc.receiptFile` outside the repository. Like every other admitted
destination, that file must not exist at admission.

Admission creates one GitHub commit status whose normalized context binds the
gate ID and manifest hash and whose description contains only the SHA-256 of
the private reservation claim. GitHub commit-status history is the authority;
the private path never leaves the machine. The runner pins `github.com`,
repository `mcnatg1/yap`, and immutable repository ID `1278708785`; neither
`GH_HOST` nor mutable Git remote configuration selects the authority. It lists
every status page,
refuses an existing context, and records the oldest status ID. Completion
re-lists and re-elects that oldest ID before running any command cell, so
changing the local profile, evidence root, or cached reservation cannot create
another executable attempt. GitHub credential variables are removed from every
command-cell environment after that validation. GitHub documents commit statuses as create/list
history with case-insensitive contexts; see the
[commit-status API](https://docs.github.com/en/rest/commits/statuses).

```powershell
$candidateHead = (git rev-parse HEAD).Trim()
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head $candidateHead `
  --evidence-root <existing-private-gate-root> `
  --manifest .\verification\integrated-identity-access-gate.json `
  --private-plan <new-private-plan.json>
```

After admission, populate the admitted `mockOidc.receiptFile` on a
Docker-capable exact-clean candidate executor only through the bounded harness:

```powershell
.\verification\test-mock-oidc-owner-flow.ps1 `
  -CheckedHead $candidateHead `
  -ReceiptOutput <absolute-new-mock-oidc-receipt.json>
```

The harness writes at most 4 KiB only after the owner flow passes and container,
network, child-process, loopback-port, cancellation-handler, and state-directory
teardown is verified. The receipt contains only the checked head, locked image
digest, validator/owner-flow source hashes, and public-safe teardown facts; it
contains no token, log, container ID, or private path. The current working tree
has 8/8 focused harness tests, including executable fake-Docker lifecycle,
loopback forwarding, overload-rejection, exact-readiness, and port-release
regressions, plus the focused workflow, integrated-gate, and Windows Job
supervisor contracts. The replacement working tree passed the complete
release-contract cell 80/80 after the final ten-contract integrity split and
same-three repair closure. On Linux,
the provider remains on an egress-blocked internal bridge and a bounded Python
3.12 child exposes only numeric IPv4 loopback; Windows and macOS retain
Docker's loopback-only publish path. The Docker 29 ARM64 diagnostic proves the
Linux internal-bridge topology, but it is not an exact-head owner-flow receipt.
That admitted receipt and the hosted `mock-oidc` first-attempt result must still
be collected on the final reviewed head.

Populate the admitted destinations through the approved target-client, GB10,
connected-server, mock-OIDC, and teardown controllers. Then invoke completion
exactly once. Completion runs every command cell and accepts every private child
only when its receipt matches the frozen plan:

```powershell
node .\verification\integrated-gate-runner.mjs complete `
  --admission <private-admission.json> `
  --attempt-token <admitted-token> `
  --manifest .\verification\integrated-identity-access-gate.json
```

Validate the candidate receipt independently:

```powershell
$admissionSha256 = (
  Get-FileHash -Algorithm SHA256 -LiteralPath <private-admission.json>
).Hash.ToLowerInvariant()
node .\verification\integrated-gate-receipt.mjs validate `
  --manifest .\verification\integrated-identity-access-gate.json `
  --receipt <private-candidate-receipt.json> `
  --scope candidate `
  --checked-head $candidateHead `
  --admission-sha256 $admissionSha256
```

Any command or private-child failure consumes this candidate attempt. Any
executable, test, workflow, manifest, verification-tool, or private-plan change
requires a new clean head and new admission. Do not rerun a failed matrix on the
same candidate.

## Hosted closure

Push the checked candidate and open its focused pull request only after the
candidate receipt validates. Hosted CI—including the `mock-oidc` job—CodeQL,
and the disposable-Windows NSIS job must all pass on the exact final reviewed
head on their first attempt. A documentation-only descendant may reconcile
public-safe evidence; any other change requires a new candidate gate.

Remove the admission token after candidate completion. For hosted closure, set
`GH_TOKEN` to a separate read-only credential limited to commit-status read and
Actions read. Hosted collection pins `github.com/mcnatg1/yap`; it does not use
the mutable Git remote or `GH_HOST`.

Derive the hosted receipt from the original candidate admission:

```powershell
$candidateAdmissionPath = '<private-admission.json>'
$candidateHead = [string](
  Get-Content -LiteralPath $candidateAdmissionPath -Raw | ConvertFrom-Json
).checkedHead
$hostedHead = (git rev-parse HEAD).Trim()
node .\verification\integrated-hosted-closure.mjs `
  --checked-head $hostedHead `
  --candidate-admission $candidateAdmissionPath `
  --output <new-private-hosted-closure-receipt.json>
```

Validate the hosted receipt against the same behavior identity and original
candidate lineage before recording closure or merging:

```powershell
$admissionSha256 = (
  Get-FileHash -Algorithm SHA256 -LiteralPath $candidateAdmissionPath
).Hash.ToLowerInvariant()
$candidateReceiptSha256 = (
  Get-FileHash -Algorithm SHA256 -LiteralPath <private-candidate-receipt.json>
).Hash.ToLowerInvariant()
node .\verification\integrated-gate-receipt.mjs validate `
  --manifest .\verification\integrated-identity-access-gate.json `
  --receipt <new-private-hosted-closure-receipt.json> `
  --scope hosted-closure `
  --checked-head $hostedHead `
  --candidate-head $candidateHead `
  --candidate-receipt-sha256 $candidateReceiptSha256 `
  --admission-sha256 $admissionSha256
```

Do not add a broker, C# inventory, or post-merge language claim to this gate
until an approved production native provider exists and its separately
reviewed adapter contract requires them.
