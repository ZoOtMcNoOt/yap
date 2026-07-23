# Target-client language-routing qualification

This runbook closes the Phase 6 Windows Preview safety boundary for the
resident Nemotron, Silero, and AmberNet live path. It does **not** rerun the
consumed natural-switch quality target, remove the Preview label, certify a
minimum physical device, or replace the complete Phase 6 gate.

The Phase 6 qualification has two evidence channels. A result is incomplete
unless both belong to the same clean checked head and Windows machine:

1. the prepared-audio native resource and repeated-session collector;
2. a physical-microphone and rendered-UI run through the release-mode WDIO
   binary.

The separate prepared-audio `short-boundaries` collector closes the
250-ms-through-30-second duration contract on that same clean head. It is not a
third physical-host channel and does not duplicate the 15-minute UI soak.

A paired energy/thermal measurement on a representative low-end physical
device is a separate default-on and Phase 10 hardware-certification boundary.
It may accompany a Phase 6 run, but its absence does not block merging an
explicit, default-off Preview. A virtual machine, affinity limit, or development
host must never be relabeled as physical battery or thermal evidence.

All raw logs, audio, screenshots, ETL traces, power reports, and aggregate JSON
stay in a current-user-only directory outside the repository. Git and hosted CI
receive only code, plans, and the final non-sensitive status claim after review.

## Phase 6 host and prerequisites

- A Windows host whose actual processor name and logical-processor count are
  recorded in the private evidence. Phase 6 makes no minimum-device,
  battery-life, or thermal claim from this run.
- A clean candidate SHA with Node 24, pnpm, Rust, the Tauri build dependencies,
  and all crates/packages already cached locally.
- Verified local installations of the pinned Nemotron INT8, Silero, and
  AmberNet QDQ INT8 artifacts under one private models root. No gate step may
  download or substitute model bytes.
- A license-cleared mono 16-kHz WAV for the native collector, plus an exact
  lowercase SHA-256, and a vetted mono PCM16/16-kHz WAV for the prepared-audio
  boundary suite. One file may serve both roles only when it satisfies both
  formats.
- A license-cleared spoken-audio stimulus for the physical microphone run,
  identified by SHA-256 and a bounded SPDX-style license identifier. Play it
  acoustically from a separate offline device; do not use a virtual microphone
  for the physical-capture claim.
- No active non-loopback interface with a default gateway. A direct private
  interface without a gateway is allowed. The native gate checks this before
  and after inference and never changes adapter state itself.

Prepare caches while online, verify the candidate, and then disconnect the
target before creating evidence. If the offline build attempts dependency or
model retrieval, the run fails rather than silently broadening the boundary.

## 1. Native resource and repeated-session gate

Create an unused evidence path beneath an existing private parent outside the
checkout. The script applies a current-user-only ACL before writing evidence.

```powershell
$Head = (git rev-parse HEAD).Trim()
$Evidence = 'D:\private-yap-evidence\target-client\' + $Head
$Models = 'D:\private-yap-models'
$Fixture = 'D:\private-yap-fixtures\live-routing-38s.wav'
$FixtureSha256 = '<lowercase-sha256>'

pwsh.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\desktop\tests\scripts\resident-language-routing-resource-gate.ps1 `
  -CheckedHead $Head `
  -ModelsDirectory $Models `
  -AudioFixture $Fixture `
  -AudioFixtureSha256 $FixtureSha256 `
  -EvidenceDirectory $Evidence `
  -SessionCycles 12
```

The collector uses the production-sized bounded queue and ten-millisecond
source cadence with the executable two-thread Nemotron default. It requires:

- exact source accounting and zero dropped frames in every cycle;
- combined inference below real time;
- scheduler-delay p95 at or below 50 ms and maximum at or below 250 ms;
- drain at or below six seconds;
- all requested start/reset cycles to pass; and
- no more than 64 MiB private-byte growth from the first completed paced cycle
  to any later cycle end or the final cycle.

The resulting `resource-gate-context.json` deliberately records neither the
models path nor the audio path. It records the observed processor and logical-
processor count so the result cannot be presented as another machine. The
profile contains aggregate counts and resource measurements, never transcript
text. Optional `-ExpectedProcessorToken` and `-ExpectedLogicalProcessors`
parameters are reserved for a later named-device certification; omitting them
uses and records the actual host.

