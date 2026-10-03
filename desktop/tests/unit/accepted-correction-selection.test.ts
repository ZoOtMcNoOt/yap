import { beforeEach, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
import { readAcceptedTranscriptCorrection, exportAcceptedTranscriptCorrection } from "@/transcript-correction";

const path = "/recordings/transcript.txt";
const receipt = (number = 2) => ({
  schemaVersion: 1, outputPath: path, sourceRevisionSha256: "a".repeat(64),
  sourceSha256: "b".repeat(64), revisionCount: 2,
  acceptedRevision: {
    requestId: `accepted-${number}`, revision: number,
    sourceRevisionSha256: "a".repeat(64), sourceSha256: "b".repeat(64),
    terminologySnapshotSha256: "c".repeat(64), correctedSha256: "d".repeat(64),
    correctedText: "Reviewed café — 日本語🦀", revisionPath: `/saved/correction-${number}.json`,
  },
});

beforeEach(() => { invokeMock.mockReset(); });

it("opens latest by default and sends an explicit earlier revision without changing text", async () => {
  invokeMock.mockResolvedValue(receipt());
  expect(await readAcceptedTranscriptCorrection(path)).toEqual(receipt());
  expect(invokeMock).toHaveBeenLastCalledWith("read_accepted_transcript_correction", {outputPath: path, revision: null});
  invokeMock.mockResolvedValue(receipt(1));
  expect(await readAcceptedTranscriptCorrection(path, 1)).toEqual(receipt(1));
  expect(invokeMock).toHaveBeenLastCalledWith("read_accepted_transcript_correction", {outputPath: path, revision: 1});
});

it("rejects a substituted revision, source, count or malformed accepted record", async () => {
  for (const value of [
    receipt(2), {...receipt(1), outputPath: "/another/transcript.txt"},
    ...[-1, 0, 1, 65, true, undefined].map(revisionCount => ({...receipt(2), revisionCount})),
    {...receipt(1), acceptedRevision: {...receipt(1).acceptedRevision, sourceSha256: "e".repeat(64)}},
    {...receipt(1), acceptedRevision: null},
  ]) {
    invokeMock.mockResolvedValue(value);
    await expect(readAcceptedTranscriptCorrection(path, 1)).rejects.toThrow();
  }
});

it("empty history remains usable but invalid or missing explicit selections are refused", async () => {
  invokeMock.mockResolvedValue({...receipt(), revisionCount: 0, acceptedRevision: null});
  expect((await readAcceptedTranscriptCorrection(path)).acceptedRevision).toBeNull();
  await expect(readAcceptedTranscriptCorrection(path, 1)).rejects.toThrow();
  invokeMock.mockClear();
  for (const revision of [0, -1, 65, 1.5, Number.NaN]) {
    await expect(readAcceptedTranscriptCorrection(path, revision)).rejects.toThrow();
  }
  expect(invokeMock).not.toHaveBeenCalled();
});

it("exports only the selected earlier revision and rejects a substituted saved receipt", async () => {
  const selected = receipt(1).acceptedRevision;
  invokeMock.mockResolvedValue({status: "saved", path: "/review/earlier.txt", revision: 1, correctedSha256: selected.correctedSha256});
  expect((await exportAcceptedTranscriptCorrection(path, selected)).status).toBe("saved");
  expect(invokeMock).toHaveBeenLastCalledWith("export_accepted_transcript_correction", {outputPath: path, revision: 1, correctedSha256: selected.correctedSha256});
  invokeMock.mockResolvedValue({status: "saved", path: "/review/latest.txt", revision: 2, correctedSha256: selected.correctedSha256});
  await expect(exportAcceptedTranscriptCorrection(path, selected)).rejects.toThrow("did not match");
});
