import gsap from "gsap";
import { useLayoutEffect, useRef } from "react";

import { LiveOverlayContent } from "@/components/live/live-overlay-views";
import { useLiveOverlayPresentation } from "@/components/live/use-live-overlay-presentation";
import { usePrefersReducedMotion } from "@/components/live/use-prefers-reduced-motion";
import type { LiveOverlayView } from "@/lib/live-session";
import { cn } from "@/lib/utils";

type LiveOverlayProps = {
  onOpenScratch?: () => void;
  onOpenTransform?: () => void;
  onRetry?: () => void;
  onStart?: () => void;
  onStop?: () => void;
  view: LiveOverlayView;
};

export function LiveOverlay({
  onOpenScratch,
  onOpenTransform,
  onRetry,
  onStart,
  onStop,
  view,
}: LiveOverlayProps) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const contentRef = useRef<HTMLDivElement>(null);
  const {
    hiddenIdle,
    model,
    openIdleIsland,
    revealed,
    rootFrameStyle,
    scheduleIdleCollapse,
    setPreviewPointerWithin,
    surface,
  } = useLiveOverlayPresentation(view);

  useOverlayTransition(contentRef, surface, prefersReducedMotion);

  const scheduleIdleCollapseWithoutFocus = (root: HTMLDivElement) => {
    if (root.contains(document.activeElement)) return;
    if (surface === "expanded") scheduleIdleCollapse();
  };

  if (hiddenIdle) return null;

  return (
    <div
      className={cn(
        "live-overlay-root h-full w-full overflow-hidden bg-transparent p-0",
        model.phase === "idle" ? "pointer-events-auto" : "pointer-events-none",
      )}
      data-overlay-phase={model.phase}
      data-overlay-surface={surface}
      data-testid="live-overlay-root"
      aria-label="Yap dictation controls"
      role="toolbar"
      onBlur={(event) => {
        if (
          event.relatedTarget instanceof Node &&
          event.currentTarget.contains(event.relatedTarget)
        )
          return;
        if (surface === "expanded") scheduleIdleCollapse();
      }}
      onFocus={() => {
        if (model.phase === "idle") openIdleIsland();
      }}
      onKeyDown={(event) => {
        if (
          event.target !== event.currentTarget ||
          model.phase !== "idle" ||
          !["Enter", " "].includes(event.key)
        )
          return;
        event.preventDefault();
        openIdleIsland();
      }}
      onPointerEnter={() => {
        setPreviewPointerWithin(true);
        if (model.phase === "idle") openIdleIsland();
      }}
      onMouseLeave={(event) => {
        setPreviewPointerWithin(false);
        scheduleIdleCollapseWithoutFocus(event.currentTarget);
      }}
      onPointerOut={(event) => {
        if (
          event.relatedTarget instanceof Node &&
          event.currentTarget.contains(event.relatedTarget)
        )
          return;
        setPreviewPointerWithin(false);
        scheduleIdleCollapseWithoutFocus(event.currentTarget);
      }}
      style={rootFrameStyle}
      tabIndex={model.phase === "idle" ? 0 : -1}
    >
      {/* Top-bezel geometry derives from FreeFlow's RecordingOverlay.swift (MIT,
          revision 7427ca9). Native code owns the frame; CSS owns the reveal. */}
      <div
        className="live-island-surface pointer-events-auto h-full w-full text-white motion-reduce:transition-none"
        data-overlay-revealed={revealed ? "true" : "false"}
        data-testid="live-overlay-island"
        style={{
          transform: revealed ? "translateY(0)" : "translateY(-101%)",
        }}
      >
        <div className="h-full w-full" ref={contentRef}>
          <LiveOverlayContent
            model={model}
            onOpenScratch={onOpenScratch}
            onOpenTransform={onOpenTransform}
            onRetry={onRetry}
            onStart={onStart}
            onStop={onStop}
            prefersReducedMotion={prefersReducedMotion}
            surface={surface}
          />
        </div>
      </div>
    </div>
  );
}

function useOverlayTransition(
  contentRef: React.RefObject<HTMLDivElement | null>,
  surface: string,
  prefersReducedMotion: boolean,
) {
  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    gsap.killTweensOf(content);

    if (prefersReducedMotion) {
      gsap.set(content, { opacity: 1, y: 0 });
      return;
    }
    gsap.fromTo(
      content,
      { opacity: 0.72, y: -2 },
      { duration: 0.12, ease: "power2.out", opacity: 1, overwrite: true, y: 0 },
    );
    return () => gsap.killTweensOf(content);
  }, [contentRef, prefersReducedMotion, surface]);
}
