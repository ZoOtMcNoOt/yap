import {
  closeSync,
  fstatSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import path from "node:path";

const SUPERVISOR_STATUS_LIMIT_BYTES = 16 * 1024;

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function samePath(left, right) {
  return path.normalize(left).toLowerCase()
    === path.normalize(right).toLowerCase();
}

function readBoundedInvocationStatus(protocol) {
  const descriptor = openSync(protocol.statusPath, "r");
  try {
    const descriptorMetadata = fstatSync(descriptor);
    const pathMetadata = lstatSync(protocol.statusPath);
    const realStatusPath = path.normalize(realpathSync.native(protocol.statusPath));
    const confirmedPathMetadata = lstatSync(protocol.statusPath);
    requireCondition(
      descriptorMetadata.isFile()
        && pathMetadata.isFile()
        && confirmedPathMetadata.isFile()
        && !pathMetadata.isSymbolicLink()
        && !confirmedPathMetadata.isSymbolicLink()
        && descriptorMetadata.size > 0
        && descriptorMetadata.size <= SUPERVISOR_STATUS_LIMIT_BYTES
        && descriptorMetadata.dev === pathMetadata.dev
        && descriptorMetadata.ino === pathMetadata.ino
        && descriptorMetadata.dev === confirmedPathMetadata.dev
        && descriptorMetadata.ino === confirmedPathMetadata.ino
        && samePath(realStatusPath, protocol.statusPath)
        && samePath(path.dirname(realStatusPath), protocol.expectedLogDirectory),
      "Windows command Job supervisor status was not one bounded real file.",
    );
    return JSON.parse(readFileSync(descriptor, "utf8"));
  } finally {
    closeSync(descriptor);
  }
}

function validateStatusShape(status, protocol) {
  const expectedKeys = [
    "activeProcessCount",
    "activeProcessZeroObserved",
    "assignedBeforeResume",
    "cleanupProven",
    "containment",
    "elapsedMilliseconds",
    "environmentSha256",
    "launchNonce",
    "launchSpecSha256",
    "nativeErrorCode",
    "outcome",
    "retainedDescendantDetected",
    "retainedProcessNames",
    "rootExited",
    "rootProcessId",
    "schemaVersion",
    "supervisorIdentitySha256",
    "targetExitCode",
    "terminationRequested",
  ];
  requireCondition(
    status
      && typeof status === "object"
      && !Array.isArray(status)
      && JSON.stringify(Object.keys(status).sort()) === JSON.stringify(expectedKeys),
    "Windows command Job supervisor status fields differed from its contract.",
  );
  requireCondition(
    status.schemaVersion === 2
      && status.containment === "windows-job-object"
      && status.supervisorIdentitySha256 === protocol.supervisorIdentitySha256
      && status.environmentSha256 === protocol.environmentSha256
      && status.launchNonce === protocol.launchNonce
      && status.launchSpecSha256 === protocol.launchSpecSha256
      && [
        "cleanup-unproven",
        "completed",
        "retained-descendant",
        "supervisor-failure",
        "terminated",
      ].includes(status.outcome)
      && Number.isSafeInteger(status.rootProcessId)
      && status.rootProcessId >= 0
      && typeof status.assignedBeforeResume === "boolean"
      && (
        status.targetExitCode === null
        || (
          Number.isSafeInteger(status.targetExitCode)
          && status.targetExitCode >= 0
          && status.targetExitCode <= 0xffffffff
        )
      )
      && typeof status.terminationRequested === "boolean"
      && typeof status.rootExited === "boolean"
      && Number.isSafeInteger(status.activeProcessCount)
      && status.activeProcessCount >= 0
      && typeof status.activeProcessZeroObserved === "boolean"
      && typeof status.cleanupProven === "boolean"
      && typeof status.retainedDescendantDetected === "boolean"
      && Array.isArray(status.retainedProcessNames)
      && status.retainedProcessNames.length <= 128
      && status.retainedProcessNames.every(
        (name) => typeof name === "string" && /^[a-z0-9._-]{1,128}$/.test(name),
      )
      && (
        status.retainedDescendantDetected
        || status.retainedProcessNames.length === 0
      )
      && Number.isSafeInteger(status.elapsedMilliseconds)
      && status.elapsedMilliseconds >= 0
      && (
        status.nativeErrorCode === null
        || Number.isSafeInteger(status.nativeErrorCode)
      ),
    "Windows command Job supervisor status values differed from its contract.",
  );
}

function validateCleanupProof(status) {
  if (!status.cleanupProven) return;
  const assignedCleanup = status.assignedBeforeResume
    && status.rootProcessId > 0
    && status.rootExited
    && status.activeProcessCount === 0
    && status.activeProcessZeroObserved;
  const preAssignmentCleanup = status.outcome === "supervisor-failure"
    && !status.assignedBeforeResume
    && status.activeProcessCount === 0
    && (
      (status.rootProcessId === 0 && !status.rootExited)
      || (status.rootProcessId > 0 && status.rootExited)
    );
  requireCondition(
    assignedCleanup || preAssignmentCleanup,
    "Windows command cleanup was claimed without complete Job evidence.",
  );
}

function validateOutcome(status) {
  if (status.outcome === "completed") {
    requireCondition(
      status.cleanupProven
        && status.targetExitCode !== null
        && !status.terminationRequested
        && !status.retainedDescendantDetected,
      "A completed Windows command had contradictory Job evidence.",
    );
  }
  if (status.outcome === "terminated") {
    requireCondition(
      status.cleanupProven
        && status.terminationRequested
        && !status.retainedDescendantDetected,
      "A terminated Windows command had contradictory Job evidence.",
    );
  }
  if (status.outcome === "retained-descendant") {
    requireCondition(
      status.cleanupProven
        && status.terminationRequested
        && status.retainedDescendantDetected
        && status.retainedProcessNames.length > 0,
      "A retained-descendant result had contradictory Job evidence.",
    );
  }
  if (status.outcome === "cleanup-unproven") {
    requireCondition(
      !status.cleanupProven,
      "An unproven Windows cleanup result claimed proof.",
    );
  }
  if (status.outcome === "supervisor-failure") {
    requireCondition(
      status.terminationRequested,
      "A supervisor failure had contradictory Job evidence.",
    );
  }
}

export function readWindowsSupervisorStatus(protocol) {
  const status = readBoundedInvocationStatus(protocol);
  validateStatusShape(status, protocol);
  validateCleanupProof(status);
  validateOutcome(status);
  return status;
}
