import { expect, type Locator, type Page, test } from "@playwright/test";

type Frame = { height: number; width: number };

const previewUrl = "/?window=live-overlay&preview=live-overlay";
// FreeFlow's pill geometry (see overlay_window.rs::frame). The recording pill
// has two widths because only hands-free recording shows a stop badge, and the
// failure pill is sized from its message -- "Mic denied" lands on the 180pt
// clamp floor.
const frames = {
  collapsed: { height: 38, width: 92 },
  expanded: { height: 96, width: 180 },
  feedback: { height: 38, width: 180 },
  recording: { height: 38, width: 92 },
  recordingHandsFree: { height: 38, width: 150 },
  success: { height: 38, width: 94 },
} satisfies Record<string, Frame>;

test.describe.configure({ timeout: 45_000 });

test("hidden idle preference renders no island", async ({ page }) => {
  await openOverlayPreview(page, "&visibility=hidden&status=idle");

  await expect(page.getByTestId("live-overlay-root")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start dictating" })).toHaveCount(0);
});

test("showing a previously expanded hidden island always returns collapsed", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  await page.mouse.move(52, 20);
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");
  await setLiveView(page, { visibility: "hidden" });
  await expect(root).toHaveCount(0);
  await moveOutsideIsland(page);
  await setLiveView(page, { visibility: "enabled" });
  await expect(root).toHaveAttribute("data-overlay-surface", "collapsed");
  await expectExactFrame(root, frames.collapsed);
});

// Windows only, and not for convenience. When collapsed the root and the island
// occupy the same frame as the whole viewport, so the opening assertion that the
// surface is still collapsed holds only while no pointer event has reached the
// fresh document — which is why the helper parks the cursor before navigating
// rather than after. Chromium's Linux headless shell synthesizes a mouseover at
// the parked position on load and the island expands before the first
// assertion; the Windows browser CI actually ships on does not. No cursor
// position avoids it, because when collapsed the island is the viewport.
// Every other case in this file runs everywhere.
test("one visible island expands downward quickly without taking focus", async ({ page }) => {
  // Inside the body on purpose: at file scope this form skips every test in the
  // file, which silently disabled all eleven when first written here.
  test.skip(process.platform !== "win32", "collapsed-at-load needs a browser that does not synthesize hover");
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  const island = page.getByTestId("live-overlay-island");
  await expect(root).toHaveAttribute("data-overlay-surface", "collapsed");
  await expectExactFrame(root, frames.collapsed);
  // Not `expectSameFrame` any more: at rest the island is tucked into the bezel,
  // so there is no visible island for the window to coincide with. The window
  // still holds the collapsed frame it will reveal into, which is what the
  // assertion above covers.
  await expectRetracted(root, island);
  await expect(page.getByLabel("Yap dictation island")).toBeVisible();

  const focusedBefore = await focusedElement(page);
  const startedAt = await page.evaluate(() => performance.now());
  await root.hover({ position: { x: 52, y: 20 } });
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");
  const expandedAt = await page.evaluate(() => performance.now());

  expect(expandedAt - startedAt).toBeLessThanOrEqual(220);
  expect(await focusedElement(page)).toEqual(focusedBefore);
  await expectExactFrame(root, frames.expanded);
  await expectSameFrame(root, island);
  await expect(page.getByRole("button", { name: "Start dictating" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open scratch" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open transform" })).toBeVisible();
  await expectControlsInside(island, [
    page.getByRole("button", { name: "Start dictating" }),
    page.getByRole("button", { name: "Open scratch" }),
    page.getByRole("button", { name: "Open transform" }),
  ]);
  // 1% rather than the 4% this carried before the port. Measured, not guessed:
  // porting the panel to FreeFlow -- 38pt header, 11pt text, white instead of
  // fuchsia, square top corners -- moved 344 of 17,280 pixels, 1.99%. At 4% a
  // restyle that complete passed unnoticed and left this baseline showing an
  // island that no longer existed. 1% keeps roughly a 170-pixel allowance for
  // antialiasing while still failing on a change of that size.
  // If a runner-image font change ever makes this flaky, raise it from an
  // observed noise ratio rather than back to a round number.
  await expect(root).toHaveScreenshot("live-overlay-hover.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.01,
  });
});

