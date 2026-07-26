import { expect, test } from "@playwright/test";

import {
  installQueuedServerBridge,
  languageCalls,
} from "./app-server-bridge";

test("primary-language picker supports labeled keyboard selection and focus return", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");
  await page.getByRole("button", { name: "Open settings" }).click();

  const settings = page.getByRole("dialog", { name: "Settings" });
  const picker = settings.getByRole("combobox", { name: "Primary language" });
  await expect(picker).toBeEnabled();

  await picker.focus();
  await expect(picker).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("option", { name: /French .*fr-FR/ }))
    .toHaveAttribute("data-highlighted", "");
  await page.keyboard.press("Enter");

  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(picker).toBeFocused();
  await expect(picker).toContainText("fr-FR");

  await page.keyboard.press("Tab");
  const save = settings.getByRole("button", { name: "Save" });
  await expect(save).toBeFocused();
  await page.keyboard.press("Enter");

  await expect.poll(() => languageCalls(page)).toEqual([{
    args: {
      catalogRevision: "language-picker-keyboard-test-catalog-v1",
      languageBcp47: "fr-FR",
    },
    command: "confirm_primary_language",
  }]);
});

test("language settings remain visible without horizontal clipping in a narrow window", async ({ page }) => {
  await page.setViewportSize({ height: 760, width: 390 });
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");
  await page.getByRole("button", { name: "Open settings" }).click();

  const settings = page.getByRole("dialog", { name: "Settings" });
  const picker = settings.getByRole("combobox", { name: "Primary language" });
  await expect(settings).toBeVisible();
  await expect(picker).toBeVisible();

  const [settingsBox, pickerBox] = await Promise.all([
    settings.boundingBox(),
    picker.boundingBox(),
  ]);
  expect(settingsBox).not.toBeNull();
  expect(pickerBox).not.toBeNull();
  expect(settingsBox!.x).toBeGreaterThanOrEqual(0);
  expect(settingsBox!.x + settingsBox!.width).toBeLessThanOrEqual(390);
  expect(pickerBox!.width).toBeGreaterThanOrEqual(180);
  expect(pickerBox!.x).toBeGreaterThanOrEqual(settingsBox!.x);
  expect(pickerBox!.x + pickerBox!.width)
    .toBeLessThanOrEqual(settingsBox!.x + settingsBox!.width);
});

test("main workspace reflows at a 200-percent-equivalent viewport", async ({ page }) => {
  await page.setViewportSize({ height: 480, width: 320 });
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");

  const sidebar = page.locator('[data-slot="sidebar-container"]');
  const workspace = page.locator(".surface-workspace");
  await expect(workspace).toBeVisible();

  const sidebarBox = await sidebar.boundingBox();
  expect(sidebarBox).not.toBeNull();
  expect(sidebarBox!.width).toBeLessThanOrEqual(52);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await expect(page.getByRole("button", { name: "Open settings" })).toBeVisible();
});
