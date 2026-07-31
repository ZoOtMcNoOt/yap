const CHECKED_HEAD = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const EXPECTED_DURATIONS_MS = Object.freeze([
  250,
  500,
  750,
  1_000,
  1_120,
  2_000,
  5_000,
  10_000,
  30_000,
]);
const MEASUREMENT_BOUNDARY = "desktop-prepared-audio-frame-to-final";
// This mirrors the frozen Rust queue contract so a capacity change invalidates
// stale evidence instead of silently changing its interpretation.
const EXPECTED_LOCAL_ASR_QUEUE_CAPACITY_FRAMES = 1_024;

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

export function validateTargetClientPreparedAudioEvidence(value, expected) {
  requireCondition(value && typeof value === "object" && !Array.isArray(value),
    "Prepared-audio evidence must be an object.");
  requireCondition(expected && typeof expected === "object" && !Array.isArray(expected),
    "Prepared-audio expected identity must be an object.");
  requireCondition(value.schemaVersion === 2, "Prepared-audio schemaVersion must be 2.");
  requireCondition(CHECKED_HEAD.test(value.checkedHead), "Prepared-audio checkedHead is invalid.");
  requireCondition(value.checkedHead === expected.checkedHead, "Prepared-audio head does not match.");
  requireCondition(
    SHA256.test(value.suiteSha256) && value.suiteSha256 === expected.suiteSha256,
    "Prepared-audio suite identity does not match.",
  );
  requireCondition(SHA256.test(value.planSha256), "Prepared-audio plan identity is invalid.");
  requireCondition(
    SHA256.test(value.modelArtifactLockSha256),
    "Prepared-audio model-lock identity is invalid.",
  );
  requireCondition(
    value.qualificationProfile === "short-boundaries",
    "Prepared-audio evidence must use the short-boundaries profile.",
  );
  requireCondition(
    value.measurementBoundary === MEASUREMENT_BOUNDARY,
    "Prepared-audio measurement boundary does not match.",
  );
  requireCondition(
    value.adapterDrainTargetMs === 6_000
      && value.adapterDrainTimeoutMs === 12_000,
    "Prepared-audio drain timing contract does not match.",
  );
  requireCondition(
    value.queueCapacityFrames === EXPECTED_LOCAL_ASR_QUEUE_CAPACITY_FRAMES,
    "Prepared-audio queue capacity does not match the frozen contract.",
  );
  requireCondition(
    Number.isSafeInteger(value.logicalProcessorBudget)
      && value.logicalProcessorBudget === expected.logicalProcessors,
    "Prepared-audio processor budget does not match the current target host.",
  );
  requireCondition(value.allCasesPassed === true, "Prepared-audio aggregate did not pass.");
  requireCondition(
    Array.isArray(value.cases) && value.cases.length === EXPECTED_DURATIONS_MS.length,
    "Prepared-audio evidence must contain exactly nine cases.",
  );

  value.cases.forEach((candidate, index) => {
    const durationMs = EXPECTED_DURATIONS_MS[index];
    const expectedFrames = durationMs / 10;
    const expectedSamples = durationMs * 16;
    const maximumObservableQueueDepth = Math.min(
      expectedFrames,
      value.queueCapacityFrames,
    );
    requireCondition(
      candidate.durationMs === durationMs
        && candidate.durationSamples === expectedSamples
        && candidate.expectedFrames === expectedFrames,
      `Prepared-audio case ${index + 1} does not match its frozen duration.`,
    );
    requireCondition(
      candidate.acceptedFrames === expectedFrames
        && candidate.droppedFrames === 0
        && candidate.processedAudioSamples === expectedSamples,
      `Prepared-audio case ${durationMs} ms did not preserve every source frame.`,
    );
    requireCondition(
      Number.isSafeInteger(candidate.queueHighWaterMark)
        && candidate.queueHighWaterMark >= 1
        && candidate.queueHighWaterMark <= maximumObservableQueueDepth,
      `Prepared-audio case ${durationMs} ms has an invalid queue high-water mark.`,
    );
    requireCondition(
      candidate.streamStatus === "completed"
        && candidate.passed === true
        && candidate.languageDegraded === false
        && candidate.transcriptionUnavailable === false,
      `Prepared-audio case ${durationMs} ms did not complete cleanly.`,
    );
    requireCondition(
      Number.isSafeInteger(candidate.adapterDrainMs)
        && candidate.adapterDrainMs >= 0
        && candidate.adapterStatus === "drained"
        && candidate.adapterDrainTargetMet === (
          candidate.adapterDrainMs <= value.adapterDrainTargetMs
        ),
      `Prepared-audio case ${durationMs} ms has inconsistent drain timing.`,
    );
    requireCondition(
      candidate.adapterDrainTargetMet === true,
      `Prepared-audio case ${durationMs} ms did not meet the drain target.`,
    );
    requireCondition(
      candidate.expectedText === (durationMs >= 1_000)
        && (durationMs < 1_000 || candidate.textSeen === true),
      `Prepared-audio case ${durationMs} ms did not satisfy its text boundary.`,
    );
  });

  return Object.freeze({
    caseCount: value.cases.length,
    checkedHead: value.checkedHead,
    measurementBoundary: value.measurementBoundary,
    suiteSha256: value.suiteSha256,
  });
}
