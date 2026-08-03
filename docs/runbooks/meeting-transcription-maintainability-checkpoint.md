# Meeting-transcription maintainability checkpoint

Use this behavior-named gate for the post-Phase-8 ownership and maintainability
checkpoint. Its identity is `meeting-transcription-maintainability-checkpoint`.
It does not reuse the completed Phase 8 image or claim a new model-quality,
capacity, or production-promotion result.

The authoritative manifest is
[`verification/meeting-transcription-maintainability-checkpoint.json`](../../verification/meeting-transcription-maintainability-checkpoint.json).
The gate runs the complete local/native/server matrix once and adds five
private lifecycle receipts for the exact checked-head Tiron image, a real
desktop-to-GB10 speaker-attributed result, active cancellation, and zero
retained owners.

## What this evaluates

The product slice uses a deterministic 65-second derivative of Yap's locked
CC-BY-4.0 fixture. It proves multi-window Tiron execution, result and companion
hash binding, native History loading, rendered anonymous speaker turns, tunnel
recovery, and cancellation during server processing. It is intentionally not a
speech-quality benchmark. Tiron's pinned upstream evaluation code remains
available for the separate private messy-meeting acceptance corpus; it does not
replace this end-to-end lifecycle proof.

## Freeze and prepare the checked image

Start from a clean checkout at the exact candidate head. The Windows controller
needs Node 24, `uv`, the Visual Studio Rust build environment, the checked
private-server SSH profile, and a private gate root outside Git. The GB10 needs
the exact Tiron and ECAPA snapshots named by
`server/meeting-transcription-runtime.lock.json`.

Before admission, qualify the canonical Windows native build mode. NASM must be
on `PATH`, and `AWS_LC_SYS_NO_ASM` must be absent rather than set to `1`. If this
checkout's Cargo target cache has ever been built with the no-assembly override,
clean only the generated AWS-LC package before returning to the canonical mode:

```powershell
Remove-Item Env:AWS_LC_SYS_NO_ASM -ErrorAction SilentlyContinue
Push-Location .\desktop\src-tauri
cargo clean -p aws-lc-sys
Pop-Location
```

Then run `pnpm test:desktop:build` from `desktop` as a focused pre-admission
smoke. Do not admit the candidate until that build passes. This prevents stale
archives from two incompatible AWS-LC build modes from being combined by the
Windows linker during the product lifecycle.

The checkpoint changes `server/runtime/tiron/Dockerfile`, so the Phase 8 image
is historical evidence only. Prepare and verify a new image from the candidate:

```bash
release_root='/srv/yap-server/releases/<checked-head>'
preparation_root='/path/to/private/runtime-preparation'
checked_head="$(git -C "$release_root" rev-parse HEAD)"
install -d -m 0700 "$preparation_root"
umask 077
tiron_receipt="$preparation_root/tiron-$checked_head.json"
PYTHONPATH="$release_root/server/src" \
  python3.12 -m yap_server.pools.checked_runtime_image \
    prepare meeting-transcription "$checked_head" >"$tiron_receipt"
tiron_receipt_sha256="$(sha256sum "$tiron_receipt" | awk '{print $1}')"
tiron_image="$(
  PYTHONPATH="$release_root/server/src" \
    python3.12 -m yap_server.pools.checked_runtime_image \
      verify-prepared meeting-transcription "$checked_head" \
      "$tiron_receipt" "$tiron_receipt_sha256"
)"
```

Copy the receipt bytes without modification into the Windows private gate root
and verify that the source and copy SHA-256 values match. Protect the copied
receipt, private plan, gate root, and every destination parent with
`verification/private-gate-artifacts.ps1`. The named lifecycle directory,
remote log, and teardown file must not exist at admission.

The private plan has this exact shape:

```json
{
  "schemaVersion": 1,
  "gateId": "meeting-transcription-maintainability-checkpoint",
  "checkedHead": "<full-lowercase-git-sha>",
  "tironPreparation": {
    "receiptFile": "<absolute-private-copied-tiron-receipt>",
    "receiptSha256": "<sha256-of-exact-receipt-bytes>"
  },
  "productLifecycle": {
    "evidenceDirectory": "<new-absolute-private-directory>",
    "remoteCleanupLogFile": "<new-absolute-private-log-file>",
    "teardownEvidenceFile": "<evidence-directory>/teardown.json"
  }
}
```

Admit the only candidate attempt before creating any planned destination:

