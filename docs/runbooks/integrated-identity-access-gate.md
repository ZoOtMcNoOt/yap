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

Exact head `3f9a8b7195dad3afd8b66034349c0482caef0a4a` corrected both empty-stream
binders, passed the three-lens admission review, and produced fresh passing
mock-OIDC, target-client, GB10, and connected-server evidence with exact
teardown. Its sole complete matrix then stopped in
`frontend.release-contracts`: the older tracked-PowerShell inventory still
required every `.ps1` and `.psm1` file to declare PowerShell Core 7.4, even
though the reviewed Phase 7 DACL helper is intentionally invoked through the
pinned inbox Windows PowerShell 5.1 host. The command exited cleanly with zero
retained processes. This is a stale contract failure, not permission to relabel
the passing private children; the admitted head is consumed.

Exact head `4dc572f120f7e284f7453dfd11bd817a2c034104` encoded that single
pinned inbox-host exception while continuing to require Core 7.4 everywhere
else. It was freshly packaged; the unaffected pre-admission checks passed, and
a temporary private connected-path retry passed, but the head was never
admitted. Review found that `/proc/<pid>/environ` can be temporarily empty
between `fork` and `exec`; the cancellation fallback could then return an
unverified state without signalling the exact pending child. Runtime and
assurance review rejected `4dc572f` before any private gate evidence or complete
matrix. Preserve it as a NO-GO; do not admit, retry, or relabel it.

Committed and pushed head
`9defb4a2202b5743f161dafb40f8fb2bc41b8fde` implemented the retained-pidfd
replacement below and passed its unaffected focused prechecks. Connected
prequalification then failed before provider startup because the proxy rejected
the stock GB10 `/usr/bin/socat -> /usr/bin/socat1` package link. No admission,
private gate receipt, complete matrix, PR, or hosted closure occurred. Preserve
that head and its private outputs only as rejected pre-admission evidence.

Exact heads `c4df39f305f739d3eb2987f24ba8387e54627902`,
`7f047c6a1a2838f70908a7c0f5ee106fd84d5fb2`, and
`c5d826ffb85a841e412e41155a3c6c82a2fbe3e4` are later consumed admissions.
The first exposed a private mock-OIDC receipt-publication parser defect. The
second passed mock OIDC but its target-client child proved that saving an
already canonical language selection needlessly retired the warm live model.
The third made equivalent canonical saves true no-ops, passed focused
verification, three-lens exact-head review, full prequalification, and
GitHub-backed admission. Its first admitted mock-OIDC controller then failed
before starting the harness because orchestration required the fixed
`/srv/yap-server/private` ancestor itself to be mode `0700`. Readback proved it
was a real admin-owned mode-`0755` directory with no group/world write bit; the
receipt parent, per-head child, receipt, container, and network remained
absent. Do not retry, complete, or relabel any of these heads. The next
admitted GB10 receipt controller must validate that every real directory
component in its fixed `/srv/yap-server/private/...` chain is owned by root or
the admitted remote account (`admin`), is not redirected, and has no
group/world write access. It must continue to require mode `0700` on the
receipt parent and per-head child and mode `0600` on the receipt. This
fixed-host controller rule is intentionally stricter than the reusable
cross-platform mock-OIDC harness policy described below; that generic harness
retains its protected sticky-directory exception.

Exact head `dece4265e052d775d2d11f1883cd8cc4b2b25191` is also consumed. It
passed focused verification, three-lens exact-head review, complete private
prequalification, and GitHub-backed admission. Its first admitted mock-OIDC
controller authenticated the checked-head helper and fixed receipt path, then
failed before the locked `uv sync` command or owner flow because
non-interactive SSH did not put the reviewed absolute `uv` executable's parent
on `PATH`. The executable remained available at its authenticated private path,
but portable PowerShell could not resolve the bare command name. Readback
proved that the mode-`0700` per-head receipt directory existed, the receipt
remained absent, and no owner flow started. Do not retry, complete, or relabel
this head.