test("keyboard focus expands the island and exposes 40-pixel primary actions", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  await root.focus();
  await expect(root).toBeFocused();
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");

  const actions = [
    page.getByRole("button", { name: "Start dictating" }),
    page.getByRole("button", { name: "Open scratch" }),
    page.getByRole("button", { name: "Open transform" }),
  ];
  await page.keyboard.press("Tab");
  await expect(actions[0]).toBeFocused();
  for (const action of actions) {
    const bounds = await action.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.height).toBeGreaterThanOrEqual(39.9);
    expect(bounds!.width).toBeGreaterThanOrEqual(39.9);
  }
});

test("focused Start dictating preserves native Enter activation", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  const start = page.getByRole("button", { name: "Start dictating" });
  await root.focus();
  await page.keyboard.press("Tab");
  await expect(start).toBeFocused();

  await page.keyboard.press("Enter");

  await expect(root).toHaveAttribute("data-overlay-phase", "recording");
  await expect(start).toHaveCount(0);
});

test("focused workspace controls preserve native Enter and Space activation", async ({ page }) => {
  for (const action of [
    { key: "Enter", label: "Open scratch", tabs: 2, workspace: "home" },
    { key: "Space", label: "Open transform", tabs: 3, workspace: "correct" },
  ]) {
    await openOverlayPreview(page);
    await installInvokeCapture(page);

    const root = page.getByTestId("live-overlay-root");
    const control = page.getByRole("button", { name: action.label });
    await root.focus();
    for (let tab = 0; tab < action.tabs; tab += 1) {
      await page.keyboard.press("Tab");
    }
    await expect(control).toBeFocused();

    await page.keyboard.press(action.key);

    await expect.poll(() => capturedWorkspace(page)).toBe(action.workspace);
  }
});

test("collapse grace keeps the visible pointer target before shrinking", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  await root.hover({ position: { x: 52, y: 20 } });
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");

  await moveOutsideIsland(page);
  await page.waitForTimeout(120);
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");

  await expect(root).toHaveAttribute("data-overlay-surface", "collapsed", { timeout: 500 });
  await expectExactFrame(root, frames.collapsed);
});

test("hover expansion p95 stays within the 220 ms interaction budget", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  const samples: number[] = [];
  for (let index = 0; index < 20; index += 1) {
    const startedAt = await page.evaluate(() => performance.now());
    await page.mouse.move(52, 20);
    await expect(root).toHaveAttribute("data-overlay-surface", "expanded");
    samples.push((await page.evaluate(() => performance.now())) - startedAt);
    await waitForAnimationFrames(page, 2);
    await moveOutsideIsland(page);
    await expect(root).toHaveAttribute("data-overlay-surface", "collapsed", { timeout: 500 });
  }

  samples.sort((left, right) => left - right);
  const p95 = samples[Math.ceil(samples.length * 0.95) - 1] ?? Number.POSITIVE_INFINITY;
  expect(p95).toBeLessThanOrEqual(220);
});

test("reduced motion keeps every native-frame projection complete", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  const island = page.getByTestId("live-overlay-island");
  await root.hover({ position: { x: 52, y: 20 } });
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");
  await expectSameFrame(root, island);

  await setLiveView(page, {
    activeCaptureMode: "pushToTalk",
    captureMode: "pushToTalk",
    level: 0,
    status: "armed",
  });
  await expect(root).toHaveAttribute("data-overlay-surface", "initializing");
  await expectExactFrame(root, frames.recording);
  await expectSameFrame(root, island);
  await expect(page.getByTestId("live-recording-layout")).toBeVisible();

  await setLiveView(page, {
    activeCaptureMode: "pushToTalk",
    captureMode: "pushToTalk",
    level: 0.12,
    status: "speaking",
  });
  const waveform = page.getByTestId("live-waveform");
  await expect(waveform).toBeVisible();
  const before = await waveformBarHeights(waveform);
  await waitForAnimationFrames(page, 3);
  expect(await waveformBarHeights(waveform)).toEqual(before);
  await expectSameFrame(root, island);
});

