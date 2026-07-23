import { describe, expect, it } from "vitest";

import { createTargetClientLanguageRoutingHardwareGate } from "../wdio/target-client-language-routing-hardware.js";

function createGate(environment) {
  return createTargetClientLanguageRoutingHardwareGate({
    browser: {},
    environment,
    recordingRoot: "C:\\private-yap-recordings",
  });
}

describe("target-client language-routing hardware gate", () => {
  it("keeps the ordinary optional hardware capture short", () => {
    const gate = createGate({});
    expect(gate.enabled).toBe(false);
    expect(gate.activeCaptureMs).toBe(750);
    expect(() => gate.publishEvidence()).not.toThrow();
  });

  it("requires a private aggregate destination before enabling qualification", () => {
    expect(() => createGate({
      YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
    })).toThrow(/UI_EVIDENCE_FILE/);
  });

  it("requires the automated acoustic stimulus delivery contract", () => {
    expect(() => createGate({
      YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
      YAP_TARGET_CLIENT_UI_EVIDENCE_FILE: "C:\\private-yap-evidence\\ui.json",
    })).toThrow(/STIMULUS_DELIVERY/);
  });

  it("defaults the unattended rendered-capture smoke to thirty seconds", () => {
    const environment = {
      YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
      YAP_TARGET_CLIENT_STIMULUS_DELIVERY: "same-host-acoustic-playback",
      YAP_TARGET_CLIENT_UI_EVIDENCE_FILE: "C:\\private-yap-evidence\\ui.json",
    };
    expect(createGate(environment).activeCaptureMs).toBe(30_000);
    expect(() => createGate({
      ...environment,
      YAP_HARDWARE_ACTIVE_CAPTURE_MS: "29999",
    })).toThrow(/between 30000 and 1800000/);
  });

  it("requires active capture and finite levels without depending on acoustic loopback", () => {
    const gate = createGate({
      YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
      YAP_TARGET_CLIENT_STIMULUS_DELIVERY: "same-host-acoustic-playback",
      YAP_TARGET_CLIENT_UI_EVIDENCE_FILE: "C:\\private-yap-evidence\\ui.json",
    });
    const evidence = {
      levels: [{ level: 0 }],
      mainSessions: [{
        error: null,
        route: "localFallback",
        transcriptionDegraded: false,
      }],
    };
    const uiResponsiveness = {
      maximumDelayMs: 25,
      p95DelayMs: 5,
      sampleCount: 2_000,
    };

    expect(() => gate.assertRenderedCaptureEvidence({
      evidence,
      statuses: ["armed", "listening", "saving", "idle"],
      uiResponsiveness,
    })).not.toThrow();
    expect(() => gate.assertRenderedCaptureEvidence({
      evidence,
      statuses: ["armed", "saving", "idle"],
      uiResponsiveness,
    })).toThrow(/active microphone capture/);
  });

  it("resolves the WebdriverIO browser when an operation starts", async () => {
    let activeBrowser;
    const gate = createTargetClientLanguageRoutingHardwareGate({
      browserProvider: () => activeBrowser,
      environment: {
        YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
        YAP_TARGET_CLIENT_STIMULUS_DELIVERY: "same-host-acoustic-playback",
        YAP_TARGET_CLIENT_UI_EVIDENCE_FILE: "C:\\private-yap-evidence\\ui.json",
      },
      recordingRoot: "C:\\private-yap-recordings",
    });
    activeBrowser = {
      tauri: {
        execute: async (operation) => operation({
          core: {
            invoke: async (command) => {
              if (command === "live_language_routing_status") {
                return {
                  automaticLanguages: [{ languageCode: "de", locales: ["de-DE"] }],
                  catalogRevision: "catalog-test",
                };
              }
              return { enabledLocales: ["en-US", "de-DE"] };
            },
          },
        }),
        switchWindow: async () => {},
      },
    };

    await expect(gate.configureLanguageRouting()).resolves.toEqual({
      enabledLocales: ["en-US", "de-DE"],
    });
  });

  it("requires the connector state that corresponds to disabled server settings", async () => {
    const status = {
      acousticLanguageDetector: { status: "ready" },
      languageRouting: {
        enabledLocales: ["en-US", "de-DE"],
        preferenceIssue: null,
      },
      model: { status: "ready" },
      serverConnection: { state: "disabled" },
      serverSettings: { schemaVersion: 1, enabled: false, baseUrl: null },
      silero: { status: "ready" },
    };
    const gate = createTargetClientLanguageRoutingHardwareGate({
      browser: {
        tauri: {
          execute: async () => status,
          switchWindow: async () => {},
        },
      },
      environment: {
        YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
        YAP_TARGET_CLIENT_STIMULUS_DELIVERY: "same-host-acoustic-playback",
        YAP_TARGET_CLIENT_UI_EVIDENCE_FILE: "C:\\private-yap-evidence\\ui.json",
      },
      recordingRoot: "C:\\private-yap-recordings",
    });

    await expect(gate.assertResidentRuntimeReady({
      enabledLocales: ["en-US", "de-DE"],
    })).resolves.toBeUndefined();
    status.serverConnection.state = "not_set";
    await expect(gate.assertResidentRuntimeReady({
      enabledLocales: ["en-US", "de-DE"],
    })).rejects.toThrow(/server disabled and no base URL/);
  });
});
