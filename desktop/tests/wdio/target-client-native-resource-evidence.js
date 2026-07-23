const SHA256 = /^[0-9a-f]{64}$/;
const CHECKED_HEAD = /^[0-9a-f]{40}$/;
const PROCESSOR_TOKEN = /^[A-Za-z0-9()@._ +\-]{3,128}$/;
const TARGET_ASR_THREADS = 2;
const TARGET_SESSION_CYCLES = 12;
const PRIVATE_BYTE_GROWTH_LIMIT = 64 * 1024 * 1024;
const BOUNDARY = "desktop-prepared-audio-frame-to-final-resource-profile";
const EXCLUSIONS = Object.freeze(["physical-microphone", "rendered-ui", "energy", "thermal"]);
const CONTEXT_KEYS = new Set([
  "audioFixturePathRecorded",
  "audioFixtureSha256",
  "boundary",
  "checkedHead",
  "exclusions",
  "logSha256",
  "logicalProcessorBudget",
  "logicalProcessors",
  "modelsDirectoryRecorded",
  "processorConstraint",
  "processorName",
  "profileSha256",
  "schemaVersion",
  "sessionCycles",
  "status",
]);

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value;
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

export function validateTargetClientNativeResourceEvidence(contextValue, profileValue, expectedValue) {
  const context = requireObject(contextValue, "Native resource context");
  const profile = requireObject(profileValue, "Native resource profile");
  const expected = requireObject(expectedValue, "Expected target identity");
  const unknown = Object.keys(context).filter((key) => !CONTEXT_KEYS.has(key));
  requireCondition(
    unknown.length === 0,
    `Native resource context contains unsupported fields: ${unknown.join(", ")}.`,
  );
  requireCondition(context.schemaVersion === 2, "Native resource context schemaVersion must be 2.");
  requireCondition(context.status === "passed", "Native resource context is not passed.");
  requireCondition(CHECKED_HEAD.test(context.checkedHead), "Native resource checkedHead must be a SHA-1.");
  requireCondition(context.checkedHead === expected.checkedHead, "Native resource head does not match.");
  requireCondition(context.processorName === expected.processorName, "Native resource processor does not match.");
  requireCondition(
    context.processorConstraint === null
      || (
        PROCESSOR_TOKEN.test(context.processorConstraint)
        && context.processorName.toLowerCase().includes(context.processorConstraint.toLowerCase())
      ),
    "Native resource evidence does not satisfy its optional processor constraint.",
  );
  requireCondition(
    Number.isSafeInteger(context.logicalProcessors)
      && context.logicalProcessors >= 1
      && context.logicalProcessors <= 256
      && context.logicalProcessorBudget === context.logicalProcessors
      && context.logicalProcessors === expected.logicalProcessors,
    "Native resource evidence does not match the recorded logical-processor budget.",
  );
  requireCondition(
    context.sessionCycles === TARGET_SESSION_CYCLES,
    "Native resource evidence must contain exactly 12 repeated sessions.",
  );
  requireCondition(context.boundary === BOUNDARY, "Native resource boundary does not match.");
  requireCondition(
    JSON.stringify(context.exclusions) === JSON.stringify(EXCLUSIONS),
    "Native resource exclusions do not match the prepared-audio boundary.",
  );
  requireCondition(
    context.modelsDirectoryRecorded === false && context.audioFixturePathRecorded === false,
    "Native resource context recorded a private source path.",
  );
  requireCondition(SHA256.test(context.audioFixtureSha256), "Audio fixture identity must be a SHA-256.");
  requireCondition(SHA256.test(context.profileSha256), "Profile identity must be a SHA-256.");
  requireCondition(SHA256.test(context.logSha256), "Log identity must be a SHA-256.");

  requireCondition(profile.schemaVersion === 5, "Native resource profile schemaVersion must be 5.");
  requireCondition(
    profile.audioFixtureSha256 === context.audioFixtureSha256,
    "Native profile and context disagree on the audio fixture.",
  );
  requireCondition(
    profile.logicalProcessorBudget === context.logicalProcessorBudget,
    "Native profile processor budget does not match the recorded host.",
  );
  requireCondition(
    profile.localAsrThreads === TARGET_ASR_THREADS,
    "Native profile must use exactly two local ASR threads.",
  );
  requireCondition(profile.combinedRealTimeGatePassed === true, "Combined local inference missed real time.");
  requireCondition(profile.paced?.pacedGatePassed === true, "The paced local resource gate failed.");
  requireCondition(
    profile.sustained?.requestedCycles === TARGET_SESSION_CYCLES
      && profile.sustained?.completedCycles === TARGET_SESSION_CYCLES
      && profile.sustained?.allCyclesPassed === true,
    "The sustained profile did not complete all 12 sessions.",
  );
  requireCondition(
    profile.sustained?.privateByteGrowthLimit === PRIVATE_BYTE_GROWTH_LIMIT
      && profile.sustained?.memoryPlateauGatePassed === true
      && profile.sustained?.sustainedGatePassed === true,
    "The sustained profile did not satisfy the frozen memory plateau.",
  );

  return Object.freeze({
    audioFixtureSha256: context.audioFixtureSha256,
    checkedHead: context.checkedHead,
    logicalProcessors: context.logicalProcessors,
    processorName: context.processorName,
    sessionCycles: context.sessionCycles,
  });
}