// The suite already asserts the waveform holds still under reduced motion. On
// its own that is the wrong half: a waveform that froze everywhere would pass
// it, and freezing in silence is exactly what this overlay used to do. Upstream
// drives the bars from wall-clock time so they breathe with no audio at all, and
// hands over to a rotating spinner a second into transcription.
test("the waveform breathes with no audio and transcription reaches the spinner", async ({ page }) => {
  // Through the query rather than an event: the preview reads the query while
  // mounting, so there is no window between paint and the listener being
  // attached for a dispatched state to fall into.
  await openOverlayPreview(page, "&activeCaptureMode=pushToTalk&level=0&status=speaking");

  const waveform = page.getByTestId("live-waveform");
  await expect(waveform).toBeVisible();

  const samples: string[] = [];
  for (let index = 0; index < 3; index += 1) {
    samples.push(JSON.stringify(await waveformBarHeights(waveform)));
    await page.waitForTimeout(220);
  }
  expect(new Set(samples).size, `bars never moved at level 0: ${samples[0]}`).toBeGreaterThan(1);

  await setLiveView(page, { activeCaptureMode: "toggle", level: 0, status: "saving" });
  const spinner = page.getByTestId("live-processing-spinner");
  await expect(spinner).toBeVisible({ timeout: 5_000 });
  const firstRotation = await spinner.evaluate((node) => getComputedStyle(node).transform);
  expect(firstRotation).not.toBe("none");
  await expect
    .poll(() => spinner.evaluate((node) => getComputedStyle(node).transform))
    .not.toBe(firstRotation);
});

// The island hides in the bezel instead of sitting on top of the screen all
// day. Asserted on the rendered offset rather than on a class or an attribute,
// because "it is out of sight" is the property -- an island that reported
// itself retracted while still painting over the desktop would pass either of
// those and fail the user.
test("the island hides in the bezel and comes back for the pointer or for dictation", async ({ page }) => {
  await openOverlayPreview(page);
  const root = page.getByTestId("live-overlay-root");
  const island = page.getByTestId("live-overlay-island");
  // After navigation the cursor sits at 0,0, which is inside the island.
  await moveOutsideIsland(page);

  const offset = async () => {
    const [rootBox, islandBox] = await Promise.all([root.boundingBox(), island.boundingBox()]);
    return Math.round((islandBox?.y ?? 0) - (rootBox?.y ?? 0));
  };
  const height = async () => Math.round((await island.boundingBox())?.height ?? 0);

  // Fully clear of its own frame, not merely nudged.
  await expect.poll(offset).toBeLessThanOrEqual(-(await height()));
  await expect(island).toHaveAttribute("data-overlay-revealed", "false");

  await page.mouse.move(46, 6);
  await expect(island).toHaveAttribute("data-overlay-revealed", "true");
  await expect.poll(offset).toBe(0);

  await moveOutsideIsland(page);
  await expect(island).toHaveAttribute("data-overlay-revealed", "false");
  await expect.poll(offset).toBeLessThanOrEqual(-(await height()));

  // Dictation holds it out with the pointer nowhere near it.
  await setLiveView(page, { activeCaptureMode: "toggle", level: 0.7, status: "speaking" });
  await expect(island).toHaveAttribute("data-overlay-revealed", "true");
  await expect.poll(offset).toBe(0);
});