Exact head `63600096cd8afe9f4435f6302c584f89dbdb5915` corrected the admitted
`uv` resolution boundary, passed the same three review lenses, complete private
prequalification, GitHub-backed admission, and all four admitted private
controllers. Independent validation accepted all 13 private receipt children.
Its one complete matrix then failed when the frontend release-contract cell
correctly rejected the installed `@floating-ui/core@1.7.5` `LICENSE` as a
Windows reparse point; that failure consumed the head. The repository lockfile,
generated inventory, and reviewed MIT notice hash were already exact. Readback
instead proved that the private checkout's default pnpm hardlink shared an
inode with the content store and another OneDrive-managed checkout, where the
Microsoft reparse tag had become visible. Do not retry, complete, or relabel
this head.

Exact head `d4adc832da90ef5a65ca8e6a9d702d833e55dbe8` replaced the
hardlinked dependency materialization with a forced copied-package install,
passed the same three review lenses, complete private prequalification,
GitHub-backed admission, all four admitted private controllers, and independent
validation of all 13 private receipt children. Its one complete matrix passed
the frontend cells, native formatting, and strict Clippy. All Rust tests in
`native.tests` then passed, but Visual Studio Build Tools left its `vctip.exe`
diagnostic helper inside the owned Windows Job beyond the
five-second natural drain. The supervisor terminated the Job and correctly
consumed the head. A longer drain is not an acceptable substitute: a focused
default-linker probe reproduced the helper for more than two minutes.
Bundled Rust LLD was rejected because this graph's SQLite and AWS-LC native
archives did not link correctly and native compilation still invoked the
Microsoft helper. Do not retry, complete, or relabel this head.

The approved Build Tools `OptIn=0` change was then applied and read back
successfully. A clean default-MSVC link still launched Microsoft's signed
`VCTIP.EXE` from `link.exe` and retained it beyond the Job drain. This matches
Microsoft's documented boundary: VSCEIP opt-out disables optional diagnostic
collection, while required diagnostic collection is unaffected. The successor
therefore does not delete or replace Microsoft binaries, extend the drain, or
teach Yap's runtime supervisor about compiler-specific exceptions. It keeps
strict descendant cleanup for Yap runtime processes and moves native
compile/link evidence to fresh GitHub-hosted Windows VMs.

The implementation boundary retains assigned-before-resume,
kill-on-close, immediate
explicit termination, authoritative accounting-zero proof, frozen per-cell
deadlines, protected one-attempt capability, exact Windows DACLs, and the
no-config SSH boundary. On Linux, every resident provider launcher, sampler,
and loopback proxy must launch through
`infra/yap-server-node/owned-process-supervisor.py` under the real system
Python 3.12 in isolated/no-site mode (`-I -S`). The supervisor must fork behind
a release barrier, retain the pidfd before release, bind PID plus start time,
prove `exec` and token-owned group membership, and reap with
`waitid(P_PIDFD)`. Output files are exclusively created regular files; setup
failure publishes an authoritative no-child result instead of blocking on an
unsafe path. `RELEASE` and `STOP` writes contain `SIGPIPE`. `STOP`,
parent/control loss, deadline expiry, exec failure, and pidfd-acquisition
failure are bounded. Bash may use the supervisor PID only to reap its direct
child; it must never signal that numeric PID. If the supervisor dies without a
result, state plus the per-run token is the fail-closed recovery boundary:
every surviving group member must verify before bounded cleanup. The proxy
separates Docker create from start and publishes private recovery identity
before create. It reconciles the fixed container name, immutable ID, and run
token before teardown; a foreign replacement is retained and refused. If a
create request is interrupted before the immutable ID is resolved, the record
is retained and the gate fails rather than treating elapsed absence as proof.
Recovery artifacts retire only after direct immutable-ID absence; name or label
replacement is retained and refused. Failure to delete any recovery artifact is
an unclean launcher result. Normal gate teardown independently requires the
recovery record, partial publication, and container-ID file absent before it
clears the proxy path. Provider containers omit Docker auto-removal so normal
exit remains addressable for bounded log capture before explicit immutable-ID
removal. Before any container mutation, the proxy resolves the PATH-selected
`socat` command with GNU `readlink -f` and requires one absolute, regular,
executable target. All 14 focused proxy contracts and the actual qualified GB10
mapping to root-owned `/usr/bin/socat1` pass.

