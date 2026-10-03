import { installQueuedServerBridge, languageCalls } from "./app-server-bridge";
import { expect, test } from "@playwright/test";


test("main app renders the home surface", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Welcome back")).toBeVisible();
  await expect(page.getByRole("button", { name: "Home" })).toBeVisible();
});


test("browser preview keeps its startup status and local setup labels", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Preview", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "About", exact: true }).click();
  await expect(page.getByText("Tauri bridge", { exact: true })).toBeVisible();
});

test("production surface exposes transcript correction without a renderer model path", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator('[data-sidebar="menu-button"]').filter({ hasText: /^Correct$/ }))
    .toBeVisible();
});

test("Settings and Help remain one mutually exclusive modal surface", async ({ page }) => {
  await page.goto("/");

  const settingsButton = page.locator('[data-sidebar="menu-button"]').filter({ hasText: /^Settings$/ });
  const helpButton = page.locator('[data-sidebar="menu-button"]').filter({ hasText: /^Help$/ });

  await settingsButton.click();
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();

  await helpButton.evaluate((button) => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  await expect(page.getByRole("dialog", { name: "Help" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(1);

  await settingsButton.evaluate((button) => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Help" })).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(1);
});

test("first run saves a language and shows readiness without claiming verified dictation", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true });
  await page.goto("/");

  const takeover = page.getByTestId("first-run-welcome");
  await expect(takeover).toBeVisible();
  await expect(page.getByTestId("first-run-language")).toContainText("English");
  await takeover.getByRole("button", { name: "Confirm language", exact: true }).click();
  await expect(takeover.getByRole("heading", { name: "Choose how to transcribe" })).toBeFocused();
  await expect(takeover).toContainText("Transcription engine ready");
  await expect(takeover).toContainText("Set your microphone and shortcut in Settings, then try your first dictation.");
  await expect(page.getByTestId("first-run-practice")).toHaveCount(0);
  await expect(page.getByText("Nothing left this computer.")).toHaveCount(0);
  await takeover.getByRole("button", { name: "Explore Yap", exact: true }).click();
  await expect(takeover).toHaveCount(0);
  await expect(page.getByText("Welcome back")).toBeVisible();

  expect(await languageCalls(page)).toEqual([{
    args: { catalogRevision: null, languageBcp47: "en-US" },
    command: "confirm_primary_language",
  }]);
  await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);
  await expect(page.getByText("Hidden transcript cleanup could not be completed.")).toHaveCount(0);
});

test("Transcribe and Help describe the organization server queue", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Transcribe", exact: true }).click();

  await expect(page.getByText("Add recordings to your organization's transcription queue.", { exact: true }))
    .toBeVisible();
  // The browser preview cannot complete a first run, so the takeover stays
  // out of it and the ordinary import hero shows directly.
  await expect(page.getByTestId("first-run-welcome")).toHaveCount(0);
  await expect(page.getByText("Drop recordings here")).toBeVisible();
  await expect(page.getByText("Private on this device", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Drop files to run", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Set up transcription above to start adding recordings.", { exact: true }))
    .toBeVisible();

  await page.locator('[data-sidebar="menu-button"]').filter({ hasText: /^Help$/ }).click();
  await expect(page.getByRole("dialog", { name: "Help" })).toContainText("Choose files");
  await expect(page.getByRole("dialog", { name: "Help" })).toContainText("organization server queue");
});
