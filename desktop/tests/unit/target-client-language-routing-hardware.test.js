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

  it("defaults the target run to fifteen minutes and rejects shorter overrides", () => {
    const environment = {
      YAP_TARGET_CLIENT_LANGUAGE_ROUTING_GATE: "1",
      YAP_TARGET_CLIENT_UI_EVIDENCE_FILE: "C:\\private-yap-evidence\\ui.json",
    };
    expect(createGate(environment).activeCaptureMs).toBe(900_000);
    expect(() => createGate({
      ...environment,
      YAP_HARDWARE_ACTIVE_CAPTURE_MS: "899999",
    })).toThrow(/between 900000 and 1800000/);
  });
});
