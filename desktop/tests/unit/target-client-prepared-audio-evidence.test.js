import { describe, expect, it } from "vitest";

import { validateTargetClientPreparedAudioEvidence } from "../wdio/target-client-prepared-audio-evidence.js";

const durations = [250, 500, 750, 1_000, 1_120, 2_000, 5_000, 10_000, 30_000];
const expected = {
  checkedHead: "a".repeat(40),
  logicalProcessors: 8,
  suiteSha256: "b".repeat(64),
};

function validEvidence() {
  return {
    allCasesPassed: true,
    cases: durations.map((durationMs) => ({
      acceptedFrames: durationMs / 10,
      droppedFrames: 0,
      durationMs,
      durationSamples: durationMs * 16,
      expectedFrames: durationMs / 10,
      expectedText: durationMs >= 1_000,
      languageDegraded: false,
      passed: true,
      processedAudioSamples: durationMs * 16,
      streamStatus: "completed",
      textSeen: durationMs >= 1_000,
      transcriptionUnavailable: false,
    })),
    checkedHead: expected.checkedHead,
    logicalProcessorBudget: expected.logicalProcessors,
    measurementBoundary: "desktop-prepared-audio-frame-to-final",
    modelArtifactLockSha256: "c".repeat(64),
    planSha256: "d".repeat(64),
    qualificationProfile: "short-boundaries",
    schemaVersion: 2,
    suiteSha256: expected.suiteSha256,
  };
}

describe("target-client prepared-audio evidence", () => {
  it("accepts the exact checked-head nine-case speech boundary", () => {
    expect(validateTargetClientPreparedAudioEvidence(validEvidence(), expected)).toEqual({
      caseCount: 9,
      checkedHead: expected.checkedHead,
      measurementBoundary: "desktop-prepared-audio-frame-to-final",
      suiteSha256: expected.suiteSha256,
    });
  });

  it("rejects a missing case, stale head, frame loss, or missing required text", () => {
    const cases = [
      { ...validEvidence(), checkedHead: "e".repeat(40) },
      { ...validEvidence(), cases: validEvidence().cases.slice(0, 8) },
      {
        ...validEvidence(),
        cases: validEvidence().cases.map((candidate, index) => (
          index === 4 ? { ...candidate, droppedFrames: 1 } : candidate
        )),
      },
      {
        ...validEvidence(),
        cases: validEvidence().cases.map((candidate, index) => (
          index === 3 ? { ...candidate, textSeen: false } : candidate
        )),
      },
    ];
    for (const candidate of cases) {
      expect(() => validateTargetClientPreparedAudioEvidence(candidate, expected)).toThrow();
    }
  });
});
