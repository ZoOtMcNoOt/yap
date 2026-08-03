export type RecordingLanguageMode = "fixed" | "dynamic";

export type RecordingLanguageDisposition =
  | "primary"
  | "manualOverride"
  | "detectedSuggestionConfirmed"
  | "explicitDynamic";

export type RecordingLanguageDecision = {
  mode: RecordingLanguageMode;
  languageBcp47: string | null;
  disposition: RecordingLanguageDisposition;
};

export type RecordingImportLanguageChoice =
  | {
      mode: "fixed";
      languageBcp47: string;
      catalogRevision: string;
    }
  | {
      mode: "dynamic";
      catalogRevision: string;
    };

export function recordingLanguageSummary(
  decision: RecordingLanguageDecision | null | undefined,
): string | null {
  if (!decision) return null;
  if (decision.mode === "dynamic") return "Auto-detect language";
  if (!decision.languageBcp47) return null;
  if (decision.disposition === "manualOverride") {
    return `${decision.languageBcp47} override`;
  }
  if (decision.disposition === "detectedSuggestionConfirmed") {
    return `${decision.languageBcp47} confirmed`;
  }
  return decision.languageBcp47;
}
