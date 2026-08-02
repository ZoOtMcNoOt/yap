import { Check } from "@phosphor-icons/react/Check";
import { WarningCircle } from "@phosphor-icons/react/WarningCircle";
import { ChatText } from "@phosphor-icons/react/ChatText";
import { Microphone } from "@phosphor-icons/react/Microphone";
import { ArrowCounterClockwise } from "@phosphor-icons/react/ArrowCounterClockwise";
import { Sparkle } from "@phosphor-icons/react/Sparkle";
import { Square } from "@phosphor-icons/react/Square";
import { X } from "@phosphor-icons/react/X";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { type OverlayModel, type OverlaySurface } from "@/components/live/live-overlay-state";
import { LiveWaveform, useOverlayTimeline } from "@/components/live/live-waveform";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Ported from FreeFlow's RecordingOverlayView and its sibling views
// (Sources/RecordingOverlay.swift, MIT, revision 7427ca9).
//
// Upstream's palette is two colours. Everything structural is white on black at
// 0.92 opacity; one red carries anything that failed or that stops a recording.
// There is no accent hue, no tinted surface and no second weight of text. Yap's
// island had picked up fuchsia and emerald along the way, and that -- more than
// any single measurement -- is what stopped it reading like the thing it was
// copied from.
const upstreamRed = "rgba(255, 59, 48, 0.92)"; // Color.red.opacity(0.92)
const chromeWhite = "rgba(255, 255, 255, 0.92)"; // .white.opacity(0.92)
// `.padding(.horizontal, 12)` on the pill's root.
const pillPaddingClass = "px-3";
// `leadingAccessoryWidth` / `trailingAccessoryWidth`: reserved on both sides so
// the centred indicator stays centred whether or not an accessory is showing.
const trailingAccessoryWidth = 32;

export function LiveOverlayContent({
  model,
  onOpenScratch,
  onOpenTransform,
  onRetry,
  onStart,
  onStop,
  prefersReducedMotion,
  surface,
}: {
  model: OverlayModel;
  onOpenScratch?: () => void;
  onOpenTransform?: () => void;
  onRetry?: () => void;
  onStart?: () => void;
  onStop?: () => void;
  prefersReducedMotion: boolean;
  surface: OverlaySurface;
}) {
  // The overlay is the one surface where state changes carry the whole meaning:
  // it is where dictation starts, stops, and fails. Every other surface here
  // renders silently, so a screen reader user would otherwise have no signal
  // that recording began or that it failed. One region for all surfaces, so the
  // announcement survives the surface swap rather than unmounting with it.
  return (
    <>
      <OverlayStatusAnnouncement model={model} surface={surface} />
      {surface === "collapsed" ? (
        <CollapsedOverlayView />
      ) : surface === "expanded" ? (
        <ExpandedOverlayView
          onOpenScratch={onOpenScratch}
          onOpenTransform={onOpenTransform}
          onStart={onStart}
        />
      ) : surface === "success" ? (
        <SuccessOverlayView />
      ) : (
        <RecordingOverlayView
          model={model}
          onRetry={onRetry}
          onStop={onStop}
          prefersReducedMotion={prefersReducedMotion}
        />
      )}
    </>
  );
}

// Announces what the overlay is doing. Errors interrupt because they need a
// response; everything else waits its turn so a burst of level updates cannot
// talk over the user.
function OverlayStatusAnnouncement({
  model,
  surface,
}: {
  model: OverlayModel;
  surface: OverlaySurface;
}) {
  const failed = model.phase === "feedback";
  const message = overlayStatusMessage(model, surface);
  return (
    <div
      aria-atomic="true"
      aria-live={failed ? "assertive" : "polite"}
      className="sr-only"
      data-testid="live-overlay-status"
      role={failed ? "alert" : "status"}
    >
      {message}
    </div>
  );
}

export function overlayStatusMessage(model: OverlayModel, surface: OverlaySurface): string {
  if (surface === "success") return "Dictation finished. Transcript inserted.";
  if (model.phase === "feedback") {
    return model.errorMessage
      ? `Dictation failed. ${model.errorMessage}`
      : "Dictation failed.";
  }
  if (model.phase === "initializing") return "Starting dictation.";
  if (model.phase === "recording") return "Listening.";
  if (model.phase === "processing") return "Transcribing.";
  return "";
}

