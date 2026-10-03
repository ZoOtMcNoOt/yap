import { expect, test } from "@playwright/test";
import { installWorkspaceAcceptanceBridge } from "./workspace-acceptance-bridge";

function contrast(first: string, second: string) {
  const luminance = (color: string) => {
    const channels = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map((value) => {
      const normalized = value / 255;
      return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  const [dark, light] = [luminance(first), luminance(second)].sort((a, b) => a - b);
  return (light + 0.05) / (dark + 0.05);
}

test("rendered knowledge text and form boundaries have readable contrast", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  const field = page.getByRole("textbox", { name: "What reviewed information are you looking for?" });
  const colors = await field.evaluate((node) => {
    const style = getComputedStyle(node);
    return { text: style.color, background: style.backgroundColor, border: style.borderTopColor };
  });
  expect(contrast(colors.text, colors.background)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(colors.border, colors.background)).toBeGreaterThanOrEqual(3);
  const help = await page.locator("#librarian-search-help").evaluate((node) => ({
    color: getComputedStyle(node).color,
    background: getComputedStyle(node.closest('[data-slot="card"]')!).backgroundColor,
  }));
  expect(contrast(help.color, help.background)).toBeGreaterThanOrEqual(4.5);
});

for (const viewport of [
  { width: 360, height: 640 },
  { width: 720, height: 520 },
  { width: 1440, height: 900 },
]) {
  test(`refreshed knowledge navigation fits ${viewport.width}×${viewport.height} and remains keyboard operable`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installWorkspaceAcceptanceBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    const tasks = page.getByRole("tablist", { name: "Knowledge tasks" });
    await expect(tasks).toBeVisible();
    const bounds = await tasks.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
    await page
      .getByRole("tab", { name: "Search sources", exact: true })
      .focus();
    await page.keyboard.press("ArrowRight");
    await expect(
      page.getByRole("tab", { name: "Ask a question", exact: true }),
    ).toBeFocused();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(viewport.width);
  });
}

test("changing motion preference stops the waveform and revealing the island retains keyboard access", async ({
  page,
}) => {
  await page.setViewportSize({ width: 300, height: 140 });
  await page.goto(
    "/?window=live-overlay&preview=live-overlay&status=speaking&level=0.6",
  );
  const bars = page.locator("[data-live-waveform-bar]");
  await expect(bars).toHaveCount(9);
  const first = await bars.first().getAttribute("style");
  await expect.poll(() => bars.first().getAttribute("style")).not.toBe(first);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.getByTestId("live-overlay-island")).toHaveCSS(
    "transition-property",
    "none",
  );
  const reduced = await bars.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("style")),
  );
  await page.waitForTimeout(160);
  expect(
    await bars.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("style")),
    ),
  ).toEqual(reduced);
  await page.evaluate(() =>
    window.dispatchEvent(
      new CustomEvent("yap-live-overlay-preview", {
        detail: { status: "idle", level: 0, hasFinalText: false },
      }),
    ),
  );
  await page.getByTestId("live-overlay-root").focus();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Start dictating" }),
  ).toBeFocused();
});

test("increased contrast replaces island transparency with an opaque readable surface", async ({
  page,
}) => {
  await page.emulateMedia({ contrast: "more", reducedMotion: "reduce" });
  await page.goto("/?window=live-overlay&preview=live-overlay");
  await page.getByTestId("live-overlay-root").focus();
  const island = page.getByTestId("live-overlay-island");
  await expect(island).toHaveCSS("backdrop-filter", "none");
  await expect(island).toHaveCSS("background-color", "rgb(24, 36, 46)");
  await expect(island).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(
    page.getByRole("button", { name: "Start dictating" }),
  ).toBeEnabled();
});

test("the waveform clock pauses on visibility loss and resumes without changing the recording state", async ({
  page,
}) => {
  await page.goto(
    "/?window=live-overlay&preview=live-overlay&status=speaking&level=0.6",
  );
  const bars = page.locator("[data-live-waveform-bar]");
  await expect(bars).toHaveCount(9);
  // Exercise the document lifecycle handler; this does not qualify native tray visibility.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hidden = await bars.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("style")),
  );
  await page.waitForTimeout(160);
  expect(
    await bars.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("style")),
    ),
  ).toEqual(hidden);
  await expect(page.getByTestId("live-overlay-root")).toHaveAttribute(
    "data-overlay-phase",
    "recording",
  );
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect
    .poll(() =>
      bars.evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("style")),
      ),
    )
    .not.toEqual(hidden);
});
