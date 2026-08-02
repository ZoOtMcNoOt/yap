import { invoke, isTauri } from "@tauri-apps/api/core";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import {
  collapseGraceMs,
  modelFromLiveView,
  overlaySurface,
  previewOverlayFrame,
  successVisibleMs,
} from "@/components/live/live-overlay-state";
import { createNativeSurfaceSync } from "@/components/live/native-surface-sync";
import { listenLiveOverlayReveal } from "@/live";
import type { LiveOverlayView } from "@/lib/live-session";

const setNativeOverlaySurface = createNativeSurfaceSync(async ({ surface }) => {
  if (!isTauri()) return;
  await invoke("set_live_overlay_surface", { surface });
});

export function useLiveOverlayPresentation(view: LiveOverlayView) {
  const model = modelFromLiveView(view);
  const [expanded, setExpanded] = useState(false);
  const [successVisible, setSuccessVisible] = useState(false);
  const previousStatusRef = useRef(view.status);
  const collapseTimerRef = useRef<number | undefined>(undefined);
  const successTimerRef = useRef<number | undefined>(undefined);
  const native = isTauri();
  const hasCopyableFinal = model.hasFinalText;
  const surface = overlaySurface(model, expanded, successVisible && hasCopyableFinal);
  const hiddenIdle = view.visibility === "hidden" && model.phase === "idle";
  // Out of the bezel or hidden in it. Rust drives this from a cursor poll --
  // see `overlay_window::sync_reveal` -- because a retracted overlay ignores
  // cursor events and cannot notice the pointer itself. The browser preview has
  // no Rust and nothing ignoring the cursor, so it drives the same state from
  // real DOM hover. Pinning the preview open instead would have made the
  // retracted state the one thing the suite could never see.
  const [cursorRevealed, setCursorRevealed] = useState(false);
  // Anything that is not a resting idle island holds it out regardless: the
  // user is dictating, transcribing, or being shown a failure.
  const revealed = cursorRevealed || model.phase !== "idle" || successVisible;
  const rootFrameStyle: CSSProperties | undefined = native
    ? undefined
    : previewOverlayFrame(surface, model);

  const clearSuccessTimer = useCallback(() => {
    if (successTimerRef.current === undefined) return;
    window.clearTimeout(successTimerRef.current);
    successTimerRef.current = undefined;
  }, []);

  const cancelCollapse = useCallback(() => {
    if (collapseTimerRef.current === undefined) return;
    window.clearTimeout(collapseTimerRef.current);
    collapseTimerRef.current = undefined;
  }, []);

  // No-op under Tauri: Rust owns the reveal there, and honouring DOM hover as
  // well would fight it every poll.
  const setPreviewPointerWithin = useCallback((within: boolean) => {
    if (native) return;
    setCursorRevealed(within);
  }, [native]);

  const openIdleIsland = useCallback(() => {
    cancelCollapse();
    setExpanded(true);
  }, [cancelCollapse]);

  const scheduleIdleCollapse = useCallback(() => {
    cancelCollapse();
    collapseTimerRef.current = window.setTimeout(() => {
      collapseTimerRef.current = undefined;
      setExpanded(false);
    }, collapseGraceMs);
  }, [cancelCollapse]);

  useEffect(() => {
    if (model.phase === "idle") return;
    cancelCollapse();
    setExpanded(false);
  }, [cancelCollapse, model.phase]);

  useLayoutEffect(() => {
    if (!hiddenIdle) return;
    cancelCollapse();
    setExpanded(false);
  }, [cancelCollapse, hiddenIdle]);

  useEffect(() => {
    const previousStatus = previousStatusRef.current;
    previousStatusRef.current = view.status;
    if (view.status !== "idle") {
      clearSuccessTimer();
      setSuccessVisible(false);
    } else if (previousStatus !== "idle" && hasCopyableFinal) {
      clearSuccessTimer();
      setSuccessVisible(true);
      successTimerRef.current = window.setTimeout(() => {
        successTimerRef.current = undefined;
        setSuccessVisible(false);
      }, successVisibleMs);
    }
  }, [clearSuccessTimer, hasCopyableFinal, view.status]);

  useEffect(() => {
    if (hiddenIdle) return;
    setNativeOverlaySurface({ surface });
  }, [hiddenIdle, surface]);

  useEffect(() => {
    if (!native) return;
    let stop: (() => void) | undefined;
    let cancelled = false;
    void listenLiveOverlayReveal(setCursorRevealed).then((unlisten) => {
      if (cancelled) {
        unlisten();
        return;
      }
      stop = unlisten;
    });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [native]);

  useEffect(() => {
    return () => {
      cancelCollapse();
      clearSuccessTimer();
    };
  }, [cancelCollapse, clearSuccessTimer]);

  return {
    hiddenIdle,
    model,
    native,
    openIdleIsland,
    revealed,
    rootFrameStyle,
    setPreviewPointerWithin,
    scheduleIdleCollapse,
    surface,
  };
}
