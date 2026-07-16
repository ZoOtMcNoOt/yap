import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import {
  confirmPrimaryLanguage,
  fixedBatchLanguageOptions,
  initialPrimaryLanguageSelection,
  primaryLanguageStatus,
  shouldRequestPrimaryLanguageSetup,
  type PrimaryLanguageStatus,
} from "@/language-preference";
import { recordingLanguageSummary } from "@/lib/recording-language";

const status: PrimaryLanguageStatus = {
  schemaVersion: 1,
  confirmedLanguageBcp47: null,
  suggestedLanguageBcp47: "en-US",
  confirmedLanguageAvailable: null,
  requiresConfirmation: true,
  preferenceIssue: null,
  lastKnownCapabilities: null,
  capabilityCatalog: {
    schemaVersion: 1,
    catalogRevision: "a".repeat(64),
    providers: [
      {
        providerId: "cohere",
        poolId: "cohere-batch",
        modelId: "model",
        modelRevision: "b".repeat(40),
        modelLicense: "Apache-2.0",
        modelSource: "https://example.test/model",
        capabilities: [
          {
            languageBcp47: "en-US",
            providerLanguageCode: "en",
            mode: "fixedBatch",
            qualityTier: "transcriptionReady",
            languageSuggestion: false,
            segmentLanguageTags: false,
            wordAlignment: false,
            promotionEvidenceRevision: "c".repeat(40),
          },
          {
            languageBcp47: "en-US",
            providerLanguageCode: "en",
            mode: "dynamicBatch",
            qualityTier: "preview",
            languageSuggestion: false,
            segmentLanguageTags: true,
            wordAlignment: false,
            promotionEvidenceRevision: "d".repeat(40),
          },
        ],
      },
    ],
  },
};

describe("primary language projection", () => {
  beforeEach(() => invokeMock.mockReset());

  it("derives choices only from fixed-batch catalog capabilities", () => {
    expect(fixedBatchLanguageOptions(status.capabilityCatalog)).toEqual([
      {
        languageBcp47: "en-US",
        qualityTier: "transcriptionReady",
      },
    ]);
  });

  it("preselects only a confirmed or exact OS suggestion", () => {
    expect(initialPrimaryLanguageSelection(status)).toBe("en-US");
    expect(initialPrimaryLanguageSelection({
      ...status,
      suggestedLanguageBcp47: null,
    })).toBeNull();
  });

  it("requests setup only when a current choice can be confirmed", () => {
    expect(shouldRequestPrimaryLanguageSetup(status)).toBe(true);
    expect(shouldRequestPrimaryLanguageSetup({
      ...status,
      capabilityCatalog: null,
      lastKnownCapabilities: {
        observedAtMs: 42,
        catalog: status.capabilityCatalog!,
      },
    })).toBe(false);
    expect(shouldRequestPrimaryLanguageSetup({
      ...status,
      preferenceIssue: "incompatibleSchema",
    })).toBe(false);
  });

  it("keeps command arguments typed and catalog-revision bound", async () => {
    invokeMock.mockResolvedValue(status);

    await primaryLanguageStatus();
    await confirmPrimaryLanguage("en-US", "a".repeat(64));

    expect(invokeMock.mock.calls).toEqual([
      ["primary_language_status"],
      ["confirm_primary_language", {
        languageBcp47: "en-US",
        catalogRevision: "a".repeat(64),
      }],
    ]);
  });

  it("keeps the frozen per-job disposition visible without changing the locale", () => {
    expect(recordingLanguageSummary({
      mode: "fixed",
      languageBcp47: "fr-FR",
      disposition: "manualOverride",
    })).toBe("fr-FR override");
    expect(recordingLanguageSummary({
      mode: "dynamic",
      languageBcp47: null,
      disposition: "explicitDynamic",
    })).toBe("Auto-detect language");
  });
});
