# Integrated identity and access gate

Use this gate for the complete identity-and-access delivery candidate. Its
behavior identity is `integrated-identity-access`. It is separate from the
historical Phase 6 gate and the earlier whole-product checkpoint, so neither
their admissions nor their pass receipts can be relabeled or reused.

**Current status:** candidates
`134ec08002aeb1deca83547d511528b282966731`,
`7046d98d61fec90d4c639e92aff09ff8f6a2083a`,
`dae316ceab60fe395a1899290ca184148f0e9b27`,
`e6fcabd0f77a604092997839e45e6cada09304f9`,
`59267c46a60ab9bb77494fc03d5666c1d1471f98`,
`2bd43b33638685ff2caccd7fdcf01c157a229c45`, and
`a7df6bfa0511ddd1ca59d7e1389a6c17eb133ebe` are consumed. The first candidate's
fresh private children validated, but its one complete matrix exposed a Windows
command-tree cleanup race in `frontend.release-contracts`: post-hoc
`taskkill /T` exceeded its own bound and masked the typed output-limit failure.
The replacement owns every Windows command from suspended creation through a
nested kill-on-close Job Object and requires signaled root exit plus
authoritative zero-active-process Job accounting before settlement. The second
candidate then passed all 13 fresh private children, but its one complete
matrix exposed a fail-fast declaration gap in that new supervisor:
`#requires -PSEdition Core` was absent. Follow-up runtime review then proved
that dynamic `ScriptBlock::Create` loading does not enforce `#requires`. The
corrected boundary checks Core edition and version 7.4 before creating the
loader script block. That consumed encoded-loader supervisor identity passed
13 focused Windows/installer contracts and its 81-case release-contract cell,
and same-three closure found no P0–P2 issue. The third candidate passed the
Windows, mock-OIDC, target-client,
and GB10 qualifications with exact teardown, but its admitted connected-server
controller called `String.Contains` on the initially empty redirected stdout
file and failed before WDIO. The remote wrapper still emitted its one cleanup
marker, and independent inspection proved zero retained local or remote owners.
That private-controller failure consumes the candidate; none of its passing
children may be relabeled. The fourth candidate passed fresh Windows,
mock-OIDC, target-client, GB10, and connected WDIO evidence. Its remote wrapper
emitted cleanup PASS and both independent zero-owner checks passed, but the
owned SSH process returned `1` rather than the required `143`. Because that
wrapper marker did not bind its TERM trigger and helper results, the teardown
status remained ambiguous and consumes the candidate. The fifth candidate's
Linux mock-OIDC flow passed, but its receipt inherited mode `0664` instead of
the required owner-only boundary; that private-child failure is preserved and
consumes the candidate. The sixth candidate passed all 13 private children and
the complete matrix through strict Clippy. Every Rust test in `native.tests`
then passed, but the Cargo root exited while the Job still reported a nonzero
process count beyond the former 250-millisecond natural-drain allowance. The
supervisor terminated the owned Job and correctly consumed the candidate. The
private failure did not preserve the lingering PID, so no particular Rust test
or process is blamed.

Exact head `2f8b127fe20ec3cb1d62879532f20e3e220c4ca6` was then admitted but
withdrawn before GB10, connected-server, or complete-matrix execution.
Pre-execution adversarial review found that command cells had no frozen
wall-clock deadline, the connected path still trusted an ambient SSH alias and
mutable remote helpers, the one-attempt secret crossed terminal/argument
boundaries, and Windows private artifacts did not verify a protected DACL.
Passing child evidence collected for that head is not replacement-candidate
evidence and must not be relabeled.

Exact head `a7df6bfa0511ddd1ca59d7e1389a6c17eb133ebe` was admitted and its fresh
mock-OIDC and target-client children passed. Its sole GB10 child then failed
before creating any remote lifecycle owner because the fixed controller parent
had not been materialized and the admitted controller attempted only the
per-head child creation. Failure handling found nothing candidate-owned to
remove, and independent cleanup proved zero retained owners. This
private-controller failure consumes the candidate; its passing children must
not be relabeled.

