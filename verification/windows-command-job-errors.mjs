export function windowsTerminationEvidence(
  status,
  terminationReason,
  terminateRequested = status.terminationRequested,
) {
  return {
    schemaVersion: 1,
    containment: "windows-job-object",
    rootProcessId: status.rootProcessId,
    assignedBeforeResume: status.assignedBeforeResume,
    terminationReason,
    terminateRequested,
    rootExited: status.rootExited,
    activeProcessCount: status.activeProcessCount,
    activeProcessZeroObserved: status.activeProcessZeroObserved,
    cleanupProven: status.cleanupProven,
  };
}

export function cleanupUnprovenError(label, cause, status) {
  const error = new Error(
    `${label} process-tree cleanup could not be proven by the Windows Job supervisor.`,
    { cause },
  );
  error.name = "BoundedCommandCleanupUnprovenError";
  error.code = "INTEGRATED_GATE_COMMAND_TERMINATION_UNVERIFIED";
  if (status) {
    error.nativeErrorCode = status.nativeErrorCode;
    error.terminationEvidence = windowsTerminationEvidence(
      status,
      "cleanup-unproven",
    );
  }
  return error;
}

export function supervisorFailureError(label, cause, status) {
  const error = new Error(
    `${label} Windows Job supervisor failed before it produced valid command evidence.`,
    { cause },
  );
  error.name = "BoundedCommandSupervisorError";
  error.code = "INTEGRATED_GATE_COMMAND_SUPERVISOR_FAILED";
  if (status) {
    error.nativeErrorCode = status.nativeErrorCode;
    error.terminationEvidence = windowsTerminationEvidence(
      status,
      "supervisor-failure",
    );
  }
  return error;
}

export function retainedDescendantError(label, status) {
  const retainedProcessSummary = status.retainedProcessNames.join(", ");
  const error = new Error(
    `${label} exited while retaining descendant processes `
      + `(${retainedProcessSummary}); the owned Job was terminated.`,
  );
  error.name = "BoundedCommandRetainedDescendantError";
  error.code = "INTEGRATED_GATE_COMMAND_RETAINED_DESCENDANT";
  error.rootExitCode = status.targetExitCode;
  error.retainedProcessNames = [...status.retainedProcessNames];
  error.terminationEvidence = windowsTerminationEvidence(
    status,
    "retained-descendant",
  );
  return error;
}

export function preservePrimaryError(
  primaryError,
  terminationFailure,
  evidence,
) {
  if (!Object.hasOwn(primaryError, "primaryError")) {
    Object.defineProperty(primaryError, "primaryError", {
      configurable: false,
      enumerable: false,
      value: primaryError,
      writable: false,
    });
  }
  primaryError.terminationFailure = terminationFailure;
  primaryError.terminationEvidence = evidence;
  return primaryError;
}
