import { expect, test, type Page } from "@playwright/test";
import { correctedPlanningText, installCorrectionJourneyBridge, originalPlanningText } from "./correction-journey-bridge";

async function setCorrectionStatus(page: Page, status: string) {
  await page.evaluate((next) => (globalThis as unknown as {
    __correctionJourney: { setStatus: (status: string) => void };
  }).__correctionJourney.setStatus(next), status);
}

test("closing review preserves the chosen older transcript for correction and manual revision acceptance", async ({ context, page }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await installCorrectionJourneyBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Review recording planning.mp3", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "planning.mp3", exact: true }).locator("pre")).toHaveText(originalPlanningText);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review transcript corrections", exact: true })).toBeVisible();
  await expect(page.getByText("planning.mp3", { exact: true }).first()).toBeVisible();
  await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
  await page.getByRole("button", { name: "Correct transcript", exact: true }).click();
  await expect(page.getByText("Waiting for the shared warm correction route…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save revision", exact: true })).toHaveCount(0);
  await setCorrectionStatus(page, "complete");
  await expect(page.locator("ins")).toHaveText("i");
  await expect(page.getByRole("button", { name: "Save revision", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(correctedPlanningText);
  await page.evaluate(() => (globalThis as unknown as { __correctionJourney: { failPublicationOnce: () => void } }).__correctionJourney.failPublicationOnce());
  await page.getByRole("button", { name: "Save revision", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("The revision could not be saved.");
  await page.getByRole("button", { name: "Save revision", exact: true }).click();
  await expect(page.getByText(/Saved immutable revision 1/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save revision", exact: true })).toBeDisabled();
  await expect(page.locator("pre").last()).toHaveText(originalPlanningText);

  const mutations = await page.evaluate(() => (globalThis as unknown as {
    __correctionJourney: { mutations: Array<{ command: string; args: unknown }> };
  }).__correctionJourney.mutations);
  expect(mutations.filter(({ command }) => command === "start_transcript_correction")).toEqual([
    { command: "start_transcript_correction", args: { outputPath: "C:\\Yap\\remote-jobs\\planning\\transcript.txt" } },
  ]);
  expect(mutations.filter(({ command }) => command === "publish_transcript_correction")).toEqual([
    { command: "publish_transcript_correction", args: { requestId: "correction-1" } },
    { command: "publish_transcript_correction", args: { requestId: "correction-1" } },
  ]);
});

test("review opens correction for its source, and changing sources cancels pending work", async ({ page }) => {
  await installCorrectionJourneyBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Review recording planning.mp3", exact: true }).click();
  await page.getByRole("button", { name: "Review corrections", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "planning.mp3", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Correct transcript", exact: true }).click();
  await setCorrectionStatus(page, "failed");
  await expect(page.getByRole("alert")).toContainText("The server could not safely correct this transcript.");
  await page.getByRole("button", { name: "Correct transcript", exact: true }).click();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Choose a transcript", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "planning.mp3", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Review recording review.mp3", exact: true }).click();
  await page.getByRole("button", { name: "Review corrections", exact: true }).click();
  await expect(page.locator("pre").first()).toHaveText("The review is complete.");
  const mutations = await page.evaluate(() => (globalThis as unknown as {
    __correctionJourney: { mutations: Array<{ command: string; args: unknown }> };
  }).__correctionJourney.mutations);
  expect(mutations).toContainEqual({ command: "cancel_transcript_correction", args: { requestId: "correction-2" } });
});