Successor head `30b18c8c4a26266210657d11cf66b1a5e0c2a893` was not admitted.
Its pre-reservation bounded-log causal test exposed two mandatory `byte[]`
parameter binders that rejected a legitimate zero-byte stream: first the
controller's protected-output wrapper, then the shared atomic private-file
publisher it calls. No remote owner or candidate evidence was created. Both
binders and the controller-level causal contract must accept empty byte arrays
before the next head is frozen.

The current replacement retains assigned-before-resume, kill-on-close,
immediate explicit termination, and authoritative accounting-zero proof. It
allows at most 5,000 milliseconds after a signaled root exit for already-
exiting descendants and asynchronous Job accounting to drain before returning
the typed retained-descendant failure and enforcing the separate
5,000-millisecond cleanup proof. It also freezes per-cell wall-clock deadlines,
uses a protected one-attempt capability file, verifies private Windows DACLs,
and requires one no-config SSH profile with bounded tunnel settlement. A new
working-tree three-agent review found no P0–P2 issue. A clean exact-head freeze
and match review, private-controller prequalification, admission, fresh private
evidence, the one complete replacement matrix, first-attempt hosted closure,
the focused PR, and merge remain open.

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

Materialize and prequalify the fixed GB10 controller parent beneath the already
verified private server root before reservation. It must be a real,
non-redirected directory owned by the admitted remote account and group with
mode `0700`. Reject a missing or redirected ancestor rather than recursively
creating an unverified path. The planned per-head child must remain absent
until the admitted controller owns the attempt. Exercise that exact parent
validation in the no-owner GB10 preflight so a missing executor prerequisite
cannot consume another candidate.

The admitted GB10 controller must repeat the ancestor and fixed-parent
validation immediately before a non-recursive direct-child creation. It then
verifies that child is canonical, non-redirected, owner-only, and contained
before exclusively creating and validating the nonce ownership marker.
Independent cleanup must inspect the complete checked-head transient-unit
family, not only the random unit name selected by one invocation. Every local
bounded-command log must use no-overwrite creation and pass the protected
private-file policy on success and failure; inherited parent permissions are
not sufficient.

Select and prove the mock-OIDC executor **before** reserving the candidate.
`test-mock-oidc-owner-flow.ps1` requires PowerShell 7.4+ Core, Docker with a
reachable daemon, Python 3.12, and an `uv` cache that can complete the script's
offline locked exact sync. The Docker executor must either have access to pull
the pinned GHCR index digest for its locked platform or already contain the
corresponding locked platform-manifest or config digest with the exact expected
OS and architecture. Resolving the command names or a mutable image tag on the
admission workstation is not evidence that another executor has the frozen
runtime. Before reservation, verify the selected checkout is exact and clean,
then run the complete harness in no-receipt mode by omitting both `CheckedHead`
and `ReceiptOutput`. Require its pass marker and verified teardown. No
transferable receipt may be produced during pre-admission.

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
  .\desktop\tests\scripts\release-contract\windows-command-powershell-runtime.contract.mjs `
  .\desktop\tests\scripts\release-contract\windows-command-supervisor-watchdog.contract.mjs
```

Require all twelve contracts to pass. They prove invocation-bound atomic status
validation, pre-assignment cleanup semantics, typed primary-error preservation,
private-file cleanup, launch-spec and immutable supervisor-source integrity
before execution, bounded watchdog settlement with late-status cleanup,
bounded natural descendant drain, retained-descendant rejection and cleanup,
nested outer/inner Job ownership,
batch-command argument/exact-environment/byte fidelity, and runtime-version and
edition rejection at the encoded dynamic-loader boundary. The supervisor
creates the target suspended, assigns and verifies the inner Job before resume,
and accepts post-assignment cleanup proof only after the retained root handle
signals and `QueryInformationJobObject` reports zero active processes.
After any signaled root exit, zero or nonzero, when no explicit termination
request has arrived, it allows the owned Job at most 5,000 milliseconds to
drain already-exiting descendants and asynchronous Job accounting naturally.
A nonzero count after that bound is terminated and fails as a retained
descendant, and zero must then be proven within the separate existing
5,000-millisecond forced-cleanup budget. Explicit termination and output-limit
paths bypass the natural-drain window.
Completion-port notifications are not used as proof because Windows does not
guarantee their delivery. This is release-gate process
ownership, not a return to the retired custom installer boundary. The earlier
implementation remains recoverable on
`archive/phase3-contained-process-pre-lean-20260713`.

