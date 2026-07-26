function browserDisplayLocale() {
  return typeof navigator === "undefined" || !navigator.language
    ? "en"
    : navigator.language;
}

export function languageDisplayName(languageBcp47: string, displayLocale = browserDisplayLocale()) {
  try {
    return new Intl.DisplayNames([displayLocale], { type: "language" }).of(languageBcp47)
      ?? languageBcp47;
  } catch {
    return languageBcp47;
  }
}

export function formatLanguageTag(languageBcp47: string, displayLocale = browserDisplayLocale()) {
  const displayName = languageDisplayName(languageBcp47, displayLocale);
  return displayName === languageBcp47
    ? languageBcp47
    : `${displayName} (${languageBcp47})`;
}
