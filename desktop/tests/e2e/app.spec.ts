import { installQueuedServerBridge, languageCalls } from "./app-server-bridge";
import { expect, test } from "@playwright/test";


test("main app renders the home surface", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Welcome back")).toBeVisible();
  await expect(page.getByRole("button", { name: "Home" })).toBeVisible();
});


test("browser preview keeps its startup status and auth labels", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Preview", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "About", exact: true }).click();
  await expect(page.getByText("Tauri bridge", { exact: true })).toBeVisible();
});

test("production surface hides the development-only Polish workspace", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator('[data-sidebar="menu-button"]').filter({ hasText: /^Polish$/ }))
    .toHaveCount(0);
  await expect(page.getByText("Polish unavailable", { exact: true })).toHaveCount(0);
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

// The first version of the welcome card had a button that opened Settings and
// a gate that never cleared without a server. This drives the whole flow the
// way a person does: pick, confirm, card yields — and asserts both that the
// LOCAL confirmation path was taken (catalogRevision null: there is no server
// catalog to name) and that Settings never opened.
test("first run confirms a dictation language in place and never opens Settings", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Transcribe", exact: true }).click();

  await expect(page.getByTestId("first-run-welcome")).toBeVisible();
  // The OS-locale suggestion arrives preselected from the local catalog.
  await expect(page.getByTestId("first-run-language")).toContainText("English");

  await page.getByRole("button", { name: "Confirm", exact: true }).click();

  // The card yields to the ordinary import hero without navigation.
  await expect(page.getByTestId("first-run-welcome")).toHaveCount(0);
  await expect(page.getByText("Drop recordings here")).toBeVisible();

  const confirmations = await languageCalls(page);
  expect(confirmations).toHaveLength(1);
  expect(confirmations[0]).toMatchObject({
    args: { catalogRevision: null, languageBcp47: "en-US" },
    command: "confirm_primary_language",
  });

  await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);
});

test("Transcribe and Help describe the organization server queue", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Transcribe", exact: true }).click();

  await expect(page.getByText("Add recordings to your organization's transcription queue."))
    .toBeVisible();
  // The preview has no language configured, which is exactly a first run: the
  // hero yields to the two-step welcome, and the queue badge belongs to the
  // post-setup import surface it describes.
  await expect(page.getByTestId("first-run-welcome")).toBeVisible();
  await expect(page.getByText("Two steps to your first dictation")).toBeVisible();
  await expect(page.getByText("Private on this device", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Drop files to run", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Choose files above to add them to the organization server queue.", { exact: true }))
    .toBeVisible();

  await page.locator('[data-sidebar="menu-button"]').filter({ hasText: /^Help$/ }).click();
  await expect(page.getByRole("dialog", { name: "Help" })).toContainText("Choose files");
  await expect(page.getByRole("dialog", { name: "Help" })).toContainText("organization server queue");
});
