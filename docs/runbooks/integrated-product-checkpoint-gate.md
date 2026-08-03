# Integrated product checkpoint gate

This is the historical Checkpoint B whole-product gate. Its identity is
`integrated-product-checkpoint`; it is retained only to validate its original
evidence and must not be used for the meeting-transcription maintainability
repair or its replacement candidate. That checkpoint has its own
[behavior-named runbook](meeting-transcription-maintainability-checkpoint.md)
and manifest. This gate is not a continuation, rerun, or relabeling of the
completed Phase 6 preprocessing and language-routing gate.

The authoritative manifest is
[`verification/integrated-product-checkpoint-gate.json`](../../verification/integrated-product-checkpoint-gate.json).
The runner requires that manifest to be selected explicitly for both admission
and completion, and freezes its exact bytes, checked Git head, private-plan
bytes, one-attempt capability digest, command logs, private evidence, and child
definitions into the admission and receipt.

## Identity boundary

The historical
[`integrated-preprocessing-language-routing-gate.json`](../../verification/integrated-preprocessing-language-routing-gate.json)
remains frozen at SHA-256
`46832f4605a92262917c0afbdeef9608270f9c56cd25a553ab6c6a5e5f7fdb52`.
It exists so historical receipts can still be validated against their original
30-child contract. Never validate a product-checkpoint receipt with that
manifest, reuse a historical admission, or copy a historical pass into the new
gate. The validator requires the receipt gate ID to equal the selected
manifest gate ID and still requires the exact manifest SHA, checked head,
candidate lineage, complete child inventory, definition hashes, evidence
hashes, first attempt, timestamps, and pass statuses.

## Candidate attempt

Start from a clean checkout at the exact candidate head. Prepare a new bounded
private evidence plan and new absent destinations outside the repository.
Before admission, use
`verification/private-gate-artifacts.ps1` to protect and verify the existing
gate root, private-plan file, all three runtime-preparation receipt files, and
the real parent of each planned destination. The detailed copy/paste preflight
in the preprocessing and language-routing runbook is the schema-1 contract for
this checkpoint; named evidence destinations themselves must remain absent.
Then admit the sole attempt:

```powershell
$candidateHead = (git rev-parse HEAD).Trim()
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head $candidateHead `
  --evidence-root <existing-private-gate-root> `
  --manifest .\verification\integrated-product-checkpoint-gate.json `
  --private-plan <new-private-plan.json>
```

The returned safe projection names the admission and candidate-receipt paths;
the admission stores only the one-attempt capability digest. The raw
`attempt.capability` remains in the protected run directory and is never
printed. Populate the admitted destinations through the approved target-client,
GB10 provider, connected-server, and teardown controllers. Do not place private
audio, transcript text, host paths, raw logs, process ledgers, capabilities,
tokens, or receipts in Git.

After every private child and teardown receipt is complete, invoke completion
once. Completion runs the manifest's command cells and publishes a candidate
receipt only when every exact child passes. The runner consumes the protected
`attempt.capability` beside the admission; no capability value belongs in the
command line, environment, or terminal output:

```powershell
node .\verification\integrated-gate-runner.mjs complete `
  --admission <private-admission.json> `
  --manifest .\verification\integrated-product-checkpoint-gate.json
```

Validate the result independently against the behavior-named manifest:

```powershell
node .\verification\integrated-gate-receipt.mjs validate `
  --manifest .\verification\integrated-product-checkpoint-gate.json `
  --receipt <private-candidate-receipt.json> `
  --scope candidate `
  --checked-head $candidateHead
```

Any failure consumes the attempt. Any executable change, manifest change,
private-plan change, missing or extra child, retry, stale definition, evidence
replacement, or non-passing teardown requires a new clean head and a new
admission.

## Hosted closure

After the candidate pull request exists, reconcile only public-safe evidence in
`docs/` if required and commit that documentation-only descendant. An
executable, test, workflow, manifest, or verification-tool change requires a
new candidate; it is not eligible for this lineage exception. After the
required first-attempt hosted checks finish on the exact final reviewed head,
derive a separate hosted-closure receipt from the original candidate admission:

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

The hosted head may equal the candidate head or be its documentation-only
descendant. The collector proves candidate ancestry, rejects any path outside
`docs/` in the cumulative candidate-to-hosted tree diff, and
revalidates the canonical candidate admission and receipt before querying the
exact hosted SHA. Validate the result with both identities:

```powershell
node .\verification\integrated-gate-receipt.mjs validate `
  --manifest .\verification\integrated-product-checkpoint-gate.json `
  --receipt <private-hosted-closure-receipt.json> `
  --scope hosted-closure `
  --checked-head $hostedHead `
  --candidate-head $candidateHead `
  --candidate-receipt-sha256 <private-candidate-receipt-sha256>
```

Record only public-safe hashes and counts in repository documentation after
independent validation succeeds.
