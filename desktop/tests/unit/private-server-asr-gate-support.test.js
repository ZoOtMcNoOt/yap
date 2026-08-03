import { EventEmitter } from "node:events";
import { describe, expect, it } from "vitest";

import {
  canonicalPcm16Mono16KhzWav,
  isValidInFlightRemotePipeline,
  matchPublishedRemoteHistoryEntry,
  meetingCheckpointFixture,
  matchesEnabledLoopbackServerSettings,
  matchesVerifiedHistoryDialog,
  resolvePrivateServerAsrGateTimeout,
  sameWindowsPath,
  settleSshTunnelChild,
} from "../wdio/private-server-asr-gate-support.js";

describe("private-server ASR gate support", () => {
  it("supplies the bounded default timeout when the operator does not override it", () => {
    expect(resolvePrivateServerAsrGateTimeout(undefined)).toBe(2_700_000);
  });

  it("treats Windows case and extended-length prefixes as the same path", () => {
    expect(sameWindowsPath("C:\\Private\\Evidence", "\\\\?\\c:\\private\\evidence\\")).toBe(true);
  });

  it("requires the current enabled loopback server-settings contract", () => {
    const origin = "http://127.0.0.1:18765";
    const settings = {
      schemaVersion: 2,
      enabled: true,
      baseUrl: origin,
      authentication: null,
    };

    expect(matchesEnabledLoopbackServerSettings(settings, origin)).toBe(true);
    expect(matchesEnabledLoopbackServerSettings(
      { ...settings, schemaVersion: 1 },
      origin,
    )).toBe(false);
    expect(matchesEnabledLoopbackServerSettings(
      { ...settings, authentication: { mode: "entra" } },
      origin,
    )).toBe(false);
    expect(matchesEnabledLoopbackServerSettings(
      { ...settings, unexpected: true },
      origin,
    )).toBe(false);
    expect(matchesEnabledLoopbackServerSettings(
      settings,
      "http://127.0.0.1:18766",
    )).toBe(false);
  });

  it("builds a canonical bounded multi-window meeting fixture", () => {
    const sourcePcm = Buffer.from([1, 0, 2, 0, 3, 0, 4, 0]);
    const fixture = meetingCheckpointFixture(sourcePcm, 60);

    expect(fixture.length).toBe(44 + 60 * 16_000 * 2);
    expect(fixture.toString("ascii", 0, 4)).toBe("RIFF");
    expect(fixture.toString("ascii", 8, 12)).toBe("WAVE");
    expect(fixture.readUInt32LE(40)).toBe(60 * 16_000 * 2);
    expect(fixture.subarray(44, 52)).toEqual(sourcePcm);
    expect(() => meetingCheckpointFixture(sourcePcm, 59)).toThrow(
      /between 60 and 120 seconds/,
    );
    expect(() => canonicalPcm16Mono16KhzWav(Buffer.alloc(3))).toThrow(
      /whole signed-16 samples/,
    );
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

  it("joins the created remote job identity to its completed History entry", () => {
    const createdJob = {
      id: "job-0123456789abcdef01234567",
      route: "serverBatch",
      sourcePath: "C:\\fixture.wav",
      status: "preflighting",
      pipeline: {
        intake: "done",
        preprocessing: "running",
        transcription: "notStarted",
        alignment: "notStarted",
        diarization: "notStarted",
        postprocessing: "notStarted",
      },
    };
    const historyEntry = {
      name: "fixture.wav",
      origin: "remote",
      outputPath: "C:\\Yap\\remote-jobs\\job-0123456789abcdef01234567\\result-1\\transcript.txt",
      sessionId: "s-0123456789abcdef01234567",
      sourcePath: "\\\\?\\c:\\fixture.wav",
    };
    const matched = matchPublishedRemoteHistoryEntry(
      createdJob,
      {
        maintenanceWarnings: [],
        sessions: [historyEntry],
      },
    );

    expect(matched).toBe(historyEntry);
    expect(matchPublishedRemoteHistoryEntry(
      { ...createdJob, route: "localFallback" },
      { maintenanceWarnings: [], sessions: [historyEntry] },
    )).toBeUndefined();
    expect(matchPublishedRemoteHistoryEntry(
      { ...createdJob, id: "job-not-a-minted-id" },
      { maintenanceWarnings: [], sessions: [historyEntry] },
    )).toBeUndefined();
    expect(matchPublishedRemoteHistoryEntry(
      createdJob,
      { maintenanceWarnings: [], sessions: [{ ...historyEntry, sessionId: "s-other" }] },
    )).toBeUndefined();
    expect(matchPublishedRemoteHistoryEntry(
      createdJob,
      { maintenanceWarnings: [], sessions: [{ ...historyEntry, sourcePath: "C:\\other.wav" }] },
    )).toBeUndefined();
    expect(matchPublishedRemoteHistoryEntry(
      createdJob,
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

  it("settles SSH tunnel children gracefully before requesting force", async () => {
    const child = new EventEmitter();
    child.exitCode = null;
    child.signalCode = null;
    child.kill = (signal) => {
      expect(signal).toBeUndefined();
      queueMicrotask(() => {
        child.exitCode = 0;
        child.emit("exit", 0, null);
      });
      return true;
    };

    await expect(settleSshTunnelChild(child, {
      gracefulTimeoutMs: 100,
      forceTimeoutMs: 100,
    })).resolves.toEqual({ forceKillRequested: false });
  });

  it("force-settles an SSH tunnel child that ignores graceful termination", async () => {
    const child = new EventEmitter();
    child.exitCode = null;
    child.signalCode = null;
    const signals = [];
    child.kill = (signal) => {
      signals.push(signal ?? "graceful");
      if (signal === "SIGKILL") {
        queueMicrotask(() => {
          child.signalCode = "SIGKILL";
          child.emit("exit", null, "SIGKILL");
        });
      }
      return true;
    };

    await expect(settleSshTunnelChild(child, {
      gracefulTimeoutMs: 5,
      forceTimeoutMs: 100,
    })).resolves.toEqual({ forceKillRequested: true });
    expect(signals).toEqual(["graceful", "SIGKILL"]);
  });

  it("fails closed when forced SSH tunnel settlement cannot be proven", async () => {
    const child = new EventEmitter();
    child.exitCode = null;
    child.signalCode = null;
    child.kill = () => true;

    await expect(settleSshTunnelChild(child, {
      gracefulTimeoutMs: 5,
      forceTimeoutMs: 5,
    })).rejects.toMatchObject({
      code: "PRIVATE_SERVER_SSH_TUNNEL_CLEANUP_UNPROVEN",
    });
  });
});
