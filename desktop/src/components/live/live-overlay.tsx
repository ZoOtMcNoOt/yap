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
          event.relatedTarget instanceof Node
          && event.currentTarget.contains(event.relatedTarget)
        ) return;
        if (surface === "expanded") scheduleIdleCollapse();
      }}
      onFocus={() => {
        if (model.phase === "idle") openIdleIsland();
      }}
      onKeyDown={(event) => {
        if (
          event.target !== event.currentTarget
          || model.phase !== "idle"
          || !["Enter", " "].includes(event.key)
        ) return;
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
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        setPreviewPointerWithin(false);
        scheduleIdleCollapseWithoutFocus(event.currentTarget);
      }}
      style={rootFrameStyle}
      tabIndex={model.phase === "idle" ? 0 : -1}
    >
      {/*
        Upstream clips with `UnevenRoundedRectangle(bottomLeadingRadius: 12,
        bottomTrailingRadius: 12)`: square at the top because the strip is flush
        with the top of the display and is meant to read as part of the bezel,
        rounded at the bottom because that is the edge that hangs into the
        desktop. On Windows the native window region does the same clip for hit
        testing; painting it here as well is what keeps the curve smooth rather
        than stair-stepped along the region boundary.
      */}
      <div
        className="pointer-events-auto h-full w-full text-white motion-reduce:transition-none"
        data-overlay-revealed={revealed ? "true" : "false"}
        data-testid="live-overlay-island"
        style={{
          backgroundColor: "black",
          borderRadius: "0 0 12px 12px",
          overflow: "hidden",
          // Upstream animates its panel down out of the menu bar on a 0.18s
          // curve with a little overshoot -- `CAMediaTimingFunction(0.34, 1.56,
          // 0.64, 1.0)`, transcribed here. The overshoot is most of why it
          // reads as native rather than as a div appearing.
          //
          // The pill moves, not the window. A Tauri window repositioned from a
          // Rust timer arrives in discrete jumps; a transform inside a
          // transparent window is composited by WebView2 and is actually
          // smooth. The window stays a fixed strip at the top edge and ignores
          // the cursor while the pill is tucked away.
          transform: revealed ? "translateY(0)" : "translateY(-101%)",
          transition: "transform 180ms cubic-bezier(0.34, 1.56, 0.64, 1)",
          willChange: "transform",
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
