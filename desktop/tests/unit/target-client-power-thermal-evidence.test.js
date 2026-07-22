import { describe, expect, it } from "vitest";

import {
  TARGET_CLIENT_POWER_LIMITS,
  validateTargetClientPowerThermalEvidence,
} from "../wdio/target-client-power-thermal-evidence.js";

const identity = {
  appBinarySha256: "a".repeat(64),
  checkedHead: "b".repeat(40),
  processorName: "11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz",
  stimulusSha256: "c".repeat(64),
};

function validEvidence() {
  return {
    activeEnergyOverheadPercent: 15,
    appBinarySha256: identity.appBinarySha256,
    baselineDurationMs: TARGET_CLIENT_POWER_LIMITS.minimumTrialDurationMs,
    candidateDurationMs: TARGET_CLIENT_POWER_LIMITS.minimumTrialDurationMs,
    checkedHead: identity.checkedHead,
    idlePackagePowerDeltaWatts: 0.5,
    measurementBoundary: "nemotron-only-vs-nemotron-plus-silero-ambernet",
    measurementMethod: "windows-adk-energy-efficiency+wpr",
    measurementToolVersion: "Windows ADK 10.1 plus WPR 10.1",
    minimumThermalHeadroomC: 10,
    powerPlanGuid: "381b4222-f694-41f0-9685-ff5bb260df2e",
    processorName: identity.processorName,
    rawEvidenceSha256: ["d".repeat(64), "e".repeat(64)],
    schemaVersion: 1,
    stimulusSha256: identity.stimulusSha256,
    temperatureTelemetry: "measured",
    thermalLimitSource: "OEM EC sensor and platform TjMax",
    thermalThrottlingObserved: false,
    transcriptTextRecorded: false,
  };
}

describe("target-client power and thermal evidence", () => {
  it("accepts a matched threshold-edge aggregate", () => {
    expect(validateTargetClientPowerThermalEvidence(validEvidence(), identity))
      .toMatchObject({ schemaVersion: 1, thermalThrottlingObserved: false });
  });

  it("rejects CPU-only or unavailable thermal claims", () => {
    const evidence = validEvidence();
    evidence.temperatureTelemetry = "unavailable";
    expect(() => validateTargetClientPowerThermalEvidence(evidence, identity))
      .toThrow(/cannot pass/i);
  });

  it("rejects excessive energy, insufficient duration, and thermal throttling", () => {
    for (const patch of [
      { activeEnergyOverheadPercent: 15.01 },
      { baselineDurationMs: TARGET_CLIENT_POWER_LIMITS.minimumTrialDurationMs - 1 },
      { candidateDurationMs: TARGET_CLIENT_POWER_LIMITS.minimumTrialDurationMs + 0.5 },
      { minimumThermalHeadroomC: 9.99 },
      { thermalThrottlingObserved: true },
    ]) {
      expect(() => validateTargetClientPowerThermalEvidence(
        { ...validEvidence(), ...patch },
        identity,
      )).toThrow();
    }
  });

  it("rejects mismatched identities, unknown fields, and duplicate raw receipts", () => {
    expect(() => validateTargetClientPowerThermalEvidence(
      { ...validEvidence(), checkedHead: "f".repeat(40) },
      identity,
    )).toThrow(/does not match/i);
    expect(() => validateTargetClientPowerThermalEvidence(
      { ...validEvidence(), rawPath: "C:/private/result.etl" },
      identity,
    )).toThrow(/unsupported fields/i);
    expect(() => validateTargetClientPowerThermalEvidence(
      { ...validEvidence(), rawEvidenceSha256: ["d".repeat(64), "d".repeat(64)] },
      identity,
    )).toThrow(/unique/i);
  });
});
