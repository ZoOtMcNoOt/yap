import { expect, test, type Page } from "@playwright/test";
import { installRecordingJourneyBridge, journeyTranscript } from "./recording-journey-bridge";

async function installExportBridge(page: Page) {
  await installRecordingJourneyBridge(page, "complete");
  await page.addInitScript(() => {
    const host = globalThis as unknown as {
      __TAURI_INTERNALS__: { invoke: (command: string, args?: unknown) => Promise<unknown> };
    };
    const baseInvoke = host.__TAURI_INTERNALS__.invoke;
    const fixture = {
      calls: [] as unknown[],
      mode: "saved",
      finish: undefined as (() => void) | undefined,
    };
    Object.assign(globalThis, { __transcriptExport: fixture });
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "server_connection_status" || command === "refresh_server_connection") {
        return { ...await baseInvoke(command, args) as object, state: "offline", errorCode: "SERVER_UNREACHABLE" };
      }
      if (command !== "export_transcript") return baseInvoke(command, args);
      fixture.calls.push(args);
      if (fixture.mode === "failed") throw "Could not save the export. Check the destination and permissions, then retry.";
      if (fixture.mode === "cancelled") return { status: "cancelled" };
      if (fixture.mode === "pending") await new Promise<void>((resolve) => { fixture.finish = resolve; });
      return { status: "saved", path: "C:\\Exports\\transcript-export.txt" };
    };
  });
}

async function mode(page: Page, value: string) {
  await page.evaluate((value) => {
    (globalThis as unknown as { __transcriptExport: { mode: string } }).__transcriptExport.mode = value;
  }, value);
}

async function review(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Review recording restored.mp3", exact: true }).click();
  return page.getByRole("dialog", { name: "restored.mp3", exact: true });
}

test("exports the selected original through native ownership while the server is offline", async ({ page }) => {
  await installExportBridge(page);
  const dialog = await review(page);
  await expect(dialog.locator("pre")).toHaveText(journeyTranscript);
  await dialog.getByRole("button", { name: "Export original transcript for restored.mp3", exact: true }).click();
  await expect(page.getByText("Transcript exported", { exact: true })).toBeVisible();
  const calls = await page.evaluate(() => (globalThis as unknown as {
    __transcriptExport: { calls: unknown[] };
  }).__transcriptExport.calls);
  expect(calls).toEqual([{ path: "C:\\Yap\\remote-jobs\\restored-1\\transcript.txt" }]);
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("pre")).toHaveText(journeyTranscript);
  await expect(page.getByText("Server offline", { exact: true })).toBeVisible();
});

test("cancelling the native picker preserves review and does not claim a saved export", async ({ page }) => {
  await installExportBridge(page);
  const dialog = await review(page);
  await mode(page, "cancelled");
  const button = dialog.getByRole("button", { name: "Export original transcript for restored.mp3", exact: true });
  await button.click();
  await expect(page.getByText("Export cancelled", { exact: true })).toBeVisible();
  await expect(page.getByText("Transcript exported", { exact: true })).toHaveCount(0);
  await expect(dialog.locator("pre")).toHaveText(journeyTranscript);
  await expect(button).toBeEnabled();
  await expect(button).toBeFocused();
});

test("failed export keeps the selected source and supports an explicit successful retry", async ({ page }) => {
  await installExportBridge(page);
  const dialog = await review(page);
  await mode(page, "failed");
  const button = dialog.getByRole("button", { name: "Export original transcript for restored.mp3", exact: true });
  await button.click();
  await expect(dialog.getByRole("alert")).toContainText("Check the destination and permissions");
  await expect(page.getByText("Transcript exported", { exact: true })).toHaveCount(0);
  await expect(dialog.locator("pre")).toHaveText(journeyTranscript);
  await mode(page, "saved");
  await button.click();
  await expect(page.getByText("Transcript exported", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => (globalThis as unknown as { __transcriptExport: { calls: unknown[] } }).__transcriptExport.calls.length)).toBe(2);
});

test("pending native export prevents duplicate submission even after review is reopened", async ({ page }) => {
  await installExportBridge(page);
  const dialog = await review(page);
  await mode(page, "pending");
  const button = dialog.getByRole("button", { name: "Export original transcript for restored.mp3", exact: true });
  await button.click();
  await expect(button).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Review recording restored.mp3", exact: true }).click();
  await expect(button).toBeDisabled();
  await page.evaluate(() => (globalThis as unknown as { __transcriptExport: { finish: () => void } }).__transcriptExport.finish());
  await expect(button).toBeEnabled();
  await expect(dialog.locator("pre")).toHaveText(journeyTranscript);
  expect(await page.evaluate(() => (globalThis as unknown as { __transcriptExport: { calls: unknown[] } }).__transcriptExport.calls.length)).toBe(1);
});

test("export remains keyboard accessible and the action toolbar fits a narrow window", async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 520 });
  await installExportBridge(page);
  const dialog = await review(page);
  const button = dialog.getByRole("button", { name: "Export original transcript for restored.mp3", exact: true });
  for (let index = 0; index < 20; index++) {
    if (await button.evaluate((element) => element === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  await expect(button).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Transcript exported", { exact: true })).toBeVisible();
  const toolbar = dialog.getByRole("group", { name: "Transcript actions", exact: true });
  expect(await toolbar.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});