test("live state transitions keep the reused window equal to visible content", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  const island = page.getByTestId("live-overlay-island");
  await root.hover({ position: { x: 52, y: 20 } });
  await expect(root).toHaveAttribute("data-overlay-surface", "expanded");

  await setLiveView(page, {
    activeCaptureMode: "pushToTalk",
    captureMode: "pushToTalk",
    level: 0.72,
    status: "speaking",
  });
  await expect(root).toHaveAttribute("data-overlay-surface", "recording");
  await expectExactFrame(root, frames.recording);
  await expectSameFrame(root, island);
  await expect(page.getByTestId("live-waveform")).toBeVisible();
  await expect(page.getByRole("button", { name: "Finish recording" })).toHaveCount(0);

  await setLiveView(page, {
    activeCaptureMode: "toggle",
    captureMode: "pushToTalk",
    level: 0.84,
    status: "speaking",
  });
  await expect(root).toHaveAttribute("data-overlay-surface", "recording");
  await expectExactFrame(root, frames.recordingHandsFree);
  await expect(page.getByRole("button", { name: "Finish recording" })).toBeVisible();
  await expectControlsInside(island, [
    page.getByTestId("live-waveform"),
    page.getByRole("button", { name: "Finish recording" }),
  ]);

  // Upstream locks the recording width through transcription rather than
  // snapping the pill narrow the moment the stop badge disappears.
  await setLiveView(page, {
    activeCaptureMode: "toggle",
    captureMode: "pushToTalk",
    level: 0,
    status: "saving",
  });
  await expect(root).toHaveAttribute("data-overlay-surface", "processing");
  await expectExactFrame(root, frames.recordingHandsFree);
  await expectSameFrame(root, island);

  await setLiveView(page, {
    activeCaptureMode: undefined,
    captureMode: "toggle",
    hasFinalText: true,
    level: 0,
    status: "idle",
  });
  await expect(root).toHaveAttribute("data-overlay-surface", "success");
  await expectExactFrame(root, frames.success);
  await expectSameFrame(root, island);
  await expect(page.getByText("Saved")).toBeVisible();

  await setLiveView(page, {
    error: "Mic denied",
    hasFinalText: false,
    level: 0,
    status: "blocked",
  });
  await expect(root).toHaveAttribute("data-overlay-surface", "feedback");
  await expectExactFrame(root, frames.feedback);
  await expectSameFrame(root, island);
  await expect(page.getByRole("button", { name: "Retry dictation" })).toBeVisible();
  await expectControlsInside(island, [page.getByRole("button", { name: "Retry dictation" })]);
});

test("rapid hover and state reversals settle to the latest exact surface", async ({ page }) => {
  await openOverlayPreview(page);

  const root = page.getByTestId("live-overlay-root");
  const island = page.getByTestId("live-overlay-island");
  for (let index = 0; index < 5; index += 1) {
    await page.mouse.move(52, 20);
    await expect(root).toHaveAttribute("data-overlay-surface", "expanded");
    await waitForAnimationFrames(page, 2);
    await moveOutsideIsland(page);
    await expect(root, `iteration ${index}`).toHaveAttribute("data-overlay-surface", "collapsed", { timeout: 500 });
  }

  await dispatchPreviewSequence(page, [
    { activeCaptureMode: "pushToTalk", level: 0, status: "armed" },
    { activeCaptureMode: "pushToTalk", level: 0.7, status: "speaking" },
    { activeCaptureMode: "pushToTalk", level: 0, status: "saving" },
    { activeCaptureMode: "toggle", level: 0.85, status: "speaking" },
    { activeCaptureMode: "toggle", error: "Transient", level: 0, status: "blocked" },
    { activeCaptureMode: "toggle", error: undefined, level: 0.92, status: "speaking" },
  ]);

  await expect(root).toHaveAttribute("data-overlay-surface", "recording");
  await expectExactFrame(root, frames.recordingHandsFree);
  await expectSameFrame(root, island);
  await expect(page.getByRole("button", { name: "Finish recording" })).toBeVisible();
});

async function openOverlayPreview(page: Page, query = "") {
  await page.setViewportSize({ height: 140, width: 300 });
  await page.mouse.move(260, 120);
  await page.goto(`${previewUrl}${query}`);
}

async function moveOutsideIsland(page: Page) {
  await page.mouse.move(299, 139, { steps: 4 });
}

async function setLiveView(page: Page, detail: Record<string, unknown>) {
  await page.evaluate((nextView) => {
    window.dispatchEvent(new CustomEvent("yap-live-overlay-preview", { detail: nextView }));
  }, detail);
}

async function dispatchPreviewSequence(page: Page, states: Array<Record<string, unknown>>) {
  await page.evaluate(async (nextStates) => {
    for (const nextView of nextStates) {
      window.dispatchEvent(new CustomEvent("yap-live-overlay-preview", { detail: nextView }));
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    }
  }, states);
}