Exact head `944673071804d8178776efa1d1e13651c87df6fb` passed the same
three review lenses, forced copied-package prequalification, GitHub-backed
admission, all four admitted private controllers, independent validation of all
13 private receipt children, and its one complete 25-cell matrix. PR #69 opened
on that exact head. Its first hosted CI dispatch was rejected while GitHub
parsed the workflow, before any job or runner started, because
`${{ runner.environment }}` was evaluated in job-level `env` before runner
assignment. That workflow-authoring defect consumes the head as merge authority
under this runbook's exact-head rule. Preserve its private package and receipts;
do not retry, complete, or relabel them.

Exact workflow successor `cafbe307e7203e09050fdbe2eb080d5d84b65026`
moved the runner-owner binding onto only the three steps that launch contained
product runtimes and added a release contract that rejects `runner.*` context
in job-level environments. It passed focused verification and the same three
read-only review lenses and is preserved at
`origin/phase7-admission-cafbe307`. Its fresh target-client controller then
failed before the complete matrix because cold model warmup saturated the
1,024-frame pending-ASR queue, dropped 11 local-ASR frames, and reached the
adapter-stop bound. Recording reported zero drops. Preserve that private
failure; do not reuse or relabel it.

Exact repair `32cf52891c277a4a3d47aa9fb3cab105ca58af98` adds bounded FIFO
batch catch-up without weakening recording ownership or stop semantics.
Focused runtime, Clippy, format, and evidence-validator checks passed, and the
same three review lenses found no P0–P2 issue. A fresh target-client
qualification passed 12 repeated resource sessions, nine prepared-audio
boundaries, and the 30-second physical-microphone/rendered-UI lifecycle with
zero audio drops. Its first resource attempt remains failed evidence because
one external scheduler sample exceeded the frozen maximum; the identical fresh
rerun passed without a code or threshold change. Documentation reconciliation
is committed at `e019036...`.

Exact documentation successor `dc6359162fb16909d38f410cdb75c2729d83972f`
then passed its one complete private 25-cell matrix and independent receipt
validation. All four CodeQL analyses passed. Hosted CI run `30574652702`
consumed the head when the Linux pre-install executable-bit probe loaded `yaml`
before package materialization. GitHub Windows temp artifacts had an owner
different from the current runner identity; two checkout contracts treated
equivalent `RUNNER~1` and `runneradmin` paths as distinct. Those causes account
for every
failed hosted job. Stock NSIS was not dispatched after CI failed.

Reviewed repair `558fed05e0f959a28fbe4d92499bbe185b0532d6` defers workflow YAML
loading to workflow-reading tests, corrects a mismatched Windows owner with the
protected private DACL, and compares existing checkout-test paths by canonical
identity. Pre-admission preparation of exact descendant `c95cfe0...` exposed
that rewriting an already-correct owner could require elevation under ordinary
development-root ACLs. It was never admitted and no matrix cell ran. Repair
`a823b28...` writes the owner only on an exact observed/current SID mismatch and
still re-reads the exact owner and three-rule protected DACL. Focused ACL,
hosted-portability, and clean-tree admission contracts pass; the same three
review lenses report no P0–P2 finding. Preserve `dc635916...` as consumed
hosted-failure evidence and its validated receipts separately as passing
private evidence; do not retry, extend, or relabel that head or its receipts.

Runner-only closure repairs use the manifest's existing candidate/hosted split.
When the exact descendant diff is confined to hosted workflow or gate tooling,
its focused contracts, and documentation—and review proves that no shipped
client, server, native, model, runtime, or candidate-manifest behavior
changed—the already-passed candidate matrix remains authoritative. Run only
the affected exact-head hosted closure. Any product/runtime or candidate-cell
behavior change still requires a fresh admission and candidate matrix.

That narrow rule applies through `c1d81fc...`: the exact diff from
`dc635916...` contains only hosted/gate tooling, its contracts, and
documentation. Focused verification and the same three review lenses passed.
No new private admission or replacement matrix is required. Exact-head hosted
CI, CodeQL, stock-NSIS, PR #69 closure, and merge remain open.

The authoritative manifest is
[`verification/integrated-identity-access-gate.json`](../../verification/integrated-identity-access-gate.json).
It splits the complete required evidence across the admitted candidate and
hosted closure. The local inventory retains frontend, server, target-client,
GB10, desktop-to-private-server, optional-diagnostics, and receipt-backed
mock-OIDC behavior. Native compilation and WDIO evidence execute in the
required disposable hosted Windows jobs. Hosted closure also includes the
dedicated `mock-oidc` job; that Ubuntu job runs the Linux pidfd/supervisor,
resident-lifecycle, and proxy behavior suites with skips converted to failures.
No production desktop-provider job is listed because no production provider is
selected or shipped.

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

