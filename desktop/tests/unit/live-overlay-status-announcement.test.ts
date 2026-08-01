import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { overlayStatusMessage } from "../../src/components/live/live-overlay-views";
import type { OverlayModel } from "../../src/components/live/live-overlay-state";

const viewsSource = readFileSync(
  new URL("../../src/components/live/live-overlay-views.tsx", import.meta.url),
  "utf8",
);

function model(overrides: Partial<OverlayModel> = {}): OverlayModel {
  return {
    audioLevel: 0,
    errorMessage: undefined,
    phase: "idle",
    recordingTriggerMode: "toggle",
    ...overrides,
  } as OverlayModel;
}

describe("live overlay status announcement", () => {
  // The overlay is the only surface where the state change is the whole
  // message. Without these, a screen reader user gets no signal that dictation
  // started, finished, or failed.
  it("names every phase a user needs to hear", () => {
    expect(overlayStatusMessage(model({ phase: "initializing" }), "recording")).toBe(
      "Starting dictation.",
    );
    expect(overlayStatusMessage(model({ phase: "recording" }), "recording")).toBe("Listening.");
    expect(overlayStatusMessage(model({ phase: "processing" }), "recording")).toBe("Transcribing.");
    expect(overlayStatusMessage(model({ phase: "idle" }), "success")).toBe(
      "Dictation finished. Transcript inserted.",
    );
  });

  it("carries the failure reason when there is one, and still announces failure when there is not", () => {
    expect(
      overlayStatusMessage(model({ errorMessage: "Microphone unavailable", phase: "feedback" }), "recording"),
    ).toBe("Dictation failed. Microphone unavailable");
    expect(overlayStatusMessage(model({ phase: "feedback" }), "recording")).toBe("Dictation failed.");
  });

  // An idle overlay must not announce anything, or the region re-reads on every
  // mount and talks over whatever the user is actually doing.
  it("stays silent when idle", () => {
    expect(overlayStatusMessage(model({ phase: "idle" }), "recording")).toBe("");
    expect(overlayStatusMessage(model({ phase: "idle" }), "collapsed")).toBe("");
  });

  // Politeness is the difference between a useful announcement and one that
  // interrupts dictation. Only a failure earns the interruption.
  it("interrupts only for failures", () => {
    expect(viewsSource).toMatch(/aria-live=\{failed \? "assertive" : "polite"\}/);
    expect(viewsSource).toMatch(/role=\{failed \? "alert" : "status"\}/);
    expect(viewsSource).toMatch(/const failed = model\.phase === "feedback"/);
  });

  // The region has to sit outside the surface branches. Mounted per-surface it
  // would unmount on every transition, and a live region that is removed as it
  // changes announces nothing at all.
  it("renders the region above the surface switch so it survives transitions", () => {
    const region = viewsSource.indexOf("<OverlayStatusAnnouncement");
    const firstSurface = viewsSource.indexOf('surface === "collapsed" ? (');
    expect(region).toBeGreaterThanOrEqual(0);
    expect(firstSurface).toBeGreaterThan(region);
  });
});
