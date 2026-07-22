const SHA256 = /^[0-9a-f]{64}$/;
const CHECKED_HEAD = /^[0-9a-f]{40}$/;
const POWER_PLAN_GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const BOUNDED_LABEL = /^[A-Za-z0-9][A-Za-z0-9 ._+/@()-]{0,127}$/;
const MEASUREMENT_METHODS = new Set([
  "calibrated-external-meter+wpr",
  "windows-adk-energy-efficiency+wpr",
]);
const ALLOWED_KEYS = new Set([
  "activeEnergyOverheadPercent",
  "appBinarySha256",
  "baselineDurationMs",
  "candidateDurationMs",
  "checkedHead",
  "idlePackagePowerDeltaWatts",
  "measurementBoundary",
  "measurementMethod",
  "measurementToolVersion",
  "minimumThermalHeadroomC",
  "powerPlanGuid",
  "processorName",
  "rawEvidenceSha256",
  "schemaVersion",
  "stimulusSha256",
  "temperatureTelemetry",
  "thermalLimitSource",
  "thermalThrottlingObserved",
  "transcriptTextRecorded",
]);

export const TARGET_CLIENT_POWER_LIMITS = Object.freeze({
  maximumActiveEnergyOverheadPercent: 15,
  maximumIdlePackagePowerDeltaWatts: 0.5,
  minimumTrialDurationMs: 15 * 60_000,
  minimumThermalHeadroomC: 10,
});

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value;
}

function requireExactString(value, expected, label) {
  if (value !== expected) throw new Error(`${label} does not match the target-client run.`);
}

function requireBoundedNumber(value, minimum, maximum, label) {
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${label} must be between ${minimum} and ${maximum}.`);
  }
}

function requireBoundedInteger(value, minimum, maximum, label) {
  requireBoundedNumber(value, minimum, maximum, label);
  if (!Number.isSafeInteger(value)) throw new Error(`${label} must be an integer.`);
}

export function validateTargetClientPowerThermalEvidence(raw, expected) {
  const evidence = requireObject(raw, "Power/thermal evidence");
  const identity = requireObject(expected, "Expected target identity");
  const unknown = Object.keys(evidence).filter((key) => !ALLOWED_KEYS.has(key));
  if (unknown.length > 0) {
    throw new Error(`Power/thermal evidence contains unsupported fields: ${unknown.join(", ")}.`);
  }
  if (evidence.schemaVersion !== 1) throw new Error("Power/thermal schemaVersion must be 1.");
  if (!CHECKED_HEAD.test(evidence.checkedHead)) throw new Error("checkedHead must be a SHA-1.");
  if (!SHA256.test(evidence.appBinarySha256)) throw new Error("appBinarySha256 must be a SHA-256.");
  if (!SHA256.test(evidence.stimulusSha256)) throw new Error("stimulusSha256 must be a SHA-256.");
  requireExactString(evidence.checkedHead, identity.checkedHead, "checkedHead");
  requireExactString(evidence.processorName, identity.processorName, "processorName");
  requireExactString(evidence.appBinarySha256, identity.appBinarySha256, "appBinarySha256");
  requireExactString(evidence.stimulusSha256, identity.stimulusSha256, "stimulusSha256");
  requireExactString(
    evidence.measurementBoundary,
    "nemotron-only-vs-nemotron-plus-silero-ambernet",
    "measurementBoundary",
  );
  if (!MEASUREMENT_METHODS.has(evidence.measurementMethod)) {
    throw new Error("measurementMethod is not an accepted calibrated boundary.");
  }
  if (!BOUNDED_LABEL.test(evidence.measurementToolVersion)) {
    throw new Error("measurementToolVersion must be a bounded tool/version label.");
  }
  if (!POWER_PLAN_GUID.test(evidence.powerPlanGuid)) {
    throw new Error("powerPlanGuid must be a lowercase Windows power-plan GUID.");
  }
  if (evidence.temperatureTelemetry !== "measured") {
    throw new Error("temperatureTelemetry must be measured; unavailable telemetry cannot pass.");
  }
  if (!BOUNDED_LABEL.test(evidence.thermalLimitSource)) {
    throw new Error("thermalLimitSource must be a bounded platform source label.");
  }
  if (evidence.thermalThrottlingObserved !== false) {
    throw new Error("Thermal throttling was observed or not explicitly ruled out.");
  }
  if (evidence.transcriptTextRecorded !== false) {
    throw new Error("Power/thermal evidence must not retain transcript text.");
  }
  requireBoundedInteger(
    evidence.baselineDurationMs,
    TARGET_CLIENT_POWER_LIMITS.minimumTrialDurationMs,
    60 * 60_000,
    "baselineDurationMs",
  );
  requireBoundedInteger(
    evidence.candidateDurationMs,
    TARGET_CLIENT_POWER_LIMITS.minimumTrialDurationMs,
    60 * 60_000,
    "candidateDurationMs",
  );
  requireBoundedNumber(
    evidence.idlePackagePowerDeltaWatts,
    -10,
    TARGET_CLIENT_POWER_LIMITS.maximumIdlePackagePowerDeltaWatts,
    "idlePackagePowerDeltaWatts",
  );
  requireBoundedNumber(
    evidence.activeEnergyOverheadPercent,
    -100,
    TARGET_CLIENT_POWER_LIMITS.maximumActiveEnergyOverheadPercent,
    "activeEnergyOverheadPercent",
  );
  requireBoundedNumber(
    evidence.minimumThermalHeadroomC,
    TARGET_CLIENT_POWER_LIMITS.minimumThermalHeadroomC,
    200,
    "minimumThermalHeadroomC",
  );
  if (
    !Array.isArray(evidence.rawEvidenceSha256)
    || evidence.rawEvidenceSha256.length < 1
    || evidence.rawEvidenceSha256.length > 16
    || evidence.rawEvidenceSha256.some((digest) => !SHA256.test(digest))
    || new Set(evidence.rawEvidenceSha256).size !== evidence.rawEvidenceSha256.length
  ) {
    throw new Error("rawEvidenceSha256 must contain 1 to 16 unique lowercase SHA-256 values.");
  }

  return Object.freeze({
    ...evidence,
    rawEvidenceSha256: Object.freeze([...evidence.rawEvidenceSha256]),
  });
}