async function focusedElement(page: Page) {
  return page.evaluate(() => ({
    ariaLabel: document.activeElement?.getAttribute("aria-label") ?? null,
    tagName: document.activeElement?.tagName ?? null,
  }));
}

async function installInvokeCapture(page: Page) {
  await page.evaluate(() => {
    const testWindow = window as typeof window & {
      __TAURI_INTERNALS__?: {
        invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
      };
      __yapCapturedWorkspace?: string;
    };
    testWindow.__TAURI_INTERNALS__ ??= {};
    testWindow.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "show_main_workspace") {
        testWindow.__yapCapturedWorkspace = String(args?.workspace ?? "");
      }
      return null;
    };
  });
}

async function capturedWorkspace(page: Page) {
  return page.evaluate(() =>
    (window as typeof window & { __yapCapturedWorkspace?: string }).__yapCapturedWorkspace);
}

async function expectExactFrame(locator: Locator, frame: Frame) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.width).toBeCloseTo(frame.width, 1);
  expect(box?.height).toBeCloseTo(frame.height, 1);
}

// The island slides out of the bezel on a 180 ms curve and `boundingBox()`
// includes that transform, so the window and the painted island coincide only
// once it has arrived. Polled rather than sampled: the property under test is
// where it settles, and pinning the animation's duration into the assertion
// would make the test fail the next time the curve is tuned.
// Clear of its own frame, not merely nudged: an island that reported itself
// retracted while still painting over the desktop would fail the user.
async function expectRetracted(root: Locator, island: Locator) {
  await expect
    .poll(async () => {
      const [rootBox, islandBox] = await Promise.all([root.boundingBox(), island.boundingBox()]);
      if (!rootBox || !islandBox) return 1;
      return Math.round(islandBox.y - rootBox.y) + Math.round(islandBox.height);
    }, { timeout: 5_000 })
    .toBeLessThanOrEqual(0);
}

async function expectSameFrame(left: Locator, right: Locator) {
  await expect
    .poll(async () => {
      const [leftBox, rightBox] = await Promise.all([left.boundingBox(), right.boundingBox()]);
      if (!leftBox || !rightBox) return "missing";
      return [
        Math.round(rightBox.x - leftBox.x),
        Math.round(rightBox.y - leftBox.y),
        Math.round(rightBox.width - leftBox.width),
        Math.round(rightBox.height - leftBox.height),
      ].join(",");
    }, { timeout: 5_000 })
    .toBe("0,0,0,0");
}

async function expectControlsInside(container: Locator, controls: Locator[]) {
  const parent = await container.boundingBox();
  expect(parent).not.toBeNull();
  for (const control of controls) {
    const child = await control.boundingBox();
    expect(child).not.toBeNull();
    expect((child?.x ?? 0) + 0.5).toBeGreaterThanOrEqual(parent?.x ?? 0);
    expect((child?.y ?? 0) + 0.5).toBeGreaterThanOrEqual(parent?.y ?? 0);
    expect((child?.x ?? 0) + (child?.width ?? 0)).toBeLessThanOrEqual((parent?.x ?? 0) + (parent?.width ?? 0) + 0.5);
    expect((child?.y ?? 0) + (child?.height ?? 0)).toBeLessThanOrEqual((parent?.y ?? 0) + (parent?.height ?? 0) + 0.5);
  }
}

// The rendered height, not the styled one. The bars are a fixed 22px box scaled
// on the Y axis, so `getComputedStyle(bar).height` reports 22 forever and would
// hold still through any amount of animation -- this assertion proved nothing
// until it started reading the box the user actually sees.
async function waveformBarHeights(waveform: Locator) {
  return waveform.locator("span").evaluateAll((bars) =>
    bars.map((bar) => Math.round(bar.getBoundingClientRect().height * 100) / 100));
}

async function waitForAnimationFrames(page: Page, count: number) {
  await page.evaluate(async (frameCount) => {
    for (let frame = 0; frame < frameCount; frame += 1) {
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    }
  }, count);
}
