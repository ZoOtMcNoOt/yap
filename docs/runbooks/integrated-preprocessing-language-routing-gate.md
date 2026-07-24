# Integrated preprocessing and language-routing gate

This runbook closes the checked preprocessing and language-routing candidate
without turning focused development checks into phase-completion evidence.
The authoritative child inventory is
[`verification/integrated-preprocessing-language-routing-gate.json`](../../verification/integrated-preprocessing-language-routing-gate.json).
Its functional names describe the behavior under test rather than a roadmap
phase number.

## Candidate boundary

Freeze one clean lowercase Git SHA before admitting a run. Every child records
that same SHA, the SHA-256 of its exact manifest definition, one private
evidence SHA-256, and `attempt: 1`. The receipt validator rejects a missing,
extra, duplicate, reordered, retried, failed, stale-definition, or mismatched-
head child.

The candidate scope contains the exact local frontend, dependency/provenance,
unit/build/accessibility, Rust format/lint/test/connector/dependency, required
native WDIO, portable Python 3.12, target-client, GB10 provider, connected
desktop/private-server, and teardown cells. Prepared audio owns transcription
and routing assertions. The short rendered-UI/default-microphone run owns
capture lifecycle, responsiveness, save/delete, and graceful process teardown.
Neither channel requires user interaction.

The repository runner admits one deterministic attempt, requires every private
destination to be absent, locks the manifest and private plan by SHA-256,
executes every command cell, rechecks the clean Git head after every command,
derives evidence hashes itself, and writes the candidate receipt only after all
private artifacts and teardown checks pass. An interrupted or failed attempt
cannot be resumed or relabeled as a first attempt.

The evidence boundary trusts the current operator and current-user private
filesystem. It fails closed against ordinary stale, missing, substituted,
retried, or partially cleaned evidence; it is not tamper-proof attestation
against a malicious machine owner who can rewrite private files and process
state. Suspected operator or host compromise invalidates the run.

The Python checks resolve an already-installed Python 3.12 through `uv`, the
Windows launcher, or the ambient interpreter, in that order. Runtime downloads
are disabled during resolution, and a different minor version fails closed.

## Candidate admission and receipt

Raw command output, audio, transcripts, screenshots, host paths, model paths,
resource samples, and private server evidence stay outside the repository.
The plan and final receipt also stay private.

Before creating any named evidence destination, prepare a private plan with this
exact shape:

```json
{
  "schemaVersion": 1,
  "checkedHead": "<full-lowercase-git-sha>",
  "targetClient": {
    "evidenceDirectory": "<new-absolute-private-directory>",
    "preparedAudioEvidenceFile": "<that-directory>/local-stream-short-boundaries.json",
    "preparedAudioSuiteSha256": "<frozen-suite-sha256>"
  },
  "gb10": {
    "lifecycleEvidenceFile": "<new-absolute-private-json-file>"
  },
  "integrated": {
    "evidenceDirectory": "<new-absolute-private-directory>",
    "remoteCleanupLogFile": "<new-absolute-private-log-file>",
    "teardownEvidenceFile": "<that-directory>/teardown.json"
  }
}
```

Admit the sole attempt from the clean frozen checkout:

```powershell
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head <full-lowercase-git-sha> `
  --evidence-root <existing-private-gate-root> `
  --private-plan <private-plan.json>
```

Use the returned exact destinations for the unattended target-client channel,
GB10 lifecycle aggregate, and connected desktop/private-server slice. Capture
the remote server launch and cleanup in one private log. After the owned SSH
and forwarding processes have exited, derive the connected teardown receipt:

```powershell
node .\verification\write-connected-server-teardown-receipt.mjs `
  --checked-head <full-lowercase-git-sha> `
  --remote-cleanup-log <private-remote-log> `
  --tunnel-process-ledger <private-integrated-evidence>\tunnel-process-ledger.json `
  --remote-server-process-id <directly-launched-ssh-pid> `
  --output <planned-teardown.json>
```

The rendered integration gate publishes the exact two sequential SSH-forward
PIDs only after both have exited. The teardown writer combines that immutable
ledger with the directly launched remote-server SSH PID; arbitrary or partial
caller-supplied PID lists are not accepted.

Then invoke `complete` once. It runs the complete local/native/server command
matrix and publishes the private candidate receipt only if every prepared
private artifact and final local teardown check also passes:

```powershell
node .\verification\integrated-gate-runner.mjs complete `
  --admission <private-admission.json> `
  --attempt-token <admitted-token>
```

The resulting receipt can be independently checked without exposing its
contents:

```powershell
node .\verification\integrated-gate-receipt.mjs validate `
  --manifest .\verification\integrated-preprocessing-language-routing-gate.json `
  --receipt <private-candidate-receipt.json> `
  --scope candidate `
  --checked-head <full-lowercase-git-sha>
```

The validator publishes only the checked head, scope, manifest SHA-256, and
child count. Repository status documentation may record those public-safe
values after the receipt passes.

## Hosted closure

After the focused pull request exists and all checks have completed, derive the
separate `hosted-closure` receipt against the immutable candidate lineage. The hosted
collector queries exact first-attempt workflow runs and job identities through
the authenticated GitHub CLI; it does not accept caller-authored pass fields.
It freezes all four CI jobs, the current CodeQL Rust, Actions,
JavaScript/TypeScript, and Python analyses, and the stock NSIS lifecycle on the
disposable Windows runner:

```powershell
node .\verification\integrated-hosted-closure.mjs `
  --checked-head <full-lowercase-git-sha> `
  --candidate-admission <private-admission.json> `
  --output <new-private-hosted-closure-receipt.json>
```

The hosted head may equal the checked candidate or be its documentation-only
evidence-reconciliation descendant. In the latter case, the collector proves
the candidate is an ancestor, rejects every changed path outside `docs/`, and
rederives the candidate receipt from its canonical admission, exact command
logs, private plan, and private evidence before binding its SHA-256 into the
hosted receipt. An executable, test, workflow, manifest, or verification-tool
change requires a new candidate rather than this exception.

A genuinely unavailable hosted check must be disclosed; it must not be
represented by an invented passing child.

An executable change after the candidate receipt starts invalidates the
candidate. A documentation-only correction still receives review and names the
unchanged checked SHA.
