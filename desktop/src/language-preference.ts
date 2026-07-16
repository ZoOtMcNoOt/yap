import { invoke } from "@tauri-apps/api/core";

import type { AsrCapabilityCatalog, AsrQualityTier } from "@/server";

export type PrimaryLanguagePreferenceIssue =
  | "invalidStoredPreference"
  | "incompatibleSchema";

export type PrimaryLanguageStatus = {
  schemaVersion: 1;
  confirmedLanguageBcp47: string | null;
  suggestedLanguageBcp47: string | null;
  confirmedLanguageAvailable: boolean | null;
  requiresConfirmation: boolean;
  preferenceIssue: PrimaryLanguagePreferenceIssue | null;
  capabilityCatalog: AsrCapabilityCatalog | null;
  lastKnownCapabilities: {
    observedAtMs: number;
    catalog: AsrCapabilityCatalog;
  } | null;
};

export type FixedBatchLanguageOption = {
  languageBcp47: string;
  qualityTier: AsrQualityTier;
};

const qualityRank: Record<AsrQualityTier, number> = {
  transcriptionReady: 3,
  broadCoverage: 2,
  preview: 1,
};

export function fixedBatchLanguageOptions(
  catalog: AsrCapabilityCatalog | null | undefined,
): FixedBatchLanguageOption[] {
  const options = new Map<string, FixedBatchLanguageOption>();
  for (const provider of catalog?.providers ?? []) {
    for (const capability of provider.capabilities) {
      if (capability.mode !== "fixedBatch") continue;
      const existing = options.get(capability.languageBcp47);
      if (!existing || qualityRank[capability.qualityTier] > qualityRank[existing.qualityTier]) {
        options.set(capability.languageBcp47, {
          languageBcp47: capability.languageBcp47,
          qualityTier: capability.qualityTier,
        });
      }
    }
  }
  return [...options.values()];
}

export function initialPrimaryLanguageSelection(status: PrimaryLanguageStatus): string | null {
  return status.confirmedLanguageBcp47 ?? status.suggestedLanguageBcp47;
}

export function shouldRequestPrimaryLanguageSetup(
  status: PrimaryLanguageStatus | null | undefined,
): boolean {
  return Boolean(
    status?.requiresConfirmation &&
    status.preferenceIssue !== "incompatibleSchema" &&
    fixedBatchLanguageOptions(status.capabilityCatalog).length,
  );
}

export function primaryLanguageStatus(): Promise<PrimaryLanguageStatus> {
  return invoke<PrimaryLanguageStatus>("primary_language_status");
}

export function confirmPrimaryLanguage(
  languageBcp47: string,
  catalogRevision: string,
): Promise<PrimaryLanguageStatus> {
  return invoke<PrimaryLanguageStatus>("confirm_primary_language", {
    languageBcp47,
    catalogRevision,
  });
}
