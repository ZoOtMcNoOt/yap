import { describe, expect, it } from "vitest";

import { validateTargetClientNativeResourceEvidence } from "../wdio/target-client-native-resource-evidence.js";

const expected = {
  checkedHead: "a".repeat(40),
  logicalProcessors: 8,
  processorName: "11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz",
};

function validContext() {
  return {
    audioFixturePathRecorded: false,
    audioFixtureSha256: "b".repeat(64),
    boundary: "desktop-prepared-audio-frame-to-final-resource-profile",
    checkedHead: expected.checkedHead,
    exclusions: ["physical-microphone", "rendered-ui", "energy", "thermal"],
    expectedLogicalProcessors: 8,
    expectedProcessorToken: "i5-1135G7",
    logSha256: "c".repeat(64),
    logicalProcessors: 8,
    modelsDirectoryRecorded: false,
    processorName: expected.processorName,
    profileSha256: "d".repeat(64),
    schemaVersion: 1,
    sessionCycles: 12,
    status: "passed",
  };
}

function validProfile() {
  return {
    audioFixtureSha256: "b".repeat(64),
    combinedRealTimeGatePassed: true,
    localAsrThreads: 2,
    logicalProcessorBudget: 8,
    paced: { pacedGatePassed: true },
    schemaVersion: 5,
    sustained: {
      allCyclesPassed: true,
      completedCycles: 12,
      memoryPlateauGatePassed: true,
      privateByteGrowthLimit: 64 * 1024 * 1024,
      requestedCycles: 12,
      sustainedGatePassed: true,
    },
  };
}

describe("target-client native resource evidence", () => {
  it("accepts the exact frozen target contract", () => {
    expect(validateTargetClientNativeResourceEvidence(
      validContext(),
      validProfile(),
      expected,
    )).toMatchObject({ sessionCycles: 12, logicalProcessors: 8 });
  });

  it("rejects relaxed CPU, thread, or cycle settings", () => {
    for (const [contextPatch, profilePatch] of [
      [{ expectedProcessorToken: "Intel" }, {}],
      [{ sessionCycles: 2 }, { sustained: { ...validProfile().sustained, requestedCycles: 2 } }],
      [{}, { localAsrThreads: 8 }],
    ]) {
      expect(() => validateTargetClientNativeResourceEvidence(
        { ...validContext(), ...contextPatch },
        { ...validProfile(), ...profilePatch },
        expected,
      )).toThrow();
    }
  });

  it("rejects private-path claims, missing receipts, and failed resource gates", () => {
    expect(() => validateTargetClientNativeResourceEvidence(
      { ...validContext(), modelsDirectoryRecorded: true },
      validProfile(),
      expected,
    )).toThrow(/private source path/i);
    expect(() => validateTargetClientNativeResourceEvidence(
      { ...validContext(), logSha256: null },
      validProfile(),
      expected,
    )).toThrow(/log identity/i);
    expect(() => validateTargetClientNativeResourceEvidence(
      validContext(),
      {
        ...validProfile(),
        sustained: { ...validProfile().sustained, memoryPlateauGatePassed: false },
      },
      expected,
    )).toThrow(/memory plateau/i);
  });
});
