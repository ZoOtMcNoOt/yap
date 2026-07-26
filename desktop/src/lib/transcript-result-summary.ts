import { formatLanguageTag } from "@/lib/language-display";

export type TranscriptLanguageStatus = "fixed" | "dynamic" | "unknownSegments";
export type TranscriptTimingStatus = "available" | "unavailable" | "legacyUnknown";

export type TranscriptResultSummary = {
  activeLanguageCorrectionCount?: number;
  languageBcp47: string;
  languageReviewRequiredCount?: number;
  languageStatus: TranscriptLanguageStatus;
  timingStatus: TranscriptTimingStatus;
};

const bcp47Pattern = /^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|\d{3}))?(?:-(?:[A-Za-z0-9]{5,8}|\d[A-Za-z0-9]{3}))*$/;

export function isTranscriptResultSummary(value: unknown): value is TranscriptResultSummary {
  if (!value || typeof value !== "object") return false;
  const summary = value as Record<string, unknown>;
  const languageStatus = summary.languageStatus;
  const languageBcp47 = summary.languageBcp47;
  if (
    languageStatus !== "fixed" &&
    languageStatus !== "dynamic" &&
    languageStatus !== "unknownSegments"
  ) return false;
  if (
    typeof languageBcp47 !== "string" ||
    languageBcp47.length > 35 ||
    !bcp47Pattern.test(languageBcp47)
  ) return false;
  if (
    (languageStatus === "fixed" && languageBcp47 === "und") ||
    (languageStatus !== "fixed" && languageBcp47 !== "und")
  ) return false;
  for (const count of [
    summary.activeLanguageCorrectionCount,
    summary.languageReviewRequiredCount,
  ]) {
    if (count !== undefined && (!Number.isSafeInteger(count) || (count as number) < 0)) {
      return false;
    }
  }
  return summary.timingStatus === "available" ||
    summary.timingStatus === "unavailable" ||
    summary.timingStatus === "legacyUnknown";
}

export function transcriptResultSummaryLabels(summary: TranscriptResultSummary) {
  const language = summary.languageStatus === "fixed"
    ? `Language: ${formatLanguageTag(summary.languageBcp47)} · fixed`
    : summary.languageStatus === "dynamic"
      ? "Language: automatic per segment"
      : "Language: some segments need review";
  const timing = summary.timingStatus === "available"
    ? "Word timing available"
    : summary.timingStatus === "unavailable"
      ? "Word timing unavailable"
      : "Word timing not recorded";
  const correctionDetails = [];
  if (summary.languageReviewRequiredCount) {
    correctionDetails.push(
      `${summary.languageReviewRequiredCount} language ${summary.languageReviewRequiredCount === 1 ? "label needs" : "labels need"} review`,
    );
  }
  if (summary.activeLanguageCorrectionCount) {
    correctionDetails.push(
      `${summary.activeLanguageCorrectionCount} language ${summary.activeLanguageCorrectionCount === 1 ? "label" : "labels"} corrected`,
    );
  }
  const corrections = correctionDetails.length ? correctionDetails.join(" · ") : undefined;
  return { corrections, language, timing };
}
