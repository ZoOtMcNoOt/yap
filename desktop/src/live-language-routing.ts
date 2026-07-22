import { invoke } from "@tauri-apps/api/core";

export type LiveLanguageRoutingPreferenceIssue =
  | "invalidStoredPreference"
  | "incompatibleSchema"
  | "staleCatalog";

export type AutomaticLanguageOption = {
  languageCode: string;
  locales: string[];
  selectedLocaleBcp47: string | null;
};

export type LiveLanguageRoutingStatus = {
  schemaVersion: 2;
  catalogRevision: string;
  primaryLanguageBcp47: string | null;
  enabledLocales: string[];
  automaticLanguages: AutomaticLanguageOption[];
  preferenceIssue: LiveLanguageRoutingPreferenceIssue | null;
};

export function liveLanguageRoutingStatus(): Promise<LiveLanguageRoutingStatus> {
  return invoke<LiveLanguageRoutingStatus>("live_language_routing_status");
}

export function saveLiveLanguageRouting(
  enabledAlternateLocales: string[],
  catalogRevision: string,
): Promise<LiveLanguageRoutingStatus> {
  return invoke<LiveLanguageRoutingStatus>("set_live_language_routing", {
    enabledAlternateLocales,
    catalogRevision,
  });
}

export function updateAutomaticLanguageSelection(
  status: LiveLanguageRoutingStatus,
  languageCode: string,
  locale: string | null,
): string[] {
  const target = status.automaticLanguages.find(
    (option) => option.languageCode === languageCode,
  );
  if (!target) {
    throw new Error("Choose an available automatic language.");
  }
  if (locale !== null && !target.locales.includes(locale)) {
    throw new Error("Choose an available automatic locale.");
  }
  const selections = status.automaticLanguages
    .filter((option) => option.languageCode !== languageCode)
    .flatMap((option) => option.selectedLocaleBcp47 ? [option.selectedLocaleBcp47] : []);
  if (locale) selections.push(locale);
  return selections;
}
