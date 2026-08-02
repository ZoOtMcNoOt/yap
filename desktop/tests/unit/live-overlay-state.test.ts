import { describe, expect, it } from "vitest";

import type { LiveOverlayView } from "@/lib/live-session";

import {
  collapseGraceMs,
  modelFromLiveView,
  overlaySurface,
  previewOverlayFrame,
} from "@/components/live/live-overlay-state";

const baseView: LiveOverlayView = {
  captureMode: "pushToTalk",
  hasFinalText: false,
  status: "idle",
  visibility: "enabled",
};

describe("live overlay state projection", () => {
  it("keeps a visible collapsed island and expands the same surface downward", () => {
    const model = modelFromLiveView(baseView);

    expect(overlaySurface(model, false, false)).toBe("collapsed");
    expect(previewOverlayFrame("collapsed", model)).toEqual({ height: 38, width: 92 });
    expect(overlaySurface(model, true, false)).toBe("expanded");
    expect(previewOverlayFrame("expanded", model)).toEqual({ height: 96, width: 180 });
    expect(collapseGraceMs).toBe(200);
  });

  it("shows armed as initializing before capture is installed", () => {
    expect(modelFromLiveView({ ...baseView, status: "armed" }).phase).toBe("initializing");
  });

  it("treats listening and speaking as active recording surfaces", () => {
    for (const status of ["listening", "speaking"] as const) {
      expect(modelFromLiveView({ ...baseView, status }).phase).toBe("recording");
    }
  });

  it("does not let hidden idle preference suppress an active recording", () => {
    const model = modelFromLiveView({ ...baseView, status: "listening", visibility: "hidden" });

    expect(model.phase).toBe("recording");
    expect(overlaySurface(model, false, false)).toBe("recording");
  });

  // Only hands-free recording grows the pill, because only hands-free recording
  // shows a stop badge. Asserted against the held width in the same case: this
  // read the same 112 for both modes when the frame ignored the model, so the
  // name promised a difference the assertion could not have caught.
  it("reserves the hands-free finish island width and nothing wider when held", () => {
    const handsFree = modelFromLiveView({ ...baseView, captureMode: "toggle", status: "listening" });
    const held = modelFromLiveView({ ...baseView, status: "listening" });

    expect(handsFree.recordingTriggerMode).toBe("toggle");
    expect(previewOverlayFrame("recording", handsFree)).toEqual({ height: 38, width: 150 });
    expect(held.recordingTriggerMode).toBe("hold");
    expect(previewOverlayFrame("recording", held)).toEqual({ height: 38, width: 92 });
  });

  it("uses the active gesture mode over the saved setting", () => {
    const held = modelFromLiveView({
      ...baseView,
      activeCaptureMode: "pushToTalk",
      captureMode: "toggle",
      status: "speaking",
    });
    const handsFree = modelFromLiveView({
      ...baseView,
      activeCaptureMode: "toggle",
      captureMode: "pushToTalk",
      status: "speaking",
    });

    expect(held.recordingTriggerMode).toBe("hold");
    expect(previewOverlayFrame("recording", held)).toEqual({ height: 38, width: 92 });
    expect(handsFree.recordingTriggerMode).toBe("toggle");
    expect(previewOverlayFrame("recording", handsFree)).toEqual({ height: 38, width: 150 });
  });

  // Upstream locks the recording width through transcription so the pill cannot
  // snap narrow mid-job; carrying the trigger mode into processing is how that
  // lock is reproduced without holding the previous width.
  it("keeps settling and saving at the width the recording had", () => {
    for (const status of ["settling", "saving"] as const) {
      const held = modelFromLiveView({ ...baseView, status });
      const handsFree = modelFromLiveView({ ...baseView, captureMode: "toggle", status });

      expect(held.phase).toBe("processing");
      expect(previewOverlayFrame("processing", held)).toEqual({ height: 38, width: 92 });
      expect(previewOverlayFrame("processing", handsFree)).toEqual({ height: 38, width: 150 });
    }
  });

  it("derives success and failure affordance surfaces from current state", () => {
    const idleWithText = modelFromLiveView({ ...baseView, hasFinalText: true });
    const blocked = modelFromLiveView({ ...baseView, error: "Mic denied", status: "blocked" });

    expect(overlaySurface(idleWithText, false, true)).toBe("success");
    expect(previewOverlayFrame("success", idleWithText)).toEqual({ height: 38, width: 94 });
    expect(overlaySurface(blocked, false, false)).toBe("feedback");
    expect(previewOverlayFrame("feedback", blocked)).toEqual({ height: 38, width: 180 });
  });

  // The failure pill is the one surface whose width carries content. Both clamp
  // ends and the bare marker are the contract; a message long enough to blow
  // past the cap must land on the cap rather than on its own arithmetic.
  it("sizes the failure pill to its message within upstream clamps", () => {
    const bare = modelFromLiveView({ ...baseView, status: "blocked" });
    const short = modelFromLiveView({ ...baseView, error: "Mic denied", status: "blocked" });
    const medium = modelFromLiveView({ ...baseView, error: "x".repeat(40), status: "blocked" });
    const overlong = modelFromLiveView({ ...baseView, error: "x".repeat(4_000), status: "blocked" });

    expect(previewOverlayFrame("feedback", bare).width).toBe(92);
    expect(previewOverlayFrame("feedback", short).width).toBe(180);
    expect(previewOverlayFrame("feedback", medium).width).toBe(332);
    expect(previewOverlayFrame("feedback", overlong).width).toBe(420);
  });

  it("surfaces idle injection fallback instead of reporting success", () => {
    const fallback = modelFromLiveView({
      ...baseView,
      error: "Couldn't insert text here. Transcript copied; press Ctrl+V.",
      hasFinalText: true,
    });

    expect(fallback.phase).toBe("feedback");
    expect(fallback.errorMessage).toContain("Transcript copied");
    expect(overlaySurface(fallback, false, true)).toBe("feedback");
  });
});
