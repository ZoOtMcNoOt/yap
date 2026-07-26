# Integrated identity and access gate

Use this gate for the complete identity-and-access delivery candidate. Its
behavior identity is `integrated-identity-access`. It is separate from the
historical Phase 6 gate and the earlier whole-product checkpoint, so neither
their admissions nor their pass receipts can be relabeled or reused.

The authoritative manifest is
[`verification/integrated-identity-access-gate.json`](../../verification/integrated-identity-access-gate.json).
It retains the complete frontend, native, server, target-client, GB10, and
desktop-to-private-server matrix. The local and hosted inventories additionally
name the self-contained native identity broker explicitly.

## Evidence boundary

Repository tests prove the single-tenant token contract with locally signed
tokens, tenant-specific principal IDs, durable access disable/restore,
cross-owner isolation, restart behavior, protected readiness, and desktop
binding. The private GB10 and connected-server receipts continue to qualify the
physical ASR lifecycle through the development access mode.

That is not evidence of real enterprise enrollment. Entra application
registrations, tenant policy, assignment/consent, test principals, certificates,
DNS, ZPA policy, and production identity-store operations remain explicit IT
inputs. Do not substitute developer-created infrastructure or claim that this
gate proves those controls.

Private audio, transcript text, host paths, raw metrics, process ledgers,
tokens, command output, and receipts must remain outside Git. Only public-safe
hashes, counts, and pass/fail status may be reconciled into documentation after
independent receipt validation.

## Sole candidate attempt

Start from the exact clean reviewed candidate. Push that exact candidate branch
without opening the pull request so GitHub can address the commit. Use a
dedicated `GH_TOKEN` limited to commit-status read/write for admission. Prepare
a new private plan for that head with new absent evidence destinations outside
the repository. Runtime preparation receipts and every private result must also
bind to that head.

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

Populate the admitted destinations through the approved target-client, GB10,
connected-server, and teardown controllers. Then invoke completion exactly
once. Completion runs every command cell and accepts every private child only
when its receipt matches the frozen plan:

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
candidate receipt validates. Hosted CI, the identity-broker job, CodeQL, and the
disposable-Windows NSIS job must all pass on the exact final reviewed head on
their first attempt. A documentation-only descendant may reconcile public-safe
evidence; any other change requires a new candidate gate.

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

The pre-merge C# boundary is enforced by the pinned .NET SDK's full analyzer
set, warnings-as-errors, locked restore, the NuGet advisory audit, and the
identity-broker CI job. The repository's GitHub CodeQL configuration uses
default setup; GitHub enrolls a newly detected supported language after that
language reaches the default branch. Therefore C# CodeQL is a post-merge
default-branch confirmation, not evidence claimed by this pre-merge receipt.
See GitHub's
[default setup documentation](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configure-code-scanning).
