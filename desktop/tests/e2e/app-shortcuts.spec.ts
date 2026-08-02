import { expect, test } from "@playwright/test";

import {
  installQueuedServerBridge,
  shortcutCalls,
} from "./app-server-bridge";


test("shortcut settings delegate physical recording to native commands and expose per-action reset", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");
  // Through the sidebar, which is now the only settings entry point: the
  // header carried a second gear opening the same surface.
  await page.getByRole("button", { name: "Settings", exact: true }).click();

  const settings = page.getByRole("dialog", { name: "Settings" });
  const dictationRow = settings.getByText("Dictation shortcut", { exact: true }).locator("xpath=../..");
  await expect(dictationRow).toContainText("Ctrl+Shift+Space");

  // The paste shortcut is an Advanced setting: absent until disclosed.
  await expect(settings.getByText("Paste-last shortcut", { exact: true })).toHaveCount(0);
  await settings.getByRole("button", { name: "Advanced", exact: true }).click();
  const pasteRow = settings.getByText("Paste-last shortcut", { exact: true }).locator("xpath=../..");
  await expect(pasteRow).toContainText("Ctrl+Shift+Alt+V");
  await expect(dictationRow.getByRole("textbox")).toHaveCount(0);
  await expect(pasteRow.getByRole("textbox")).toHaveCount(0);

  await page.keyboard.press("A");
  expect(await shortcutCalls(page)).toEqual([]);

  await dictationRow.getByRole("button", { name: "Record shortcut" }).click();
  await expect(dictationRow).toContainText("Ctrl+Shift+D");

  await pasteRow.getByRole("button", { name: "Record shortcut" }).click();
  await expect(pasteRow).toContainText("Ctrl+Shift+Alt+P");

  await pasteRow.getByRole("button", { name: "Reset" }).click();
  await expect(pasteRow).toContainText("Ctrl+Shift+Alt+V");
  const calls = await shortcutCalls(page);
  expect(calls.map(({ command }) => command)).toEqual([
    "record_live_hotkey",
    "record_live_paste_hotkey",
    "reset_live_paste_hotkey",
  ]);
  expect(calls.slice(0, 2).every(({ args }) =>
    !args || !("hotkey" in (args as Record<string, unknown>))
  )).toBe(true);
});