// Yap-only: upstream dismisses the panel when idle rather than parking a resting
// island on screen. Styled in upstream's `UpdateAvailableOverlayView` idiom --
// 13pt glyph, 7pt gap, 11pt semibold label -- because that is the one pill it
// draws that is a label rather than an indicator.
function CollapsedOverlayView() {
  return (
    <div
      aria-label="Yap dictation island"
      className={cn("flex h-full w-full items-center justify-center gap-[7px]", pillPaddingClass)}
    >
      <Microphone className="size-[13px]" style={{ color: chromeWhite }} weight="fill" />
      <PillLabel>Yap</PillLabel>
    </div>
  );
}

function ExpandedOverlayView({
  onOpenScratch,
  onOpenTransform,
  onStart,
}: {
  onOpenScratch?: () => void;
  onOpenTransform?: () => void;
  onStart?: () => void;
}) {
  return (
    <div className="flex h-full w-full flex-col">
      <div
        className={cn(
          "flex h-[38px] shrink-0 items-center justify-center gap-[7px] border-b border-white/10",
          pillPaddingClass,
        )}
      >
        <Microphone className="size-[13px]" style={{ color: chromeWhite }} weight="fill" />
        <PillLabel>Yap</PillLabel>
      </div>
      <div className={cn("flex min-h-0 flex-1 items-center justify-center gap-2", pillPaddingClass)}>
        <IslandInlineButton label="Start dictating" onClick={onStart}>
          <Microphone className="size-[18px]" weight="bold" />
        </IslandInlineButton>
        <IslandInlineButton label="Open scratch" onClick={onOpenScratch}>
          <ChatText className="size-4" weight="bold" />
        </IslandInlineButton>
        <IslandInlineButton label="Open transform" onClick={onOpenTransform}>
          <Sparkle className="size-4" weight="bold" />
        </IslandInlineButton>
      </div>
    </div>
  );
}

