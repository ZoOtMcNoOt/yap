# Integrated product checkpoint gate

Use this gate for the current whole-product checkpoint. Its identity is
`integrated-product-checkpoint`; it is not a continuation, rerun, or relabeling
of the completed Phase 6 preprocessing and language-routing gate.

The authoritative manifest is
[`verification/integrated-product-checkpoint-gate.json`](../../verification/integrated-product-checkpoint-gate.json).
The runner requires that manifest to be selected explicitly for both admission
and completion, and freezes its exact bytes, checked Git head, private-plan
bytes, one-attempt token, command logs, private evidence, and child definitions
into the admission and receipt.

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
private evidence plan and new absent destinations outside the repository, then
admit the sole attempt:

```powershell
$candidateHead = (git rev-parse HEAD).Trim()
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head $candidateHead `
  --evidence-root <existing-private-gate-root> `
  --manifest .\verification\integrated-product-checkpoint-gate.json `
  --private-plan <new-private-plan.json>
```

The returned admission names the only accepted evidence destinations and
attempt token. Populate those destinations through the approved target-client,
GB10 provider, connected-server, and teardown controllers. Do not place private
audio, transcript text, host paths, raw logs, process ledgers, tokens, or
receipts in Git.

After every private child and teardown receipt is complete, invoke completion
once. Completion runs the manifest's command cells and publishes a candidate
receipt only when every exact child passes:

```powershell
node .\verification\integrated-gate-runner.mjs complete `
  --admission <private-admission.json> `
  --attempt-token <admitted-token> `
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
