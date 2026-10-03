# Yap Desktop

Tauri/React desktop client for explicit local dictation, organization-server recording queues, transcript review/correction, and reviewed knowledge. Models are required for inference; frontend and native-boundary fixtures run without them.

Use Node 24 and pinned pnpm 11.7.0. The [cloud runbook](../docs/runbooks/cloud-development.md) installs Rust and native build dependencies. [Current status](../docs/CURRENT-STATUS.md) distinguishes portable checks from Windows/model qualification.

Repo-owned Windows automation and installer validation require PowerShell Core 7.4 or newer (`pwsh.exe`). The scripts fail fast under legacy Windows PowerShell or an older Core runtime.

```powershell
cd C:\dev\yap\desktop
node -v  # should be v24.x
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm test:e2e
pnpm tauri dev
```

Desktop-level automation:

```powershell
pnpm test:e2e:update
pnpm test:desktop:build
pnpm test:desktop
```

Playwright and WDIO write traces, videos, screenshots, and visual diffs under `tests\results` on failure.
The WebdriverIO/Tauri smoke test uses the debug binary at `src-tauri\target\debug\yap-desktop.exe`
unless `APP_BINARY` is set. Run WDIO under Node 24 LTS; Node 26 has produced embedded-session
failures on this machine.

## Windows installer validation

Yap uses Tauri's stock NSIS template and canonical app-data path. On Windows, runtime data lives at
`%APPDATA%\com.mcnatg1.yap`; the stock uninstaller owns its normal UI and delete-data behavior.
There are no Yap-specific NSIS hooks, delete tokens, quarantine directories, or test installer
identity.

On first start after this path change, Yap serializes the transition and copies only recognized
runtime entries (models, recordings, logs, settings, the job ledger, playback registries, and install
identity) from the former `%LOCALAPPDATA%\Yap` directory into staging on the canonical volume. It
recursively rejects links/reparse points, hash-verifies each complete tree, publishes without moving
installer files, re-verifies every destination, and only then retires the legacy sources. Interrupted
staging or retirement directories are reconciled under the same lock and removed only when another
byte-identical copy is verified. This works when Local and Roaming AppData are on different volumes.
A destination conflict, cleanup failure, or ten-second lock timeout stops startup without overwriting
the recoverable copy and presents a native error with a diagnostic in the user's temporary directory.

Builds and static release-contract checks may run on a normal workstation. The install/launch/
uninstall lifecycle may not: it mutates the real production installer identity and is therefore
bounded by a fresh GitHub-hosted Windows runner, Windows Sandbox, or another disposable Windows VM.

```powershell
pnpm tauri build --bundles nsis
$env:YAP_DISPOSABLE_WINDOWS = "1" # only inside the disposable VM
pnpm test:nsis:disposable
```

The harness requires a clean profile, verifies the exact installer hash when supplied, launches the
installed app until it creates `%APPDATA%\com.mcnatg1.yap\logs\yap.log`, bounds and reaps every
process it starts, runs stock silent uninstall, and confirms that stock silent uninstall preserves
app data and Tauri's product install-location registry record. It also verifies the installed notice
and provenance files against the reviewed repository inputs. It never recursively deletes application
data; disposal of the Windows environment is the lifecycle cleanup boundary. Never set
`YAP_DISPOSABLE_WINDOWS=1` in an everyday account.