Qualify the connected-server executor from the same non-login SSH shape used
by the admitted controller. Main, control, and tunnel SSH processes must use
the checked profile emitted by
`verification/private-server-ssh-profile.mjs`: the absolute OpenSSH
executable, fixed `admin@192.168.50.1` destination, absolute single-link
identity and known-hosts files, `-F NUL`, strict host checking, and disabled
ambient agents, forwarding, proxies, local commands, passwords, and
keyboard-interactive authentication. The tunnel profile owns exactly one
loopback forward. An SSH config alias is not admission evidence.

Before starting any remote owner, the private controller must authenticate the
exact checked-head Start, Stop, Verify, and Wrapper helpers as regular,
single-link, `admin`-owned mode-`0700` files with reviewed SHA-256 identities
and clean `bash -n` parsing. Stop and Verify are rechecked immediately before
use. The supported Windows entrypoint Job-contains the complete controller,
OpenSSH, PNPM, WDIO, desktop, and tunnel tree with a finite wall-clock and
bounded private log.

The private wrapper must receive an explicit absolute `YAP_UV_EXECUTABLE` plus
its byte length, SHA-256, and exact version output. The wrapper forwards the checked-head
`infra/yap-server-node/checked-uv-executor.py` as `YAP_UV_BINARY`. Every actual
`uv` invocation rejects an unexpected or over-limit size, copies and hashes the
configured file once within that frozen bound, seals that exact in-memory image
against mutation, verifies its version from the sealed image, and executes the
same image by file descriptor. The wrapper records the observed size and digest
reported by that helper rather than restating unobserved input.
Resolving `uv` only from an interactive shell is not evidence. Verify the
private wrapper's exact hash, the configured `uv` identity, the clean release,
and absent run roots and owners before reservation.

Also qualify the private Windows readiness controller before reservation. Its
poll must treat both an absent redirected stdout file and an existing
zero-length file as an empty string, continue polling, and never call a string
method on `$null`. Parse the complete controller under PowerShell 7.4 Core and
exercise those two no-server states without creating an admitted destination.
The controller must still launch the real admitted SSH owner with
`-NoNewWindow`, stop the exact remote wrapper through a separate bounded
control connection with live wall-clock and output limits, wait for the
original SSH process to exit naturally, and create teardown evidence only after
independent zero-owner checks. The remote wrapper must place the Yap server in
its own token-owned process group and use the checked bounded TERM/KILL group
helper; a plain unbounded `kill` followed by `wait` is not sufficient teardown
proof.

Cleanup PASS must additionally mean that the wrapper entered cleanup through
the expected TERM status, every checked child/group helper succeeded, and the
final container, listener, and network inventories are empty. A helper or
unexpected-trigger failure must emit FAIL and exit nonzero even if later
inspection finds no retained owner. Every `docker`, `ss`, Git, and process
inventory command must itself succeed before its captured output can prove
absence; command failure is not an empty inventory, and `pgrep` not-found must
be distinguished from an inventory error. Prequalify one exact connected
request and bounded stop before reservation. Windows OpenSSH exit `1` may be
normalized only when the strengthened wrapper emitted exactly one PASS marker
with an empty cleanup-error stream and the separate local-forward and remote
zero-owner checks pass; otherwise it is a consumed failure.

Start from the exact clean reviewed candidate. Push that exact candidate branch
without opening the pull request so GitHub can address the commit. Use a
dedicated `GH_TOKEN` limited to commit-status read/write for admission. Prepare
a new private plan for that head with new absent evidence destinations outside
the repository. Runtime preparation receipts and every private result must also
bind to that head.

The identity gate requires private-plan schema version 2 and a new absolute
`mockOidc.receiptFile` outside the repository. Like every other admitted
destination, that file must not exist at admission. The schema also binds the
reviewed remote start, stop, verification, and wrapper helpers as one
`integrated.remoteHelperSetSha256`:

