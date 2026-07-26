import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({
  invoke,
  isTauri: () => true,
}));

import { LanguageLabelCorrectionRow } from "@/components/language-label-corrections";
import {
  loadLanguageLabelReview,
  saveLanguageLabelCorrection,
} from "@/history-catalog";
import type { TranscriptHistoryEntry } from "@/history-model";

const entry: TranscriptHistoryEntry = {
  createdAt: "2026-07-18T00:00:00.000Z",
  name: "Global meeting",
  origin: "remote",
  outputPath: "C:/Yap/remote-jobs/job/result-00000000000000000001/transcript.txt",
  sessionId: "session-global-meeting",
  sourcePath: "C:/Yap/source.wav",
};

describe("language-label corrections", () => {
  beforeEach(() => {
    invoke.mockReset();
  });

  it("binds review and correction commands to the native remote-history identity", async () => {
    invoke.mockResolvedValue({ revision: 0 });

    await loadLanguageLabelReview(entry);
    await saveLanguageLabelCorrection(entry, 4, 7, "fr-FR");

    expect(invoke).toHaveBeenNthCalledWith(1, "history_language_label_review", {
      identity: {
        origin: "remote",
        outputPath: entry.outputPath,
        sessionId: entry.sessionId,
      },
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "history_append_language_label_correction", {
      expectedRevision: 4,
      identity: {
        origin: "remote",
        outputPath: entry.outputPath,
        sessionId: entry.sessionId,
      },
      replacementLanguageBcp47: "fr-FR",
      segmentIndex: 7,
    });
  });

  it("renders explicit labels and status text instead of color-only correction state", () => {
    const markup = renderToStaticMarkup(
      <LanguageLabelCorrectionRow
        disabled={false}
        languageOptions={[{ languageBcp47: "fr-FR", qualityTier: "transcriptionReady" }]}
        onSave={async () => undefined}
        segment={{
          effectiveLanguageBcp47: null,
          hasUserCorrection: false,
          index: 1,
          sourceLanguageBcp47: null,
          sourceSpanIndex: 0,
          sourceStatus: "unknown",
          text: "bonjour",
        }}
      />,
    );

    expect(markup).toContain("Language for transcript segment 2");
    expect(markup).toContain("Language needs review");
    expect(markup).toContain("Save label");
  });
});