For the fixed GB10 mock-OIDC controller, do not rely on a login shell to extend
`PATH`. Before reservation and again immediately before admitted use,
authenticate every real directory component from the filesystem anchor through
the selected absolute `uv` parent as canonical, non-redirected, owned by root
or `admin`, and not group/world writable. Then authenticate the `uv` path as one
canonical, regular, single-link, `admin`-owned executable with no group/world
write bit and with the reviewed SHA-256, size, and version. In the same
non-interactive SSH command environment used by the admitted controller, make
that exact executable resolvable inside the pinned portable PowerShell process
and prove that `Get-Command uv` returns the authenticated absolute path. The
no-owner preflight must exercise this exact controller invocation, not a login
shell or an environment assembled by a different diagnostic. A resolution
mismatch is a pre-admission failure.

If the workstation does not have Docker, use a Docker-capable exact-clean
Linux executor and copy only its bounded receipt to the new path frozen in the
private plan. A hash-verified portable PowerShell archive may be prepared
privately on that executor; it is gate tooling, not a Yap runtime dependency.
Do not discover a missing executor dependency after admission and then retry
the same checked head.

On the local Windows admission workstation, configure Visual Studio Build Tools
to opt out of the optional Visual Studio Customer Experience Improvement
Program before reservation.
[Microsoft documents the Build Tools configuration](https://learn.microsoft.com/en-us/visualstudio/ide/visual-studio-experience-improvement-program?view=visualstudio)
through the `OptIn` DWORD: Group Policy at
`HKLM\Software\Policies\Microsoft\VisualStudio\SQM` takes precedence; otherwise
Visual Studio 2022 uses
`HKLM\SOFTWARE\Wow6432Node\Microsoft\VSCommon\17.0\SQM`. The effective value
must be `0`. This disables optional collection only; it does not claim that
Microsoft's required diagnostics are disabled. Yap does not modify machine
policy during a gate. Prequalify the exact workstation with:

```powershell
node .\verification\verify-windows-build-tools-optional-diagnostics-opt-out.mjs
if ($LASTEXITCODE -ne 0) {
    throw 'Build Tools optional-diagnostics prerequisite failed.'
}
```

Require
`WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS=disabled:policy` or
`WINDOWS_BUILD_TOOLS_OPTIONAL_DIAGNOSTICS=disabled:installation`. The registry
reader uses the 64-bit .NET registry API, distinguishes an absent key/value
from an unreadable one, requires an actual DWORD, and rejects access, schema,
type, or process failures without falling back from policy to installation
state. It resolves the inbox Windows PowerShell executable through the kernel
object-manager `GLOBALROOT\SystemRoot` alias, derives the real OS root from
that executable, and rejects a conflicting `SystemRoot` or `WINDIR` before
process launch.

The `begin` operation reruns this optional-diagnostics prerequisite before it reserves remote
GitHub admission status, then rechecks the clean head. The candidate manifest
repeats it as
`windows.build-tools-optional-diagnostics-disabled`. Native formatting,
Clippy, compilation, tests, dependency checks, and the WDIO build do not run
inside the persistent admission workstation's command Jobs. They execute on
the exact reviewed pull-request head in the required `rust` and `Native WDIO
smoke (required, no hardware)` CI jobs. The connector integrations and
required WDIO specs also execute there, but their actual Yap server/desktop
runtime trees remain inside the repository's kill-on-close Windows Job
wrapper.

Every CI job named by `hostedClosureCells`—`frontend`, `rust`, required native
WDIO, `server`, and `mock-oidc`—must:

- check out `${{ github.event.pull_request.head.sha || github.sha }}`;
- disable persisted checkout credentials;
- reject any runner whose `runner.environment` is not `github-hosted`;
- prove the checkout head and clean worktree before project setup or execution;
- on Windows, use the no-space absolute System32 command bootstrap to stream
  the runner's extensionless temporary script into the declared absolute
  PowerShell host; on Linux, launch that PowerShell host directly. Then select
  the first resolved Git application deterministically and capture the
  PowerShell and Git paths and SHA-256 identities;
- capture the exact checkout-guard bytes/hash, Git-index hash, and an
  index-independent manifest that hashes every tracked file as initial step
  outputs;
- use `windows-latest` for the four Windows jobs and `ubuntu-latest` for the
  Linux mock-OIDC lifecycle; and
- prove tracked source and the index remain unchanged after execution by
  using the same absolute shell chain, verifying and executing the admitted
  guard bytes in memory, rejecting hidden index flags and linked tracked
  ancestors, forcing Linux executable-bit comparison, rehashing the
  tracked-content manifest, and reusing the admitted Git path/hash. The final
  step must not reread the mutable workspace helper or resolve a shell or Git
  from post-project `PATH`.

The two native jobs additionally must:

- bind `YAP_CHECKED_HEAD` to that expression and verify the running WDIO binary
  reports the same embedded SHA;
- populate the locked Python 3.12 server environment online before connector
  scripts reverify it offline on the fresh runner;
- run connector and required WDIO runtime profiles without GitHub credentials,
  with a private bounded command log, and require assigned-before-resume plus
  active-process-zero Job evidence.

[GitHub documents](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/use-github-hosted-runners)
that each such job receives a new VM and that the VM is decommissioned when the
job finishes. That disposable VM is the lifecycle boundary for Microsoft build
helpers. The Job wrapper remains the lifecycle boundary for launched Yap
runtime and rejects even a non-listening retained descendant. A persistent
self-hosted runner is not an equivalent substitute.

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
independent zero-owner checks. The remote wrapper must place the Yap server
under the checked retained-pidfd supervisor and preserve its token-owned
process-group recovery record; a plain unbounded `kill` followed by `wait` is
not sufficient teardown proof.

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
without opening the pull request so GitHub can address the commit. A dedicated
`GH_TOKEN` limited to commit-status read/write remains the preferred admission
credential. For the current Phase 7 successor only, the user explicitly
authorized transient use of the existing authenticated GitHub CLI credential
because a separate status token is unavailable. Resolve it without printing,
inject it only into the admission process, never persist it, and record that
broader-scope exception in the private admission record. The runner must still
remove GitHub credential variables from every command cell. Prepare a new
private plan for that head with new absent evidence destinations outside the
repository. Runtime preparation receipts and every private result must also
bind to that head.

Start from a new exact checkout whose `desktop/node_modules` path is absent.
Do not accept Git cleanliness as proof because that ignored path can contain a
prior hardlinked install. Materialize the candidate's desktop dependencies
through the pinned package manager with forced copied package files, never the
default clone/hardlink selection:

```powershell
Push-Location .\desktop
try {
  corepack pnpm@11.7.0 install --offline --frozen-lockfile `
    --force --no-optimistic-repeat-install --package-import-method=copy
  if ($LASTEXITCODE -ne 0) {
    throw "Copied dependency materialization failed with exit $LASTEXITCODE."
  }
  pnpm test:release-contract
  if ($LASTEXITCODE -ne 0) {
    throw "The release-contract preflight failed with exit $LASTEXITCODE."
  }
} finally {
  Pop-Location
}
```

The active identity manifest repeats `--force`,
`--no-optimistic-repeat-install`, and `--package-import-method=copy` in its
admitted dependency cell. Disabling optimistic repeat installation prevents
pnpm from retaining an existing hardlinked package merely because the install
appears current; force plus copy then rematerializes package bytes. Before
reservation, the complete release-contract cell must pass from the exact
private checkout after this install. That contract authenticates every
installed notice source as a real, non-redirected file and rejects a
content-store or OneDrive reparse tag. The tracked dependency inventory or
notice bundle is not a substitute for proving the installed bytes that the
release cell will consume.

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
selection before starting the owner flow. For this reusable cross-platform
harness, distinct from the stricter fixed GB10 receipt-controller path, the
existing Linux receipt parent must have mode `0700` and belong to the executor
identity. Every ancestor must belong to that identity or root; a shared-writable
ancestor is accepted only when its sticky-bit and ownership protect the child.
Linked directory components are forbidden. The harness rejects a replaceable
path before it creates any file:

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
capability. For hosted closure, a separate credential limited to commit-status
read and Actions read remains preferred. Under the explicit current-successor
exception above, the existing authenticated GitHub CLI credential may instead
be resolved and injected transiently; never print or persist it, and record the
broader scope. Hosted collection pins `github.com/mcnatg1/yap`; it does not use
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