```json
{
  "schemaVersion": 2,
  "checkedHead": "<full-lowercase-git-sha>",
  "mockOidc": {
    "receiptFile": "<new-absolute-private-mock-oidc-receipt>"
  },
  "targetClient": {
    "evidenceDirectory": "<new-absolute-private-directory>",
    "preparedAudioEvidenceFile": "<that-directory>/local-stream-short-boundaries.json",
    "preparedAudioSuiteSha256": "<frozen-suite-sha256>"
  },
  "gb10": {
    "lifecycleEvidenceFile": "<new-absolute-private-json-file>",
    "runtimePreparation": {
      "cohere-vllm": {
        "receiptFile": "<absolute-private-cohere-preparation-receipt>",
        "receiptSha256": "<frozen-receipt-sha256>"
      },
      "nemotron-nemo": {
        "receiptFile": "<absolute-private-nemotron-preparation-receipt>",
        "receiptSha256": "<frozen-receipt-sha256>"
      },
      "language-detection": {
        "receiptFile": "<absolute-private-lid-preparation-receipt>",
        "receiptSha256": "<frozen-receipt-sha256>"
      }
    }
  },
  "integrated": {
    "evidenceDirectory": "<new-absolute-private-directory>",
    "remoteCleanupLogFile": "<new-absolute-private-log-file>",
    "teardownEvidenceFile": "<that-directory>/teardown.json",
    "remoteHelperSetSha256": "<frozen-helper-set-sha256>"
  }
}
```

The reviewed private controller calculates the helper-set identity from exactly
four lowercase file SHA-256 values in fixed role order (`start`, `stop`,
`verify`, `wrapper`), using one UTF-8
`<role>=<sha256>\n` line per helper. It authenticates each remote helper as a
real, single-link, administrator-owned mode-0700 file and runs `bash -n` before
freezing that digest. The wrapper emits exactly one matching
`REMOTE_HELPER_SET_SHA256=<sha256>` line in the bounded private cleanup log.

Protect and read back every existing private input and every required parent
before admission. Do not create any named evidence destination:

```powershell
$candidateHead = (git rev-parse HEAD).Trim()
$PrivatePlanPath = (
  Resolve-Path -LiteralPath '<new-private-plan.json>'
).Path
$PrivatePlan = Get-Content -LiteralPath $PrivatePlanPath -Raw |
  ConvertFrom-Json -Depth 20
$EvidenceRoot = [IO.Path]::GetFullPath('<existing-private-gate-root>')
$PrivateArtifactHelper = (
  Resolve-Path -LiteralPath '.\verification\private-gate-artifacts.ps1'
).Path
$RuntimeReceipts = @(
  $PrivatePlan.gb10.runtimePreparation.'cohere-vllm'.receiptFile
  $PrivatePlan.gb10.runtimePreparation.'nemotron-nemo'.receiptFile
  $PrivatePlan.gb10.runtimePreparation.'language-detection'.receiptFile
)
$RequiredParents = @(
  $EvidenceRoot
  (Split-Path -Parent $PrivatePlanPath)
  (Split-Path -Parent $PrivatePlan.mockOidc.receiptFile)
  (Split-Path -Parent $PrivatePlan.targetClient.evidenceDirectory)
  (Split-Path -Parent $PrivatePlan.gb10.lifecycleEvidenceFile)
  (Split-Path -Parent $PrivatePlan.integrated.evidenceDirectory)
  (Split-Path -Parent $PrivatePlan.integrated.remoteCleanupLogFile)
  ($RuntimeReceipts | ForEach-Object { Split-Path -Parent $_ })
) | Sort-Object -Unique
foreach ($PrivateParent in $RequiredParents) {
  New-Item -ItemType Directory -Force -Path $PrivateParent | Out-Null
  & $PrivateArtifactHelper `
    -Operation protect-directory `
    -LiteralPath $PrivateParent | Out-Null
  & $PrivateArtifactHelper `
    -Operation verify-directory `
    -LiteralPath $PrivateParent | Out-Null
}
foreach ($PrivateInput in @($PrivatePlanPath) + $RuntimeReceipts) {
  & $PrivateArtifactHelper `
    -Operation protect-file `
    -LiteralPath $PrivateInput | Out-Null
  & $PrivateArtifactHelper `
    -Operation verify-file `
    -LiteralPath $PrivateInput | Out-Null
}
```

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
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head $candidateHead `
  --evidence-root $EvidenceRoot `
  --manifest .\verification\integrated-identity-access-gate.json `
  --private-plan $PrivatePlanPath
```

