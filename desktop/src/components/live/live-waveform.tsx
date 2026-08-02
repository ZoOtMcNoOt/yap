import { useCallback, useEffect, useRef, type CSSProperties } from "react";

// Ported from FreeFlow's WaveformView / WaveformBar (Sources/RecordingOverlay.swift,
// MIT, revision 7427ca9).
//
// The bar count, the multipliers and the 2-22pt height range were already
// upstream's. What was not, and what makes the difference you notice before you
// can name it, is that upstream drives the bars from wall-clock time at 30fps
// rather than from the audio level alone. Its waveform keeps breathing through
// silence; a level-only waveform freezes the moment the room goes quiet.

const liveOverlayLevelEvent = "yap-live-overlay-level";
// upstream `TimelineView(.animation(minimumInterval: 1.0 / 30.0))`
const frameIntervalMs = 1000 / 30;

const waveformMultipliers = [0.35, 0.55, 0.75, 0.9, 1.0, 0.9, 0.75, 0.55, 0.35] as const;
const waveformCenterIndex = (waveformMultipliers.length - 1) / 2;
// upstream WaveformBar.minHeight / .maxHeight
const barMinHeight = 2;
const barMaxHeight = 22;

export function emitLiveOverlayLevel(level: number) {
  const normalized = Number.isFinite(level) ? Math.min(1, Math.max(0, level)) : 0;
  window.dispatchEvent(new CustomEvent(liveOverlayLevelEvent, { detail: normalized }));
}

/**
 * Upstream's 30fps timeline. Held here rather than in a module of its own
 * because the processing indicator reads the same clock, and upstream computes
 * both from one `TimelineView`.
 *
 * `onFrame` receives seconds since the timing origin and seconds since the last
 * frame. Nothing runs while `active` is false, which is how reduced motion is
 * honoured: not a slower animation, no animation.
 */
export function useOverlayTimeline(
  active: boolean,
  onFrame: (timeSeconds: number, deltaSeconds: number) => void,
) {
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;

  useEffect(() => {
    if (!active) return;
    let handle = 0;
    let previous = performance.now();
    let nextDue = previous;
    const tick = (now: number) => {
      handle = window.requestAnimationFrame(tick);
      if (now < nextDue) return;
      nextDue = now + frameIntervalMs;
      const delta = (now - previous) / 1000;
      previous = now;
      onFrameRef.current(now / 1000, delta);
    };
    handle = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(handle);
  }, [active]);
}

export function LiveWaveform({
  audioLevel,
  prefersReducedMotion,
  showsActivityPulse,
}: {
  audioLevel: number;
  prefersReducedMotion: boolean;
  showsActivityPulse?: boolean;
}) {
  const waveformRef = useRef<HTMLDivElement>(null);
  const targetLevelRef = useRef(audioLevel);
  const smoothedLevelsRef = useRef<number[]>(waveformMultipliers.map(() => audioLevel));
  const animated = !prefersReducedMotion;

  const paint = useCallback((pulseTime: number | null, deltaSeconds: number) => {
    const waveform = waveformRef.current;
    if (!waveform) return;
    const bars = waveform.querySelectorAll<HTMLElement>("[data-live-waveform-bar]");
    const smoothed = smoothedLevelsRef.current;
    const target = targetLevelRef.current;
    bars.forEach((bar, index) => {
      // First-order approach with upstream's per-bar time constant. Upstream
      // uses a spring of the same response; both settle outward from the centre,
      // which is the visible property.
      smoothed[index] = deltaSeconds > 0
        ? smoothed[index]
          + (target - smoothed[index]) * (1 - Math.exp(-deltaSeconds / barResponseSeconds(index)))
        : target;
      const amplitude = barAmplitude(
        smoothed[index] ?? 0,
        waveformMultipliers[index] ?? 0,
        index,
        pulseTime,
      );
      bar.style.transform = `scaleY(${barScale(amplitude)})`;
    });
  }, []);

  useOverlayTimeline(animated, (timeSeconds, deltaSeconds) => {
    paint(showsActivityPulse ? timeSeconds : null, deltaSeconds);
  });

  // With no timeline running there is no frame to pick a new level up, so a
  // reduced-motion overlay redraws on the spot instead — once, without easing.
  const setLevel = useCallback((level: number) => {
    targetLevelRef.current = Number.isFinite(level) ? Math.min(1, Math.max(0, level)) : 0;
    if (!animated) paint(null, 0);
  }, [animated, paint]);

  useEffect(() => {
    const handleLevel = (event: Event) => setLevel((event as CustomEvent<number>).detail);
    window.addEventListener(liveOverlayLevelEvent, handleLevel);
    return () => window.removeEventListener(liveOverlayLevelEvent, handleLevel);
  }, [setLevel]);

  useEffect(() => setLevel(audioLevel), [audioLevel, setLevel]);

  return (
    <div
      aria-hidden="true"
      className="flex h-6 w-12 items-center justify-center gap-[2.5px]"
      data-testid="live-waveform"
      ref={waveformRef}
    >
      {waveformMultipliers.map((multiplier, index) => (
        <span
          // The one sanctioned deviation from the exact FreeFlow port: the
          // bars wear Yap's accent so the most-seen pixel in the product is
          // recognizably ours. Geometry and motion stay upstream's.
          className="live-waveform-bar w-[3px] rounded-full bg-[var(--accent)]"
          data-live-waveform-bar
          key={index}
          style={{
            height: barMaxHeight,
            transform: `scaleY(${barScale(barAmplitude(0, multiplier, index, null))})`,
          } as CSSProperties}
        />
      ))}
    </div>
  );
}

// upstream `barAmplitude(for:pulseTime:)`. `pulseTime` null is upstream's
// `showsActivityPulse == false` branch: the level, and nothing else.
function barAmplitude(
  level: number,
  multiplier: number,
  index: number,
  pulseTime: number | null,
) {
  const baseAmplitude = Math.min(Math.max(level, 0) * multiplier, 1);
  if (pulseTime === null) return baseAmplitude;
  const travelingWave = 0.5 + 0.5 * Math.sin(pulseTime * 6.2 - index * 0.78);
  const shimmer = 0.5 + 0.5 * Math.sin(pulseTime * 3.1 + index * 0.5);
  const pulse = travelingWave * 0.22 + shimmer * 0.06;
  const saturationRelief = baseAmplitude * (0.74 + pulse);
  const quietPulse = (1 - baseAmplitude) * (0.04 + pulse * 0.28);
  return Math.min(saturationRelief + quietPulse, 1);
}

// upstream `barResponse(for:)`. ponytail: upstream also staggers each bar by
// `distance * 0.01`s on top of this. Dropped — at 30fps the outermost bar's
// 40ms lag is one frame of extra ripple over what the response spread already
// produces. Add it back with a per-bar target queue if the ripple reads flat.
function barResponseSeconds(index: number) {
  const normalizedDistance = Math.abs(index - waveformCenterIndex) / waveformCenterIndex;
  return 0.18 + normalizedDistance * 0.06;
}

function barScale(amplitude: number) {
  return (barMinHeight + (barMaxHeight - barMinHeight) * amplitude) / barMaxHeight;
}
