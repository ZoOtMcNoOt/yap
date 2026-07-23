import { describe, expect, it } from "vitest";

import {
  isValidInFlightRemotePipeline,
  matchCompletedRemoteTranscript,
  matchesVerifiedHistoryDialog,
  resolvePrivateServerAsrGateTimeout,
  sameWindowsPath,
} from "../wdio/private-server-asr-gate-support.js";

describe("private-server ASR gate support", () => {
  it("supplies the bounded default timeout when the operator does not override it", () => {
    expect(resolvePrivateServerAsrGateTimeout(undefined)).toBe(2_700_000);
  });

  it("treats Windows case and extended-length prefixes as the same path", () => {
    expect(sameWindowsPath("C:\\Private\\Evidence", "\\\\?\\c:\\private\\evidence\\")).toBe(true);
  });

  it("accepts every legitimate in-flight server pipeline projection", () => {
    const pipeline = {
      intake: "done",
      preprocessing: "notStarted",
      transcription: "notStarted",
      alignment: "notStarted",
      diarization: "notStarted",
      postprocessing: "notStarted",
    };
    const job = {
      route: "serverBatch",
      status: "queued_server",
      pipeline,
    };
    const expectedStages = new Map([
      ["queued_server", ["notStarted", "notStarted"]],
      ["preflighting", ["running", "notStarted"]],
      ["preprocessing", ["running", "notStarted"]],
      ["uploading", ["done", "notStarted"]],
      ["server_processing", ["done", "running"]],
    ]);

    for (const [status, [preprocessing, transcription]] of expectedStages) {
      expect(isValidInFlightRemotePipeline({
        ...job,
        status,
        pipeline: { ...pipeline, preprocessing, transcription },
      })).toBe(true);
    }
    expect(isValidInFlightRemotePipeline({
      ...job,
      status: "preflighting",
      pipeline,
    })).toBe(false);
    expect(isValidInFlightRemotePipeline({
      ...job,
      status: "complete",
      pipeline: { ...pipeline, preprocessing: "done", transcription: "done" },
    })).toBe(false);
  });

  it("joins only a fully processed remote job to its terminal History entry", () => {
    const completedJob = {
      id: "job-0123456789abcdef01234567",
      route: "serverBatch",
      sourcePath: "C:\\fixture.wav",
      status: "complete",
      pipeline: {
        intake: "done",
        preprocessing: "done",
        transcription: "done",
        alignment: "notStarted",
        diarization: "notStarted",
        postprocessing: "done",
      },
    };
    const historyEntry = {
      name: "fixture.wav",
      origin: "remote",
      outputPath: "C:\\Yap\\remote-jobs\\job-0123456789abcdef01234567\\result-1\\transcript.txt",
      sessionId: "s-0123456789abcdef01234567",
      sourcePath: "\\\\?\\c:\\fixture.wav",
    };
    const matched = matchCompletedRemoteTranscript(
      completedJob,
      {
        maintenanceWarnings: [],
        sessions: [historyEntry],
      },
    );

    expect(matched).toBe(historyEntry);
    expect(matchCompletedRemoteTranscript(
      { ...completedJob, status: "queued_server" },
      { maintenanceWarnings: [], sessions: [historyEntry] },
    )).toBeUndefined();
    for (const stage of ["intake", "preprocessing", "transcription", "postprocessing"]) {
      expect(matchCompletedRemoteTranscript(
        {
          ...completedJob,
          pipeline: { ...completedJob.pipeline, [stage]: "running" },
        },
        { maintenanceWarnings: [], sessions: [historyEntry] },
      )).toBeUndefined();
    }
    expect(matchCompletedRemoteTranscript(
      { ...completedJob, route: "localFallback" },
      { maintenanceWarnings: [], sessions: [historyEntry] },
    )).toBeUndefined();
    expect(matchCompletedRemoteTranscript(
      { ...completedJob, id: "job-not-a-minted-id" },
      { maintenanceWarnings: [], sessions: [historyEntry] },
    )).toBeUndefined();
    expect(matchCompletedRemoteTranscript(
      completedJob,
      { maintenanceWarnings: [], sessions: [{ ...historyEntry, sessionId: "s-other" }] },
    )).toBeUndefined();
    expect(matchCompletedRemoteTranscript(
      completedJob,
      { maintenanceWarnings: [], sessions: [{ ...historyEntry, sourcePath: "C:\\other.wav" }] },
    )).toBeUndefined();
    expect(matchCompletedRemoteTranscript(
      completedJob,
      { maintenanceWarnings: [], sessions: [{ ...historyEntry, origin: "live" }] },
    )).toBeUndefined();
  });

  it("recognizes the exact verified transcript dialog without requiring the table behind it", () => {
    const name = "fixture.wav";
    const transcript = "Verified server transcript.";

    expect(matchesVerifiedHistoryDialog(
      [{ label: name, transcript }],
      name,
      transcript,
    )).toBe(true);
    expect(matchesVerifiedHistoryDialog(
      [{ label: "other.wav", transcript }],
      name,
      transcript,
    )).toBe(false);
    expect(matchesVerifiedHistoryDialog(
      [{ label: name, transcript: "Different text." }],
      name,
      transcript,
    )).toBe(false);
  });
});
