import { expect, test } from "@playwright/test";
import { installQueuedServerBridge, languageCalls, serverCalls } from "./app-server-bridge";

async function expectNoImplicitSetup(page: import("@playwright/test").Page) {
  const calls = await page.evaluate(() => (globalThis as unknown as {
    __queuedServerBoundaryTest: { calls: string[] };
  }).__queuedServerBoundaryTest.calls);
  expect(calls).not.toContain("fallback_model_install");
  expect(await serverCalls(page)).toEqual([]);
}

test("missing model first run has one modal and a usable route to the queue", async ({ page }) => {
  await page.setViewportSize({ width: 1122, height: 740 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installQueuedServerBridge(page, "not_set", {
    primaryLanguageUnconfirmed: true,
    localModelStatus: "missing",
    serverRefreshNeverSettles: true,
  });
  await page.goto("/");
  const welcome = page.getByTestId("first-run-welcome");
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(welcome).toContainText("No model is downloaded and no server is connected by this step.");
  await welcome.getByRole("button", { name: "Confirm language" }).click();
  await expect(welcome).toContainText("Local fallback model missing");
  await expect(welcome).toContainText("Install or repair the local model in Settings");
  await welcome.getByRole("button", { name: "Open Transcribe" }).click();
  await expect(welcome).toHaveCount(0);
  await expect(page.getByText("Drop recordings here")).toBeVisible();
  await expect(page.getByText("Waiting in queue", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);
  await expectNoImplicitSetup(page);
});

test("skip does not confirm a language and offline Settings can complete it later", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true, localModelStatus: "missing" });
  await page.goto("/");
  await page.getByTestId("first-run-welcome").getByRole("button", { name: "Skip for now" }).click();
  expect(await languageCalls(page)).toEqual([]);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("button", { name: "General", exact: true }).click();
  await expect(settings.getByRole("combobox", { name: "Primary language" })).toContainText("English");
  await settings.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(settings).toContainText("Per-recording choices never rewrite it.");
  expect(await languageCalls(page)).toEqual([{
    command: "confirm_primary_language", args: { catalogRevision: null, languageBcp47: "en-US" },
  }]);
  await expectNoImplicitSetup(page);
});

test("failed confirmation stays on the chosen language and can be retried", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true, primaryLanguageConfirmFailsOnce: true });
  await page.goto("/");
  const welcome = page.getByTestId("first-run-welcome");
  await welcome.getByRole("button", { name: "Confirm language" }).click();
  await expect(welcome.getByRole("alert")).toContainText("Language could not be saved. Try again.");
  await expect(page.getByTestId("first-run-language")).toContainText("English");
  await expect(welcome.getByRole("heading", { name: "Choose how to transcribe" })).toHaveCount(0);
  await welcome.getByRole("button", { name: "Confirm language" }).click();
  await expect(welcome.getByRole("heading", { name: "Choose how to transcribe" })).toBeVisible();
  expect(await languageCalls(page)).toHaveLength(2);
});

test("setup check failure is recoverable without trapping local navigation", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true, primaryLanguageCheckFails: true });
  await page.goto("/");
  const welcome = page.getByTestId("first-run-welcome");
  await expect(welcome.getByRole("alert")).toContainText("Language settings could not be read.");
  await page.evaluate(() => (globalThis as unknown as {
    __queuedServerBoundaryTest: { setLanguageCheckFails: (fails: boolean) => void };
  }).__queuedServerBoundaryTest.setLanguageCheckFails(false));
  await welcome.getByRole("button", { name: "Retry setup check" }).click();
  await expect(welcome.getByRole("button", { name: "Confirm language" })).toBeEnabled();
  await expect(welcome.getByRole("alert")).toHaveCount(0);
});

test("unsupported locale suggestion requires an explicit supported choice", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true, suggestedLanguage: "xx-XX" });
  await page.goto("/");
  const welcome = page.getByTestId("first-run-welcome");
  await expect(welcome.getByRole("button", { name: "Confirm language" })).toBeDisabled();
  await welcome.getByRole("combobox", { name: "Primary language" }).click();
  await page.getByRole("option", { name: /French/ }).click();
  await welcome.getByRole("button", { name: "Confirm language" }).click();
  await expect(welcome).toContainText("French");
  expect((await languageCalls(page))[0]).toMatchObject({ args: { languageBcp47: "fr-FR" } });
});

test("welcome traps keyboard focus and Escape skips without changing preferences", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { primaryLanguageUnconfirmed: true, localModelStatus: "missing" });
  await page.goto("/");
  const welcome = page.getByTestId("first-run-welcome");
  await expect(welcome.getByRole("heading", { name: "Welcome to Yap" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(welcome.getByRole("combobox", { name: "Primary language" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(welcome.getByRole("button", { name: "Skip for now" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Help", exact: true }).first().click();
  await expect(page.getByRole("dialog", { name: "Help" })).toBeVisible();
  expect(await languageCalls(page)).toEqual([]);
});

test("a local-only preference remains selectable beside a server catalog without granting a server route", async ({ page }) => {
  await installQueuedServerBridge(page, "offline");
  await page.goto("/");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("combobox", { name: "Primary language" }).click();
  await page.getByRole("option", { name: /German.*On-device dictation/ }).click();
  await settings.getByRole("button", { name: "Save", exact: true }).click();
  await expect(settings).toContainText("Available for local dictation.");
  expect((await languageCalls(page))[0]).toMatchObject({
    args: { catalogRevision: null, languageBcp47: "de-DE" },
  });
  await expectNoImplicitSetup(page);
});
