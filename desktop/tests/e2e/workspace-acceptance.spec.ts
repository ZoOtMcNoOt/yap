import { expect, test, type Locator, type Page } from "@playwright/test";
import { installWorkspaceAcceptanceBridge } from "./workspace-acceptance-bridge";
import { journeyTranscript } from "./recording-journey-bridge";

async function calls(page: Page) {
  return page.evaluate(() => (globalThis as unknown as {
    __workspaceAcceptance: { calls: Array<{ command: string; args: unknown }> };
  }).__workspaceAcceptance.calls);
}

async function inWindow(locator: Locator, width: number, height: number) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(height + 1);
}

for (const viewport of [{ width: 1122, height: 740 }, { width: 1440, height: 900 }, { width: 720, height: 520 }]) {
  test(`workspaces and recovery dialogs fit ${viewport.width}×${viewport.height} with reduced motion`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installWorkspaceAcceptanceBridge(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    await page.getByRole("button", { name: "Review recording restored.mp3" }).click();
    const review = page.getByRole("dialog", { name: "restored.mp3", exact: true });
    await expect(review.locator("pre")).toHaveText(journeyTranscript);
    await inWindow(review.getByRole("button", { name: "Review corrections", exact: true }), viewport.width, viewport.height);
    await review.getByRole("button", { name: "Review corrections", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Transcript correction", exact: true }).first()).toBeVisible();
    // The sidebar becomes a drawer below the desktop breakpoint.
    async function navigate(name: string) {
      const button = page.getByRole("button", { name, exact: true }).first();
      if (!await button.isVisible()) await page.getByRole("button", { name: "Toggle sidebar" }).click();
      await button.click();
      if (await page.getByRole("dialog", { name: "Sidebar", exact: true }).isVisible()) await page.keyboard.press("Escape");
    }
    await navigate("Transcribe");
    await expect(page.getByRole("heading", { name: "Transcribe", exact: true })).toBeVisible();
    await navigate("Knowledge");
    await inWindow(page.getByRole("tab", { name: "Review conflicts" }), viewport.width, viewport.height);
    await page.getByRole("tab", { name: "Search sources" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Ask a question" })).toBeFocused();
    await navigate("Settings");
    const settings = page.getByRole("dialog", { name: "Settings", exact: true });
    await expect(settings).toBeVisible();
    await settings.getByRole("button", { name: "System", exact: true }).click();
    await settings.getByRole("button", { name: "Organization server", exact: true }).click();
    await settings.getByRole("textbox", { name: "Server URL" }).scrollIntoViewIfNeeded();
    await inWindow(settings.getByRole("textbox", { name: "Server URL" }), viewport.width, viewport.height);
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);
    await page.keyboard.press("Escape");
    await navigate("Help");
    const help = page.getByRole("dialog", { name: "Help", exact: true });
    const question = help.locator("summary").filter({ hasText: "Will correction change my original?" });
    await question.focus();
    await page.keyboard.press("Enter");
    await expect(help.getByText("Your original transcript stays unchanged.", { exact: false })).toBeVisible();
    await inWindow(help.locator('[data-slot="sheet-footer"]').getByRole("button", { name: "Close", exact: true }), viewport.width, viewport.height);
    await help.locator('[data-slot="sheet-footer"]').getByRole("button", { name: "Close", exact: true }).click();
    await expect(help).toHaveCount(0);
  });
}

test("history loading, failure and retry preserve saved entries", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page, { historyBlocked: true });
  await page.goto("/");
  await expect(page.getByText("Loading transcript history…", { exact: true })).toBeVisible();
  await expect(page.getByText("No recordings yet", { exact: true })).toHaveCount(0);
  await page.evaluate(() => {
    const fixture = (globalThis as unknown as { __workspaceAcceptance: { setHistoryFails: (fails: boolean) => void; releaseHistory: () => void } }).__workspaceAcceptance;
    fixture.setHistoryFails(true);
    fixture.releaseHistory();
  });
  await expect(page.getByRole("alert")).toContainText("Your saved files are unchanged.");
  await page.evaluate(() => (globalThis as unknown as { __workspaceAcceptance: { setHistoryFails: (fails: boolean) => void } }).__workspaceAcceptance.setHistoryFails(false));
  await page.getByRole("button", { name: "Retry history" }).click();
  await expect(page.getByRole("button", { name: "Review recording restored.mp3" })).toBeVisible();
  await page.evaluate(() => {
    (globalThis as unknown as { __workspaceAcceptance: { setHistoryFails: (fails: boolean) => void } }).__workspaceAcceptance.setHistoryFails(true);
    (globalThis as unknown as { __recordingJourney: { setState: (state: string) => void } }).__recordingJourney.setState("complete");
  });
  await expect(page.getByRole("button", { name: "Retry history" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review recording restored.mp3" })).toBeVisible();
});

for (const serverState of ["offline", "disabled", "sign_in_required", "access_denied", "ready"] as const) {
  test(`${serverState} and denied capabilities preserve local reading and setup without sign-in or rerouting`, async ({ page }) => {
    await installWorkspaceAcceptanceBridge(page, { serverState });
    await page.goto("/");
    await page.getByRole("button", { name: "Review recording restored.mp3" }).click();
    await expect(page.getByRole("dialog", { name: "restored.mp3", exact: true }).locator("pre")).toHaveText(journeyTranscript);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Correct", exact: true }).click();
    await expect(page.getByRole("button", { name: "Correct transcript", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("textbox", { name: "What reviewed information are you looking for?" }).fill("launch");
    await expect(page.getByRole("button", { name: "Search knowledge", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Check server settings", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "Settings", exact: true });
    await settings.getByRole("button", { name: "System", exact: true }).click();
    await expect(settings.getByText("On-device dictation", { exact: true })).toBeVisible();
    await expect(settings.getByRole("button", { name: "Verify", exact: true })).toBeEnabled();
    const commands = (await calls(page)).map((entry) => entry.command);
    expect(commands).not.toContain("sign_in_to_server");
    expect(commands).not.toContain("set_server_settings");
    expect(commands).not.toContain("recording_jobs_pick_imports");
  });
}

test("server settings load/save/check failures have explicit retries and retain the typed URL", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page, { settingsFailOnce: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings", exact: true });
  await settings.getByRole("button", { name: "System", exact: true }).click();
  await settings.getByRole("button", { name: "Organization server", exact: true }).click();
  await expect(settings.getByRole("alert")).toContainText("Server settings could not be read.");
  await expect(settings.getByRole("textbox", { name: "Server URL" })).toHaveCount(0);
  await page.evaluate(() => (globalThis as unknown as { __workspaceAcceptance: { allowSettingsLoad: () => void } }).__workspaceAcceptance.allowSettingsLoad());
  await settings.getByRole("button", { name: "Retry server settings" }).click();
  const url = settings.getByRole("textbox", { name: "Server URL" });
  await url.fill("https://reviewed-server.example");
  await settings.getByRole("button", { name: "Save", exact: true }).click();
  await expect(settings.getByRole("alert")).toHaveText("Server settings could not be saved.");
  await expect(url).toHaveValue("https://reviewed-server.example");
  await settings.getByRole("button", { name: "Save", exact: true }).click();
  await expect(settings.getByText("Saved.", { exact: true })).toBeVisible();
  await settings.getByRole("button", { name: "Test Connection", exact: true }).click();
  await expect(settings.getByRole("alert")).toHaveText("Connection check failed. Try again.");
  await expect(url).toHaveValue("https://reviewed-server.example");
  await settings.getByRole("button", { name: "Test Connection", exact: true }).click();
  await expect(settings.getByText("Connection ready.", { exact: true })).toBeVisible();
});

test("bounded preview failure can be retried without changing the saved transcript", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page);
  await page.goto("/");
  await page.evaluate(() => (globalThis as unknown as { __recordingJourney: { setReadFails: (fails: boolean) => void } }).__recordingJourney.setReadFails(true));
  await page.getByRole("button", { name: "Actions for restored.mp3" }).click();
  await page.getByRole("menuitem", { name: "Preview", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "restored.mp3", exact: true });
  await expect(preview.getByRole("alert")).toContainText("This preview could not be read.");
  await page.evaluate(() => (globalThis as unknown as { __recordingJourney: { setReadFails: (fails: boolean) => void } }).__recordingJourney.setReadFails(false));
  await preview.getByRole("button", { name: "Retry preview" }).click();
  await expect(preview.locator("pre")).toHaveText(journeyTranscript);
  expect((await calls(page)).filter((entry) => entry.command === "recording_job_retry")).toHaveLength(0);
});

test("a native workspace action dismisses review and retains its correction source", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Review recording restored.mp3" }).click();
  await page.evaluate(() => (globalThis as unknown as { __recordingJourney: { openWorkspace: (action: string) => void } }).__recordingJourney.openWorkspace("knowledge"));
  await expect(page.getByRole("heading", { name: "Knowledge", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await expect(page.getByText("restored.mp3", { exact: true }).first()).toBeVisible();
});

test("partial recovery failures retain the artifact and retry the native identity", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page, { maintenance: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Actions for live-partial-1" }).click();
  await page.getByRole("menuitem", { name: "Recover", exact: true }).click();
  await expect(page.getByText("Error: Recovery interrupted. Try again.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Actions for live-partial-1" }).click();
  await page.getByRole("menuitem", { name: "Recover", exact: true }).click();
  await expect(page.getByText("Partial recording recovered", { exact: true })).toBeVisible();
  const attempts = (await calls(page)).filter((entry) => entry.command === "recover_live_session");
  expect(attempts).toHaveLength(2);
  expect(attempts[0].args).toEqual({ sessionId: "partial-1", expectedArtifactPath: "C:\\Yap\\live-recordings\\live-partial-1.wav.part" });
  expect(attempts[1].args).toEqual(attempts[0].args);
});

for (const name of ["live-partial-1", "live-saved-1"]) {
  test(`deleting ${name} requires confirmation and retains the row after native refusal`, async ({ page }) => {
    await installWorkspaceAcceptanceBridge(page, { maintenance: true });
    await page.goto("/");
    async function askDelete() {
      await page.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
    }
    await askDelete();
    await page.getByRole("alertdialog").getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: `Actions for ${name}` })).toBeFocused();
    expect((await calls(page)).filter((entry) => entry.command.startsWith("delete_"))).toHaveLength(0);
    await askDelete();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByText("Error: Native identity changed. Refresh and try again.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: `Actions for ${name}` })).toBeVisible();
    await askDelete();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByRole("button", { name: `Actions for ${name}` })).toHaveCount(0);
  });
}

test("failed native hiding retains the row until an acknowledged retry", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page, { maintenance: true });
  await page.goto("/");
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.getByRole("button", { name: "Actions for live-partial-1" }).click();
    await page.getByRole("menuitem", { name: "Hide", exact: true }).click();
    if (attempt === 0) await expect(page.getByRole("button", { name: "Actions for live-partial-1" })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Actions for live-partial-1" })).toHaveCount(0);
  expect((await calls(page)).filter((entry) => entry.command === "history_hide_native")).toHaveLength(2);
});

test("keyboard review/navigation and modal focus remain usable through repeated tabbing", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Review recording restored.mp3" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "restored.mp3", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Review recording restored.mp3" })).toBeFocused();
  await page.getByRole("button", { name: "Correct", exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Choose a transcript", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Welcome back", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).focus();
  await page.keyboard.press("Enter");
  for (const key of ["Tab", "Shift+Tab"]) {
    for (let index = 0; index < 18; index++) {
      await page.keyboard.press(key);
      expect(await page.evaluate(() => document.activeElement?.closest('[role="dialog"]')?.getAttribute("aria-labelledby"))).toBeTruthy();
    }
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toBeFocused();
});

test("local model install failure/retry/cancel and ready projection stay independent of server access", async ({ page }) => {
  await installWorkspaceAcceptanceBridge(page, { serverState: "access_denied", modelLifecycle: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings", exact: true });
  await settings.getByRole("button", { name: "Install", exact: true }).click();
  await expect(settings.getByText(/Downloading.*20/)).toBeVisible();
  await expect(settings.getByRole("button", { name: "Cancel", exact: true })).toBeEnabled();
  await page.evaluate(() => (globalThis as unknown as { __workspaceAcceptance: { failModelInstall: () => void } }).__workspaceAcceptance.failModelInstall());
  await settings.getByRole("button", { name: "Retry", exact: true }).click();
  await settings.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(settings.getByRole("button", { name: "Install", exact: true })).toBeEnabled();
  await settings.getByRole("button", { name: "Install", exact: true }).click();
  await expect(settings.getByRole("button", { name: "Verify", exact: true })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Local ready", exact: true })).toBeVisible();
  expect((await calls(page)).filter((entry) => entry.command === "fallback_model_install")).toHaveLength(3);
  expect((await calls(page)).some((entry) => entry.command === "sign_in_to_server")).toBe(false);
});