This boundary begins at prepared audio. It is not microphone, rendered-UI,
energy, or thermal evidence; its context file states those exclusions.

## 2. Prepared-audio short-boundary gate

Before disconnecting, build only the nine immutable boundary inputs in the
external private cache. Do not select the retained complete two-hour profile for
the Phase 6 Preview gate:

```powershell
$DurationSource = 'D:\private-yap-fixtures\duration-source-pcm16.wav'
$env:PYTHONPATH = (Resolve-Path '.\server\src').Path
$env:YAP_EVAL_CACHE = 'D:\private-yap-evaluation-cache'
$DurationBuild = (
  uv run --isolated --no-project --python 3.12 python `
    -m yap_server.evaluation.local_stream_duration_suite `
    --profile short-boundaries `
    --source $DurationSource
) | ConvertFrom-Json
```

After the native resource script creates the protected evidence directory and
while the machine is still offline, run the prepared-audio collector:

```powershell
$env:YAP_CHECKED_HEAD = $Head
$env:YAP_MODELS_DIR = $Models
$env:YAP_TEST_LOCAL_DURATION_PROFILE = 'short-boundaries'
$env:YAP_TEST_LOCAL_DURATION_SUITE = $DurationBuild.suitePath
$env:YAP_TEST_LOCAL_DURATION_SUITE_SHA256 = $DurationBuild.suiteSha256
$env:YAP_TEST_LOCAL_DURATION_EVIDENCE = Join-Path `
  $Evidence 'local-stream-short-boundaries.json'

Push-Location .\desktop\src-tauri
cargo test --locked --lib `
  local_stream_duration_ladders_preserve_audio_and_finalize `
  -- --ignored --nocapture
Pop-Location
```

The collector independently rejects a different or dirty Git head, an
unrecognized profile, altered plan/suite/track/audio identity, paths inside the
repository, dropped audio, incomplete finalization, or degraded/unavailable
inference. It runs for roughly the sum of the nine source durations—under one
minute plus inference/finalization overhead—not for two hours. Its versioned
private aggregate records the functional profile but no source path or
transcript text.

## 3. Physical microphone and rendered UI

Build the test-instrumented release binary from the same clean head while the
host remains offline:

```powershell
Push-Location .\desktop
pnpm test:desktop:build:release
```

Run the exact release binary from the same protected evidence boundary:

```powershell
$env:YAP_CHECKED_HEAD = $Head
$env:YAP_TARGET_CLIENT_EVIDENCE_DIR = $Evidence
$env:YAP_MODELS_DIR = $Models
$env:APP_BINARY = (Resolve-Path '.\src-tauri\target\release\yap-desktop.exe').Path
$env:YAP_HARDWARE_ACTIVE_CAPTURE_MS = '900000'
$env:YAP_TARGET_CLIENT_STIMULUS_SHA256 = '<lowercase-sha256>'
$env:YAP_TARGET_CLIENT_STIMULUS_LICENSE = 'CC-BY-4.0'

pnpm test:target-client-language-routing-ui
Pop-Location
```

The specialized WDIO configuration refuses a dirty or different head. It
independently revalidates the native context, profile, and log hashes; the
observed processor identity and processor count; two ASR threads; and all 12
sustained cycles. It verifies that no model-load snapshots remain and never
copies private model or recording bytes into the checkout.

During the 15-minute capture, keep the stimulus audible at a representative
near-field level and interact normally with the machine. The gate requires the
physical microphone, speaking state, local-fallback route, both resident
language-support artifacts, at least two enabled locales, no degraded/error
state, four early-stop/restart recovery cycles, UI timer-delay p95 at or
below 50 ms, UI maximum delay at or below 250 ms, exact save/idle lifecycle
ordering, and deletion of all captured recording artifacts. The early-stop
path issues stop while start is still outstanding, so it exercises the real
`cancel_pending_start` boundary before proving later sessions recover. The
aggregate JSON contains no transcript text. Failure screenshots and driver
logs remain under the external private evidence root.

The release-mode binary includes the WDIO capability solely for this disposable
qualification build. It is not the distributable production artifact.

## Optional physical-device energy and thermal certification

Before enabling automatic routing by default or making a minimum-device or
enterprise deployment claim, run matched 15-minute trials on the same physical
target, power plan, charge band,
display level, acoustic stimulus, and checked-head binary:

1. Nemotron live capture with automatic language routing disabled; and
2. Nemotron live capture with the pinned Silero/AmberNet route enabled.

Freeze the measurement setup before either trial. Follow Microsoft's current
[device-under-test setup for battery-life measurements](https://learn.microsoft.com/en-us/windows-hardware/test/assessments/device-under-test-setup-for-battery-life)
and use the Windows ADK
[Energy Efficiency assessment](https://learn.microsoft.com/en-us/windows-hardware/test/assessments/energy-efficiency)
or a calibrated external power meter. A bounded
[WPR trace](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/wpr-command-line-options)
supplies CPU scheduling and throttling context. `powercfg /srumutil` may be kept
as supplemental system energy-estimation evidence, but its aggregate export is
not by itself the matched short-window authority.

The frozen acceptance limits are:

- at most 0.5 W application-idle package-power increase;
- at most 15% active energy increase from enabling Silero/AmberNet beside the
  same Nemotron workload;
- at least 10 C minimum headroom to the platform-reported thermal limit; and
- no observed thermal throttling.

If the target exposes no trustworthy temperature or throttling channel, record
that limitation in the private lab notes and keep this qualification open; an
`unavailable` value cannot create a passing aggregate. CPU time is not a
substitute for calibrated energy or thermal evidence. Raw ADK/WPR/meter output
and exact tool versions remain private and hash-addressed.

If collected alongside the UI run, set
`YAP_TARGET_CLIENT_POWER_THERMAL_EVIDENCE_FILE` to the validated aggregate
beneath the protected evidence root. The UI gate binds it to the checked head,
binary, processor, and stimulus. Otherwise it records that physical power and
thermal certification is deferred and cannot be inferred from the Preview
result.

The final aggregate follows the versioned
[`target-client-power-thermal-evidence` schema](../../desktop/tests/fixtures/target-client-power-thermal-evidence.schema.json).
For example:

```json
{
  "schemaVersion": 1,
  "checkedHead": "<40-lowercase-hex>",
  "processorName": "11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz",
  "appBinarySha256": "<64-lowercase-hex>",
  "stimulusSha256": "<64-lowercase-hex>",
  "measurementBoundary": "nemotron-only-vs-nemotron-plus-silero-ambernet",
  "measurementMethod": "windows-adk-energy-efficiency+wpr",
  "measurementToolVersion": "Windows ADK 10.1 plus WPR 10.1",
  "powerPlanGuid": "381b4222-f694-41f0-9685-ff5bb260df2e",
  "baselineDurationMs": 900000,
  "candidateDurationMs": 900000,
  "idlePackagePowerDeltaWatts": 0.3,
  "activeEnergyOverheadPercent": 9.5,
  "temperatureTelemetry": "measured",
  "thermalLimitSource": "OEM EC sensor and platform TjMax",
  "minimumThermalHeadroomC": 15,
  "thermalThrottlingObserved": false,
  "rawEvidenceSha256": ["<64-lowercase-hex>"],
  "transcriptTextRecorded": false
}
```

The UI gate rejects unknown fields, identity or binary mismatches, duplicate raw
receipts, short trials, unavailable telemetry, throttling, or any metric outside
the frozen limits. It copies only this path-free aggregate into the private run
root and rehashes the source receipt at completion.

## Completion and interpretation

An engineer reviews the native and rendered-UI channels together, verifies the
separate short-boundary aggregate belongs to the same clean head, checks their
SHA and machine identity, and confirms that cleanup left no recordings, model
snapshots, background Yap processes, or listeners. Only then may the Phase 6
documents mark the current-host Preview safety and proportional-duration items
complete.

Passing the two Phase 6 channels means the accepted AmberNet route is safe
enough to remain an explicit default-off Preview on the tested Windows host.
It does not certify an i5, battery life, thermals, or a minimum supported
device. The previously consumed 0/4
natural-switch result still prevents a stronger automatic-switching quality
claim. Physical low-end hardware certification remains required before the
feature becomes default-on and in the Phase 10 release matrix. Any change to
model bytes, frontend, thread count, queue size, routing policy, UI ownership,
or capture lifecycle invalidates the affected channel and requires a new
checked-head qualification.
