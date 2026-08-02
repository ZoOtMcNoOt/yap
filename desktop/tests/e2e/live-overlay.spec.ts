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
  await expectSameFrame(root, island);
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
  await expect(root).toHaveScreenshot("live-overlay-hover.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.04,
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
    { key: "Space", label: "Open transform", tabs: 3, workspace: "polish" },
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

async function expectSameFrame(left: Locator, right: Locator) {
  const [leftBox, rightBox] = await Promise.all([left.boundingBox(), right.boundingBox()]);
  expect(leftBox).not.toBeNull();
  expect(rightBox).not.toBeNull();
  expect(rightBox?.x).toBeCloseTo(leftBox?.x ?? 0, 1);
  expect(rightBox?.y).toBeCloseTo(leftBox?.y ?? 0, 1);
  expect(rightBox?.width).toBeCloseTo(leftBox?.width ?? 0, 1);
  expect(rightBox?.height).toBeCloseTo(leftBox?.height ?? 0, 1);
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
