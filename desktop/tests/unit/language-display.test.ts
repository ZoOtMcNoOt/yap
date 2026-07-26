import { describe, expect, it } from "vitest";

import { formatLanguageTag, languageDisplayName } from "@/lib/language-display";

describe("language display formatting", () => {
  it("keeps the canonical BCP 47 tag visible beside a localized name", () => {
    const displayName = languageDisplayName("zh-Hant-TW", "en");
    const formatted = formatLanguageTag("zh-Hant-TW", "en");

    expect(displayName).not.toBe("zh-Hant-TW");
    expect(formatted).toContain(displayName);
    expect(formatted).toContain("zh-Hant-TW");
  });

  it("falls back to the unchanged tag when display-name construction fails", () => {
    expect(formatLanguageTag("en-US", "not_a_locale")).toBe("en-US");
  });
});
