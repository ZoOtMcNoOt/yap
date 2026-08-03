import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TranscriptResultSummaryLine } from "@/components/transcript-result-summary";
import { HistoryEntryPreview } from "@/components/panels/history-entry-preview";
import {
  isTranscriptResultSummary,
  transcriptResultSummaryLabels,
} from "@/lib/transcript-result-summary";

describe("transcript result summary", () => {
  it("validates compatible language modes and canonical locale formatting", () => {
    expect(isTranscriptResultSummary({
      languageBcp47: "zh-Hant-TW",
      languageStatus: "fixed",
      timingStatus: "available",
    })).toBe(true);
    expect(isTranscriptResultSummary({
      languageBcp47: "en-US",
      languageStatus: "dynamic",
      timingStatus: "available",
    })).toBe(false);
    expect(isTranscriptResultSummary({
      languageBcp47: "en-us",
      languageStatus: "fixed",
      timingStatus: "available",
    })).toBe(false);
  });

  it("uses explicit labels for unknown language segments and unavailable timing", () => {
    expect(transcriptResultSummaryLabels({
      languageBcp47: "und",
      languageStatus: "unknownSegments",
      timingStatus: "unavailable",
    })).toEqual({
      corrections: undefined,
      language: "Language: some segments need review",
      timing: "Word timing unavailable",
    });
    expect(isTranscriptResultSummary({
      languageBcp47: "und",
      languageStatus: "unknownSegments",
      timingStatus: "legacyUnknown",
    })).toBe(false);
  });

  it("exposes correction and pending-review counts as non-color text", () => {
    expect(transcriptResultSummaryLabels({
      activeLanguageCorrectionCount: 2,
      languageBcp47: "und",
      languageReviewRequiredCount: 0,
      languageStatus: "dynamic",
      timingStatus: "available",
    }).corrections).toBe("2 language labels corrected");
    expect(isTranscriptResultSummary({
      activeLanguageCorrectionCount: -1,
      languageBcp47: "und",
      languageStatus: "dynamic",
      timingStatus: "available",
    })).toBe(false);
  });

  it("renders plain, non-color-only result details in the shared review projection", () => {
    const summary = {
      languageBcp47: "und",
      languageStatus: "dynamic" as const,
      timingStatus: "unavailable" as const,
    };
    const line = renderToStaticMarkup(<TranscriptResultSummaryLine summary={summary} />);
    const history = renderToStaticMarkup(
      <HistoryEntryPreview
        entry={{
          createdAt: "2026-07-18T00:00:00.000Z",
          name: "Global meeting",
          outputPath: "C:/Yap/remote.txt",
          resultSummary: summary,
          sourcePath: "C:/Yap/source.wav",
        }}
      />,
    );

    expect(line).toContain('aria-label="Transcript result details"');
    expect(line).toContain("Language: automatic per segment · Word timing unavailable");
    expect(history).toContain("Language: automatic per segment");
    expect(history).toContain("Word timing unavailable");
  });
});
