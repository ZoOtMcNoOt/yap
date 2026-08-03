import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { PrimaryLanguageSetting } from "@/components/settings/primary-language-setting";
import { AutomaticLanguageRoutingSetting } from "@/components/settings/automatic-language-routing-setting";
import { SettingsRow } from "@/components/settings/settings-primitives";
import type { LiveLanguageRoutingControl } from "@/hooks/use-live-language-routing";
import type { PrimaryLanguageStatus } from "@/language-preference";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

function cssHexVariable(styles: string, name: string) {
  const value = styles.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1];
  if (!value) throw new Error(`Missing six-digit CSS color variable ${name}`);
  return value;
}

function relativeLuminance(hex: string) {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const [red, green, blue] = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
}

function contrastRatio(foreground: string, background: string) {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

const primaryLanguageStatus: PrimaryLanguageStatus = {
  capabilityCatalog: {
    catalogRevision: "language-control-accessibility-test-catalog-v1",
    providers: [{
      capabilities: [{
        languageBcp47: "en-US",
        languageSuggestion: false,
        mode: "fixedBatch",
        promotionEvidenceRevision: "language-control-accessibility-test-evidence-v1",
        providerLanguageCode: "en",
        qualityTier: "transcriptionReady",
        segmentLanguageTags: false,
        wordAlignment: true,
      }],
      modelId: "test-model",
      modelLicense: "test-license",
      modelRevision: "0123456789abcdef0123456789abcdef01234567",
      modelSource: "https://example.invalid/model",
      poolId: "test-pool",
      providerId: "test-provider",
    }],
    schemaVersion: 1,
  },
  confirmedLanguageAvailable: true,
  confirmedLanguageBcp47: "en-US",
  lastKnownCapabilities: null,
  preferenceIssue: null,
  requiresConfirmation: false,
  schemaVersion: 1,
  suggestedLanguageBcp47: null,
};

describe("language-control accessibility", () => {
  it("announces a settings error once as live, atomic alert text", () => {
    const html = renderToStaticMarkup(
      <SettingsRow error="Choose a supported language." errorId="language-error" label="Language" value="Unknown" />,
    );

    expect(html).toContain('id="language-error"');
    expect(html).toContain('role="alert"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain('aria-atomic="true"');
    expect(html.match(/Choose a supported language\./g)).toHaveLength(1);
  });

  it("can announce asynchronous settings status without turning it into an alert", () => {
    const html = renderToStaticMarkup(
      <SettingsRow
        detail="Opening Microsoft sign-in."
        label="Server sign-in"
        liveStatus
        value="Checking"
      />,
    );

    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain('aria-atomic="true"');
    expect(html).not.toContain('role="alert"');
  });

  it("gives the primary picker an explicit label and connects invalid state to one error", () => {
    const html = renderToStaticMarkup(
      <PrimaryLanguageSetting
        error="The language catalog changed."
        onConfirm={vi.fn()}
        pending={false}
        status={primaryLanguageStatus}
      />,
    );
    const errorId = html.match(/id="([^"]+)" role="alert"/)?.[1];

    expect(errorId).toBeTruthy();
    expect(html).toContain("Primary language");
    expect(html).toMatch(/aria-labelledby="[^"]+"/);
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain(`aria-describedby="${errorId}"`);
    expect(html.match(/The language catalog changed\./g)).toHaveLength(1);
  });

  it("labels every automatic-language picker and connects one shared routing error", () => {
    const control = {
      error: "Automatic choices need review.",
      load: vi.fn(),
      pending: false,
      reset: vi.fn(),
      status: {
        catalogRevision: "local-language-catalog-v1",
        enabledLocales: ["en-US"],
        preferenceIssue: null,
        primaryLanguageBcp47: "en-US",
        automaticLanguages: [{
          languageCode: "fr",
          locales: ["fr-CA", "fr-FR"],
          selectedLocaleBcp47: null,
        }],
        schemaVersion: 2,
      },
      update: vi.fn(),
    } as unknown as LiveLanguageRoutingControl;
    const html = renderToStaticMarkup(
      <AutomaticLanguageRoutingSetting control={control} liveActive={false} />,
    );
    const errorId = html.match(/id="([^"]+)" role="alert"/)?.[1];

    expect(errorId).toBeTruthy();
    expect(html).toContain("Automatic alternate languages (Preview)");
    expect(html).toContain("initial live text can wait for a 3-second language window");
    expect(html).toContain("may miss or misclassify natural switches");
    expect(html).toContain("ambiguous audio stays on your primary language");
    expect(html).toContain("French");
    expect(html).toMatch(/aria-labelledby="[^"]+"/);
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain(`aria-describedby="${errorId}"`);
    expect(html.match(/Automatic choices need review\./g)).toHaveLength(1);
  });

  it("describes an incompatible automatic-language setting without guessing its origin", () => {
    const control = {
      error: "",
      load: vi.fn(),
      pending: false,
      reset: vi.fn(),
      status: {
        catalogRevision: "local-language-catalog-v1",
        enabledLocales: ["en-US"],
        preferenceIssue: "incompatibleSchema",
        primaryLanguageBcp47: "en-US",
        automaticLanguages: [],
        schemaVersion: 2,
      },
      update: vi.fn(),
    } as unknown as LiveLanguageRoutingControl;

    const html = renderToStaticMarkup(
      <AutomaticLanguageRoutingSetting control={control} liveActive={false} />,
    );

    expect(html).toContain("uses an incompatible format");
    expect(html).toContain("preserved unchanged");
    expect(html).not.toContain("newer Yap version");
  });

  it("disables picker and drop-target transitions for reduced-motion users", () => {
    expect(source("../../src/components/ui/select.tsx"))
      .toContain("motion-reduce:animate-none motion-reduce:transition-none");
    expect(source("../../src/components/panels/drop-hero.tsx"))
      .toContain("motion-reduce:transition-none");
  });

  it("keeps normal-size language status and error tokens above WCAG AA contrast", () => {
    const styles = source("../../src/styles.css");
    const background = cssHexVariable(styles, "--background");

    expect(contrastRatio(cssHexVariable(styles, "--muted-foreground"), background))
      .toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(cssHexVariable(styles, "--destructive"), background))
      .toBeGreaterThanOrEqual(4.5);
  });
});
