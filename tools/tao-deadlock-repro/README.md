# tao session-lock deadlock reproduction

Standalone harness for [#92](https://github.com/mcnatg1/yap/issues/92). Not part
of the product and not built by CI.

## What it does

The lock screen matters only because it delivers `WM_KILLFOCUS` while a key
message is being processed. `is_msg_keyboard_related` counts `WM_KILLFOCUS` as
keyboard-related, so it re-enters the handler that already holds the global
`KEY_EVENT_BUILDERS` lock in tao 0.35.3, and a non-reentrant `parking_lot`
mutex deadlocks.

This posts a `WM_KEYDOWN` and then *sends* a `WM_KILLFOCUS`, which
`PeekMessageW` dispatches inline during key processing. That is the same
ordering a session lock produces, without locking anyone's workstation.

It pins `tao = "=0.35.3"` on purpose, so it keeps testing the version the
product ships even after Tauri bumps.

## Running it

**It must run in an interactive desktop session.** Over SSH it reports a
deadlock that is not real: a tao event loop does not pump without a desktop, so
the control run — `REPRO_INJECT` unset, no messages sent at all — also reports
frozen ticks. Any result gathered over SSH is meaningless.

At the machine, in a normal terminal:

```powershell
cd tools\tao-deadlock-repro
$env:REPRO_INJECT = "1"; cargo run
```

Then the control, which must print `OK`:

```powershell
Remove-Item Env:\REPRO_INJECT; cargo run
```

## Result on our hardware, 2026-08-01

```
CONTROL   OK:       54037 -> 156421 ticks    exit 0
INJECTED  DEADLOCK: frozen at 6627           exit 1
```

Reproduced. The control pumped 102,384 ticks in five seconds; the injected run
froze and never recovered. Same binary, same session, same machine — the only
difference is the two messages.

| output | meaning |
| --- | --- |
| control `OK`, injected `DEADLOCK` | reproduced; we are affected |
| both `OK` | not reproducible on this machine |
| control `DEADLOCK` | the harness is invalid here; ignore the injected run |

The control is the whole point. Without it a frozen loop cannot be told apart
from a loop that never started — which is not hypothetical: over SSH the
control itself reports a deadlock, because a tao event loop does not pump
without a desktop.

The watchdog runs in its own thread for a related reason. `SendMessageW` blocks
until the target thread handles the message, so an injector that also watched
would be blocked by the very deadlock it was meant to report. The first version
did exactly that: it hung instead of reporting the hang, and had to be
interrupted by hand.

## After the fix

Once a `tauri-runtime-wry` above 2.11.4 ships and `cargo tree -i tao` reports
0.36, change the pin here to `0.36` and confirm the injected run prints `OK`.
