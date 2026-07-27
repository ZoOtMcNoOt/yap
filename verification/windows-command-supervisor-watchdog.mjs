export const WINDOWS_SUPERVISOR_KILL_TIMEOUT_MS = 6_500;
export const WINDOWS_SUPERVISOR_FINAL_SETTLEMENT_TIMEOUT_MS = 1_500;

function stopStream(stream) {
  try {
    stream?.destroy();
  } catch {
    // The watchdog reports cleanup as unverified regardless of stream state.
  }
}

export function startWindowsSupervisorTerminationWatchdog({
  supervisor,
  onLateClose = () => {},
  onUnproven,
  killTimeoutMilliseconds = WINDOWS_SUPERVISOR_KILL_TIMEOUT_MS,
  finalSettlementTimeoutMilliseconds
    = WINDOWS_SUPERVISOR_FINAL_SETTLEMENT_TIMEOUT_MS,
}) {
  let active = true;
  let deadlineExpired = false;
  let finalTimer = null;
  const handleClose = () => {
    if (deadlineExpired) onLateClose();
  };
  supervisor.once("close", handleClose);
  const killTimer = setTimeout(() => {
    if (!active) return;
    try {
      supervisor.kill();
    } catch {
      // Kill-on-close is a backstop; only a valid status can prove cleanup.
    }
    finalTimer = setTimeout(() => {
      if (!active) return;
      active = false;
      deadlineExpired = true;
      stopStream(supervisor.stdin);
      stopStream(supervisor.stdout);
      stopStream(supervisor.stderr);
      try {
        supervisor.unref();
      } catch {
        // Settlement remains bounded even if the process object cannot unref.
      }
      onUnproven(new Error(
        "The Windows command Job supervisor did not close before its final deadline.",
      ));
    }, finalSettlementTimeoutMilliseconds);
  }, killTimeoutMilliseconds);

  return function cancelWindowsSupervisorTerminationWatchdog() {
    if (deadlineExpired) return;
    if (!active) return;
    active = false;
    clearTimeout(killTimer);
    if (finalTimer) clearTimeout(finalTimer);
    supervisor.removeListener("close", handleClose);
  };
}
