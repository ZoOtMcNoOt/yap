import {
  cleanupUnprovenError,
  preservePrimaryError,
  retainedDescendantError,
  supervisorFailureError,
  windowsTerminationEvidence,
} from "./windows-command-job-errors.mjs";
import {
  readWindowsSupervisorStatus,
} from "./windows-command-job-status.mjs";

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function readSupervisorResult(exitCode, signal, protocol) {
  requireCondition(
    exitCode === 0 && signal === null,
    "Windows command Job supervisor exited unsuccessfully.",
  );
  return readWindowsSupervisorStatus(protocol);
}

function primaryTerminationReason(primaryError) {
  return primaryError.code === "INTEGRATED_GATE_COMMAND_OUTPUT_LIMIT_EXCEEDED"
    ? "output-limit"
    : "command-log-write";
}

function unboundCleanupEvidence(status) {
  return status
    ? windowsTerminationEvidence(status, "cleanup-unproven")
    : {
      schemaVersion: 1,
      containment: "windows-job-object",
      rootProcessId: null,
      assignedBeforeResume: false,
      terminationReason: "cleanup-unproven",
      terminateRequested: true,
      rootExited: false,
      activeProcessCount: null,
      activeProcessZeroObserved: false,
      cleanupProven: false,
    };
}

function interpretPrimaryFailure(label, primaryError, status, statusFailure) {
  if (status?.cleanupProven) {
    primaryError.terminatedProcessIds = status.rootProcessId > 0
      ? [status.rootProcessId]
      : [];
    const evidence = windowsTerminationEvidence(
      status,
      primaryTerminationReason(primaryError),
      true,
    );
    if (status.outcome === "supervisor-failure") {
      return preservePrimaryError(
        primaryError,
        supervisorFailureError(
          label,
          new Error("The supervisor reported a native launch failure."),
          status,
        ),
        evidence,
      );
    }
    primaryError.terminationEvidence = evidence;
    return primaryError;
  }
  return preservePrimaryError(
    primaryError,
    cleanupUnprovenError(label, statusFailure, status),
    unboundCleanupEvidence(status),
  );
}

function interpretSupervisorOutcome(label, status) {
  if (status.outcome === "completed") return { status };
  if (status.outcome === "retained-descendant") {
    return { error: retainedDescendantError(label, status) };
  }
  if (status.outcome === "cleanup-unproven") {
    return {
      error: cleanupUnprovenError(
        label,
        new Error("The supervisor could not prove its final process state."),
        status,
      ),
    };
  }
  if (status.outcome === "supervisor-failure") {
    const cause = new Error("The supervisor reported a native launch failure.");
    return {
      error: status.cleanupProven
        ? supervisorFailureError(label, cause, status)
        : cleanupUnprovenError(label, cause, status),
    };
  }
  return {
    error: supervisorFailureError(
      label,
      new Error(`Unexpected supervisor outcome: ${status.outcome}.`),
      status,
    ),
  };
}

export function interpretWindowsCommandResult({
  exitCode,
  label,
  primaryError,
  protocol,
  signal,
}) {
  let status;
  let statusFailure = null;
  try {
    status = readSupervisorResult(exitCode, signal, protocol);
  } catch (error) {
    statusFailure = error;
  }
  if (primaryError) {
    return {
      error: interpretPrimaryFailure(
        label,
        primaryError,
        status,
        statusFailure,
      ),
    };
  }
  if (statusFailure) {
    return { error: supervisorFailureError(label, statusFailure) };
  }
  return interpretSupervisorOutcome(label, status);
}
