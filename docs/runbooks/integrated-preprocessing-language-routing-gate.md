# Integrated preprocessing and language-routing gate

This runbook closes the checked preprocessing and language-routing candidate
without turning focused development checks into phase-completion evidence.
The authoritative child inventory is
[`verification/integrated-preprocessing-language-routing-gate.json`](../../verification/integrated-preprocessing-language-routing-gate.json).
Its functional names describe the behavior under test rather than a roadmap
phase number.

## Admitted history

Exact executable candidate `97b63be46b05dffa21595f2fd081b8467bb95798`
passed its sole admitted 30-child attempt on 2026-07-24. The manifest SHA-256 is
`8c59a08174a2c1a7e72bef59fefc6a8160ca65982736e0ba7b18f853d893affd`;
the independently validated candidate receipt SHA-256 is
`798f3fcef3709f9751d1e7fc1a8c31b5bf2e429c2cf08efedad4a03b77d87f8d`.
Final adversarial review then found executable restart/cleanup, normative
OpenAPI, hosted-closure, evidence-bound, and persisted-vocabulary defects. That
review explicitly invalidated `97b63be...` as merge authority; its receipt
remains historical evidence and must not be relabeled.

The next admitted candidate,
`4b87e222c8ad7325a12a88709a52b5e9c1baf22e`, failed before provider startup
when its checked builder forced an NGC registry lookup across the deliberately
offline GB10 boundary. The concurrent Windows channel was stopped and exact
local/remote cleanup passed. That admission remains failed private evidence and
must never be retried, resumed, or represented by the historical passing
receipt. Runtime-image preparation now happens before gate admission. It
requires every external base to be digest-pinned and locally present, disables
base-image pulls, and preserves network-dependent dependency layers across
candidate-only revision changes. Preparation may still use the network for
hash- or revision-pinned Dockerfile steps. After preparation, the admitted
gates verify each frozen private preparation-receipt hash, then perform
inspection-only verification of the exact ARM64 image, checked-head revision,
base digest, runtime identity, and receipt-bound immutable image ID. They launch
and record that exact ID; they never build, pull, reconnect, or substitute an
image.
Focused route-less verification passed on the GB10; one
new admitted complete gate remains.
The private plan, command logs, audio, runtime evidence, and receipts remain
outside Git.

Two later admissions remain failed private evidence. Candidate
`7d5d1b79f0f539ca3e4c1160ed25c32442cc3fa3` completed the target-client and
provider workloads, but Docker 29's exact post-removal `network <id> not found`
response was initially treated as an inventory failure; candidate
`6b4eda32ca3853c90b40db607248fab5af23048e` contains the exact-match,
fail-closed compatibility fix, but its Windows controller entered lid-triggered
Modern Standby during evidence collection. That standby interval suspended the
local responsiveness clock and reset the live SSH process. Neither admission
may be resumed, retried, or relabeled.

## Candidate boundary

Freeze one clean lowercase Git SHA before admitting a run. Every child records
that same SHA, the SHA-256 of its exact manifest definition, one private
evidence SHA-256, and `attempt: 1`. The receipt validator rejects a missing,
extra, duplicate, reordered, retried, failed, stale-definition, or mismatched-
head child.

Keep the Windows gate controller awake with its lid open for the entire
admitted attempt. A per-process execution request cannot safely override the
host's physical lid-close action. Run the long GB10 provider lifecycle through
a candidate-scoped transient user service so a transport interruption cannot
terminate healthy on-node work. Before accepting its evidence, require the
transient unit to finish successfully and disappear, then independently verify
the usual zero-container, zero-listener, zero-network, and zero-process
teardown boundary.

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
    "teardownEvidenceFile": "<that-directory>/teardown.json"
  }
}
```

Create all three runtime-preparation receipts from the clean checked head before
admission. Each receipt must be an existing bounded regular file outside the
repository and must bind the exact runtime, Dockerfile hash, ARM64 image ID,
base digest, and checked head. `begin` validates the receipt bytes against the
listed SHA-256 values and freezes the complete private-plan hash.

The plan validator runs on the Windows gate controller, so copy the exact
receipt JSON bytes from the GB10 into the private Windows gate root and verify
that each copied file has the same SHA-256 as its mode-0600 GB10 original. The
plan points to those local byte-identical copies. The remote wrappers use the
GB10 copies and the same frozen hashes; changing either copy invalidates the
attempt.

Admit the sole attempt from the clean frozen checkout:

```powershell
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head <full-lowercase-git-sha> `
  --evidence-root <existing-private-gate-root> `
  --private-plan <private-plan.json>
```

Use the returned exact destinations for the unattended target-client channel,
GB10 lifecycle aggregate, and connected desktop/private-server slice. Capture
the remote server launch and cleanup in one private log. After
`verify-prepared` returns the Cohere and language-detection immutable IDs and
those exact IDs have been handed to the launchers, the remote wrapper must emit
exactly one copy of each public-safe binding:

```bash
printf '%s\n' \
  "REMOTE_RUNTIME_COHERE_VLLM_IMAGE_ID=$vllm_image" \
  "REMOTE_RUNTIME_COHERE_VLLM_PREPARATION_RECEIPT_SHA256=$YAP_COHERE_VLLM_PREPARATION_RECEIPT_SHA256" \
  "REMOTE_RUNTIME_LANGUAGE_DETECTION_IMAGE_ID=$lid_image" \
  "REMOTE_RUNTIME_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256=$YAP_LANGUAGE_DETECTION_PREPARATION_RECEIPT_SHA256"
```

The final validator rejects missing, duplicate, stale, or mismatched marker
lines and compares both IDs to the parsed frozen receipts. The connected cell
also sends one bounded five-window request through `/v1/lid/preflight` and
records the returned AmberNet component, policy, runtime, model, and five
observations in `native-vertical-slice.json`. Configuration markers alone do
not count as language-detection execution. After the owned SSH and forwarding
processes have exited, derive the connected teardown receipt:

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