```powershell
$CandidateHead = (git rev-parse HEAD).Trim()
node .\verification\integrated-gate-runner.mjs begin `
  --checked-head $CandidateHead `
  --evidence-root <existing-private-gate-root> `
  --manifest .\verification\meeting-transcription-maintainability-checkpoint.json `
  --private-plan <new-private-plan.json>
```

## Run the private product lifecycle

Launch `infra/yap-server-node/development-batch-server.sh` through the reviewed
direct OpenSSH controller described in
[`yap-server-node-setup.md`](yap-server-node-setup.md). Use only the explicit
Tiron variables: checked head, private job storage, Tiron model directory,
ECAPA directory, verified image, preparation receipt path and SHA-256, and the
absolute checked `uv` executable. Do not launch Cohere, AmberNet, Nemotron, or a
candidate-capability override for this meeting-only route.

The owned remote wrapper writes its stdout and stderr to the planned private
cleanup log and emits exactly one copy of these public-safe bindings after the
server is ready:

```bash
printf '%s\n' \
  "REMOTE_RUNTIME_TIRON_IMAGE_ID=$tiron_image" \
  "REMOTE_RUNTIME_TIRON_PREPARATION_RECEIPT_SHA256=$tiron_receipt_sha256" \
  "REMOTE_PRIVATE_SERVER_READY=$checked_head"
```

With the server still owned by that wrapper, run the desktop slice from the
clean Windows candidate. `YAP_PRIVATE_SERVER_ASR_GATE_IMAGE_ID` is the
`sha256:...` image ID from the preparation receipt, not its mutable tag:

```powershell
$Plan = Get-Content -LiteralPath <new-private-plan.json> -Raw |
  ConvertFrom-Json -Depth 10
$Receipt = Get-Content -LiteralPath $Plan.tironPreparation.receiptFile -Raw |
  ConvertFrom-Json -Depth 10
$env:YAP_CHECKED_HEAD = $Plan.checkedHead
$env:YAP_PRIVATE_SERVER_ASR_GATE_PROFILE = 'meeting-transcription'
$env:YAP_PRIVATE_SERVER_ASR_GATE_BASE_URL = 'http://127.0.0.1:18765'
$env:YAP_PRIVATE_SERVER_ASR_GATE_EVIDENCE_DIR = $Plan.productLifecycle.evidenceDirectory
$env:YAP_PRIVATE_SERVER_ASR_GATE_IMAGE_ID = $Receipt.imageId
$env:YAP_PRIVATE_SERVER_ASR_GATE_PREPARATION_RECEIPT_SHA256 =
  $Plan.tironPreparation.receiptSha256
Push-Location .\desktop
pnpm test:desktop:build
pnpm exec wdio run .\tests\wdio.private-server-asr-gate.conf.ts
Pop-Location
```

Signal the exact remote wrapper through a separate bounded SSH control call
while its original OpenSSH process and evidence channel are still alive. Wait
for the wrapper to stop its server and Tiron container, remove only its owned
resources, emit exactly one `REMOTE_GATE_CLEANUP=PASS`, and exit naturally.
Then create the independent teardown receipt from the direct wrapper PID and
the WDIO-owned two-forward ledger:

```powershell
node .\verification\write-connected-server-teardown-receipt.mjs `
  --checked-head $Plan.checkedHead `
  --remote-cleanup-log $Plan.productLifecycle.remoteCleanupLogFile `
  --tunnel-process-ledger (Join-Path $Plan.productLifecycle.evidenceDirectory 'tunnel-process-ledger.json') `
  --remote-server-process-id <direct-remote-wrapper-ssh-pid> `
  --output $Plan.productLifecycle.teardownEvidenceFile
```

Private audio, transcripts, model paths, raw logs, plans, process ledgers,
receipts, and host identities stay outside Git.

## Run the complete checkpoint once

After implementation, documentation, focused checks, and antagonist review are
frozen, invoke completion exactly once. It consumes the protected admission
capability, validates all five private receipts, runs every command cell, and
publishes the candidate receipt only if the entire exact-head matrix passes:

```powershell
node .\verification\integrated-gate-runner.mjs complete `
  --admission <private-admission.json> `
  --manifest .\verification\meeting-transcription-maintainability-checkpoint.json
```

Validate the private candidate receipt against the same manifest and checked
head. Any executable, test, workflow, manifest, verification-tool, or private
evidence change consumes the attempt and requires a new clean head and
admission.

After the focused PR is reviewed, derive hosted closure only from successful
first-attempt jobs on the exact reviewed head. A documentation-only descendant
may use the runner's documented lineage exception; any executable change
requires a new candidate gate. Merge only after the exact head is green.
