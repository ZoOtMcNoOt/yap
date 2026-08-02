import type { LiveCaptureMode, LiveOverlayView } from "@/lib/live-session";

type OverlayPhase = "idle" | "initializing" | "recording" | "processing" | "feedback";
export type OverlaySurface = "collapsed" | "expanded" | Exclude<OverlayPhase, "idle"> | "success";

export type OverlayModel = {
  audioLevel: number;
  errorMessage?: string;
  hasFinalText: boolean;
  phase: OverlayPhase;
  recordingTriggerMode: "hold" | "toggle";
};

export const collapseGraceMs = 200;
export const successVisibleMs = 2_500;

// Browser preview only. Rust is the sole owner of production native-window
// bounds; these mirror `overlay_window.rs::frame`, which is the port of
// FreeFlow's `overlayWidth` and holds the reasoning behind every number.
// A table cannot express the two rules that depend on the model, so this is a
// function of the same inputs Rust reads off its own state.
const pillHeight = 38;
const defaultWidth = 92;
const toggleWidth = 150;
const successWidth = 94;
const expandedFrame = { height: 96, width: 180 };

export function modelFromLiveView(view: LiveOverlayView): OverlayModel {
  const triggerMode = triggerModeFromCaptureMode(view.activeCaptureMode ?? view.captureMode);
  const base = {
    hasFinalText: view.hasFinalText,
  };
  if (view.status === "idle") {
    if (view.error) {
      return {
        ...base,
        audioLevel: 0,
        errorMessage: view.error,
        phase: "feedback",
        recordingTriggerMode: triggerMode,
      };
    }
    return { ...base, audioLevel: 0, phase: "idle", recordingTriggerMode: triggerMode };
  }

  switch (view.status) {
    case "armed":
      return { ...base, audioLevel: 0, phase: "initializing", recordingTriggerMode: triggerMode };
    case "listening":
    case "speaking":
      return { ...base, audioLevel: view.level ?? 0, phase: "recording", recordingTriggerMode: triggerMode };
    case "settling":
    case "saving":
      return { ...base, audioLevel: 0, phase: "processing", recordingTriggerMode: triggerMode };
    case "blocked":
      return {
        ...base,
        audioLevel: 0,
        errorMessage: view.error ?? undefined,
        phase: "feedback",
        recordingTriggerMode: triggerMode,
      };
  }
}

export function overlaySurface(model: OverlayModel, expanded: boolean, successVisible: boolean): OverlaySurface {
  if (model.phase !== "idle") return model.phase;
  if (successVisible) return "success";
  return expanded ? "expanded" : "collapsed";
}

export function previewOverlayFrame(surface: OverlaySurface, model: OverlayModel) {
  if (surface === "expanded") return expandedFrame;
  return { height: pillHeight, width: previewOverlayWidth(surface, model) };
}

function previewOverlayWidth(surface: OverlaySurface, model: OverlayModel) {
  switch (surface) {
    case "success":
      return successWidth;
    case "feedback":
      return feedbackWidth(model.errorMessage ?? "");
    case "recording":
    case "processing":
      return model.recordingTriggerMode === "toggle" ? toggleWidth : defaultWidth;
    default:
      return defaultWidth;
  }
}

// Upstream truncates at 90 characters before sizing, then allows ~6.8pt per
// character plus 60pt of chrome, clamped so a short failure stays readable and
// a long one cannot stretch across the display.
function feedbackWidth(message: string) {
  const characters = Math.min([...message].length, 90);
  if (characters === 0) return defaultWidth;
  return Math.min(420, Math.max(180, characters * 6.8 + 60));
}

function triggerModeFromCaptureMode(captureMode: LiveCaptureMode): "hold" | "toggle" {
  return captureMode === "toggle" ? "toggle" : "hold";
}