function RecordingOverlayView({
  model,
  onRetry,
  onStop,
  prefersReducedMotion,
}: {
  model: OverlayModel;
  onRetry?: () => void;
  onStop?: () => void;
  prefersReducedMotion: boolean;
}) {
  const showsLiveRecordingContent = model.phase === "recording";
  const showsStopButton = showsLiveRecordingContent && model.recordingTriggerMode === "toggle";

  if (model.phase === "feedback" && model.errorMessage) {
    return <ErrorOverlayView message={model.errorMessage} onRetry={onRetry} />;
  }
  if (model.phase === "feedback") return <FailureIndicatorView onRetry={onRetry} />;

  return (
    <div
      className={cn("relative grid h-full w-full place-items-center", pillPaddingClass)}
      data-testid="live-recording-layout"
    >
      <div className="absolute inset-0 grid place-items-center">
        {model.phase === "initializing" ? (
          <InitializingDotsView prefersReducedMotion={prefersReducedMotion} />
        ) : showsLiveRecordingContent ? (
          <LiveWaveform
            audioLevel={model.audioLevel}
            prefersReducedMotion={prefersReducedMotion}
            showsActivityPulse
          />
        ) : (
          <ProcessingIndicatorView prefersReducedMotion={prefersReducedMotion} />
        )}
      </div>

      <div className={cn("absolute inset-0 flex items-center justify-end", pillPaddingClass)}>
        <div
          className="flex items-center justify-end"
          data-testid="live-toggle-actions"
          style={{ width: trailingAccessoryWidth }}
        >
          {showsStopButton ? (
            <BadgeButton label="Finish recording" onClick={onStop}>
              <StopBadge />
            </BadgeButton>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// upstream: `Image(systemName: "stop.fill").font(.system(size: 7, weight: .bold))`
// in a 14x14 `Circle().fill(Color.red.opacity(0.92))`.
function StopBadge() {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full"
      style={{ backgroundColor: upstreamRed, height: 14, width: 14 }}
    >
      <Square className="size-[7px] text-white" weight="fill" />
    </span>
  );
}

// Upstream's badge is the whole button: a 14pt hit target, which is fine for a
// pointer parked in a menu bar and not fine anywhere else. The badge renders at
// upstream's size; the button carries the transparent 32pt slot upstream already
// reserves for it, so the target is honest without the silhouette changing.
function BadgeButton({ children, label, onClick }: ActionButtonProps) {
  return (
    <button
      aria-label={label}
      className="grid size-8 place-items-center rounded-full bg-transparent p-0 outline-none focus-visible:ring-2 focus-visible:ring-white/60"
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function PillLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold leading-none" style={{ color: chromeWhite }}>
      {children}
    </span>
  );
}

function IslandInlineButton({ children, label, onClick }: ActionButtonProps) {
  return (
    <Button
      aria-label={label}
      className="size-10 rounded-full bg-white/10 p-0 text-white transition-colors motion-reduce:transition-none hover:bg-white/20 focus-visible:ring-white/60"
      onClick={onClick}
      size="icon-tight"
      title={label}
      type="button"
      variant="ghost"
    >
      {children}
    </Button>
  );
}

// upstream `ProcessingIndicatorView`: the processing waveform for one second,
// then a spinner, because past a second the bars read as "still listening".
function ProcessingIndicatorView({ prefersReducedMotion }: { prefersReducedMotion: boolean }) {
  const [showsSpinner, setShowsSpinner] = useState(false);

  useEffect(() => {
    if (prefersReducedMotion) return;
    const handle = window.setTimeout(() => setShowsSpinner(true), 1_000);
    return () => window.clearTimeout(handle);
  }, [prefersReducedMotion]);

  if (showsSpinner) return <ProcessingSpinnerView />;
  return <ProcessingWaveformView prefersReducedMotion={prefersReducedMotion} />;
}

// upstream: `Circle().trim(from: 0.1, to: 0.9).stroke(.white, lineWidth: 2.5,
// lineCap: .round)` in 16x16, rotating 360 degrees linearly every 0.8s.
const spinnerRadius = 6.75; // (16 - 2.5) / 2
const spinnerCircumference = 2 * Math.PI * spinnerRadius;

function ProcessingSpinnerView() {
  return (
    <svg
      aria-hidden="true"
      className="animate-spin"
      data-testid="live-processing-spinner"
      height={16}
      style={{ animationDuration: "0.8s" }}
      viewBox="0 0 16 16"
      width={16}
    >
      <circle
        cx={8}
        cy={8}
        fill="none"
        r={spinnerRadius}
        stroke="white"
        strokeDasharray={`${spinnerCircumference * 0.8} ${spinnerCircumference}`}
        strokeLinecap="round"
        strokeWidth={2.5}
      />
    </svg>
  );
}

// upstream `ProcessingWaveformView`: five pills on the same 30fps clock as the
// recording waveform, breathing in a staggered cycle. Height and opacity both
// track the pulse.
const processingPillCount = 5;
const processingCenterIndex = (processingPillCount - 1) / 2;
const processingMinHeight = 4;
const processingMaxHeight = 18;

function ProcessingWaveformView({ prefersReducedMotion }: { prefersReducedMotion: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useOverlayTimeline(!prefersReducedMotion, (timeSeconds) => {
    const pills = containerRef.current?.querySelectorAll<HTMLElement>("[data-live-processing-pill]");
    pills?.forEach((pill, index) => {
      const pulse = processingPulse(index, timeSeconds);
      pill.style.height = `${processingHeight(index, pulse)}px`;
      pill.style.opacity = `${0.42 + pulse * 0.52}`;
    });
  });

  return (
    <div className="flex h-5 items-center justify-center gap-1" ref={containerRef}>
      {Array.from({ length: processingPillCount }, (_, index) => (
        <span
          className="w-1 rounded-full bg-white"
          data-live-processing-pill
          key={index}
          style={{
            height: processingHeight(index, 0),
            opacity: 0.42,
          } as CSSProperties}
        />
      ))}
    </div>
  );
}

function processingPulse(index: number, timeSeconds: number) {
  const cycle = 1.05;
  const stagger = 0.11;
  // Swift's `truncatingRemainder` keeps the sign of the dividend; JS `%` does
  // too, so both need the extra wrap before dividing.
  const phase = ((((timeSeconds - index * stagger) % cycle) + cycle) % cycle) / cycle;
  const wave = 0.5 + 0.5 * Math.sin(phase * 2 * Math.PI - Math.PI / 2);
  return wave ** 1.9;
}

function processingHeight(index: number, pulse: number) {
  const centerDistance = Math.abs(index - processingCenterIndex) / processingCenterIndex;
  const baseline = 0.18 + (1 - centerDistance) * 0.1;
  const amplitude = Math.min(baseline + pulse * 0.68, 1);
  return processingMinHeight + (processingMaxHeight - processingMinHeight) * amplitude;
}

// upstream `InitializingDotsView`: three 4.5pt dots, one lit at 0.9 and the rest
// at 0.25, advancing every 0.5s over a 0.4s ease.
function InitializingDotsView({ prefersReducedMotion }: { prefersReducedMotion: boolean }) {
  const [activeDot, setActiveDot] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion) return;
    const handle = window.setInterval(() => setActiveDot((dot) => (dot + 1) % 3), 500);
    return () => window.clearInterval(handle);
  }, [prefersReducedMotion]);

  return (
    <div className="flex items-center justify-center gap-1">
      {Array.from({ length: 3 }, (_, index) => (
        <span
          className="size-[4.5px] rounded-full bg-white transition-opacity duration-[400ms] ease-in-out motion-reduce:transition-none"
          key={index}
          style={{ opacity: activeDot === index ? 0.9 : 0.25 }}
        />
      ))}
    </div>
  );
}

// Yap-only, in upstream's label-pill idiom.
function SuccessOverlayView() {
  return (
    <div className={cn("flex h-full w-full items-center justify-center gap-[7px]", pillPaddingClass)}>
      <Check className="size-[13px]" style={{ color: chromeWhite }} weight="bold" />
      <PillLabel>Saved</PillLabel>
    </div>
  );
}

// upstream `FailureIndicatorView`: a 12pt bold xmark in a 20x20 red circle, and
// nothing else. Yap keeps a retry beside it -- an affordance, not a style -- in
// the neutral white treatment upstream uses for everything that is not an alarm.
function FailureIndicatorView({ onRetry }: { onRetry?: () => void }) {
  return (
    <div className={cn("flex h-full w-full items-center justify-center gap-2", pillPaddingClass)}>
      <span
        className="grid shrink-0 place-items-center rounded-full"
        style={{ backgroundColor: upstreamRed, height: 20, width: 20 }}
      >
        <X className="size-3 text-white" weight="bold" />
      </span>
      <NeutralIconButton label="Retry dictation" onClick={onRetry}>
        <ArrowCounterClockwise className="size-3.5" weight="bold" />
      </NeutralIconButton>
    </div>
  );
}

// upstream `ErrorOverlayView`: 13pt filled exclamation in red, 6pt gap, 12pt
// medium message clipped to one line with a tail ellipsis. The message is full
// white rather than 0.92 -- upstream draws it brighter than its own chrome.
function ErrorOverlayView({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={cn("flex h-full w-full items-center justify-center gap-1.5", pillPaddingClass)}>
      <WarningCircle
        className="size-[13px] shrink-0"
        style={{ color: upstreamRed }}
        weight="fill"
      />
      <span className="min-w-0 truncate text-[12px] font-medium leading-none text-white">
        {message}
      </span>
      <NeutralIconButton label="Retry dictation" onClick={onRetry}>
        <ArrowCounterClockwise className="size-3.5" weight="bold" />
      </NeutralIconButton>
    </div>
  );
}

function NeutralIconButton({ children, label, onClick }: ActionButtonProps) {
  return (
    <Button
      aria-label={label}
      className="size-8 shrink-0 rounded-full bg-white/10 p-0 text-white hover:bg-white/20 focus-visible:ring-white/60"
      onClick={onClick}
      size="icon-tight"
      title={label}
      type="button"
      variant="ghost"
    >
      {children}
    </Button>
  );
}

type ActionButtonProps = {
  children: ReactNode;
  label: string;
  onClick?: () => void;
};
