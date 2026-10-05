import { beforeEach, expect, it, vi } from "vitest";
import { exportSpeakerTranscript } from "@/speaker-transcript-export";
const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
const identity = {
  outputPath: "owned/transcript.txt",
  sessionId: "s-transcript",
  sourceResultSha256: "a".repeat(64),
};
beforeEach(() => invoke.mockReset());
it("sends only native source identity and accepts its confirmed saved receipt", async () => {
  const receipt = {
    status: "saved",
    path: "/exports/timed.json",
    sessionId: identity.sessionId,
    sourceResultSha256: identity.sourceResultSha256,
  };
  invoke.mockResolvedValue(receipt);
  expect(await exportSpeakerTranscript(identity)).toEqual(receipt);
  expect(invoke).toHaveBeenCalledWith("export_speaker_transcript", identity);
});
it("preserves an explicitly cancelled picker", async () => {
  invoke.mockResolvedValue({ status: "cancelled" });
  expect(await exportSpeakerTranscript(identity)).toEqual({
    status: "cancelled",
  });
});
it.each([
  null,
  { status: "finished" },
  { status: "saved" },
  { status: "saved", path: " ", ...identity },
  {
    status: "saved",
    path: "/exports/timed.json",
    sessionId: "foreign",
    sourceResultSha256: identity.sourceResultSha256,
  },
  {
    status: "saved",
    path: "/exports/timed.json",
    sessionId: identity.sessionId,
    sourceResultSha256: "b".repeat(64),
  },
])(
  "refuses mismatching or incomplete receipt %# with retained write uncertainty",
  async (receipt) => {
    invoke.mockResolvedValue(receipt);
    await expect(exportSpeakerTranscript(identity)).rejects.toThrow(
      "file may already have been saved",
    );
  },
);