After admission, populate the admitted `mockOidc.receiptFile` on a
Docker-capable exact-clean Windows or Linux candidate executor only through the
bounded harness. macOS remains a supported no-receipt owner-flow diagnostic,
but it is not a receipt-capable admitted executor; the harness rejects that
selection before starting the owner flow. On Linux, the existing receipt parent
must have mode `0700` and belong to the executor identity. Every ancestor must
belong to that identity or root; a shared-writable ancestor is accepted only
when its sticky-bit and ownership protect the child. Linked directory
components are forbidden. The harness rejects a replaceable path before it
creates any file:

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
has 13/13 focused harness tests, including executable fake-Docker lifecycle,
loopback forwarding, overload-rejection, exact-readiness, port-release, and
atomic no-overwrite, permissive-umask Unix receipt-output regressions, plus the
replaceable-ancestor and linked-ancestor rejections, focused workflow,
integrated-gate, and Windows Job supervisor contracts. After the second
consumed candidate exposed the missing PowerShell-edition declaration and
follow-up review found that dynamic script blocks ignore `#requires`, that
historical working tree passed 13 focused Windows/installer contracts and the
complete release-contract cell 81/81 with no same-three P0–P2 finding. The
historical repair for the sixth candidate's 250-millisecond natural-drain race
passed its causal paired contract, focused Windows/installer set, complete
release-contract cell, and exact Cargo cell. The later adversarial rejection of
`2f8b127...` supersedes that pre-admission review as merge authority. The
current timeout, capability, DACL, SSH-profile, helper-authentication, and
controller-containment replacement still requires its own exact-head review
and admission. On Linux, the provider remains on an
egress-blocked internal bridge and a bounded Python 3.12 child exposes only
numeric IPv4 loopback; Windows and macOS retain Docker's loopback-only publish
path. The harness resolves the Docker server platform to both the frozen
platform-manifest and config digests because Docker's classic and containerd
image stores expose different immutable IDs. An already staged image is
accepted only when one of those bare digests resolves to itself and Docker
reports the exact locked OS and architecture. Otherwise the harness pulls the
named index-digest reference for the detected platform and rechecks its
store-specific immutable ID. The container runs with `--pull never`, the same
explicit platform, and either the verified bare staged digest or the pulled
named index-digest reference. An offline/private executor can therefore use a
separately transported locked image without trusting a mutable tag. The Docker
29 ARM64 diagnostic proves the Linux internal-bridge topology, but it is not
an exact-head owner-flow receipt.
That admitted receipt and the hosted `mock-oidc` first-attempt result must still
be collected on the final reviewed head.

After the owned tunnel and remote server have settled, derive the schema-2
teardown receipt with the same frozen helper-set identity:

```powershell
node .\verification\write-connected-server-teardown-receipt.mjs `
  --checked-head $candidateHead `
  --remote-cleanup-log $PrivatePlan.integrated.remoteCleanupLogFile `
  --tunnel-process-ledger (
    Join-Path $PrivatePlan.integrated.evidenceDirectory 'tunnel-process-ledger.json'
  ) `
  --remote-server-process-id <directly-launched-ssh-pid> `
  --remote-helper-set-sha256 $PrivatePlan.integrated.remoteHelperSetSha256 `
  --output $PrivatePlan.integrated.teardownEvidenceFile
```

Populate the admitted destinations through the approved target-client, GB10,
connected-server, mock-OIDC, and teardown controllers. Then invoke completion
exactly once. Completion runs every command cell and accepts every private child
only when its receipt matches the frozen plan. The runner consumes the protected
32-byte `attempt.capability` beside the admission and proves it absent before
the first command cell; no capability value belongs in the command line,
environment, admission JSON, or terminal output:

```powershell
node .\verification\integrated-gate-runner.mjs complete `
  --admission <private-admission.json> `
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

Candidate completion has already consumed and deleted the raw attempt
capability. For hosted closure, set `GH_TOKEN` to a separate read-only
credential limited to commit-status read and Actions read. Hosted collection
pins `github.com/mcnatg1/yap`; it does not use the mutable Git remote or
`GH_HOST`.

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
