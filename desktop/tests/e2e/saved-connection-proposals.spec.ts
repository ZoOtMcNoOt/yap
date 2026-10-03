import { expect, test, type Page } from "@playwright/test";
import { installProposalInspectionBridge, proposalReference } from "./connection-proposal-bridge";

const otherReference = "f".repeat(64);
const list = (page: Page) => page.getByRole("list", { name: "Pending connection proposals" });
const row = (page: Page, reference = proposalReference) => page.getByRole("button", { name: `Open saved proposal ${reference}`, exact: true });
const article = (page: Page) => page.getByRole("article", { name: "Saved connection proposal" });
async function enter(page: Page) {
  await installProposalInspectionBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page.getByRole("tab", { name: "Review proposals", exact: true }).click();
}
async function control(page: Page, method: string, value?: unknown) {
  await page.evaluate(({ method, value }) => (globalThis as any).__proposalInspection[method](value), { method, value });
}
async function journey(page: Page, method: string, value: string | boolean) {
  await page.evaluate(({ method, value }) => (globalThis as any).__knowledgeJourney[method](value), { method, value });
}
async function calls(page: Page) {
  return page.evaluate(() => (globalThis as any).__proposalInspection.calls.filter((call: any) => call.command === "knowledge_connections"));
}
async function load(page: Page) {
  await page.getByRole("button", { name: "Load saved proposals", exact: true }).click();
  await expect(list(page)).toBeVisible();
}
async function discard(page: Page) {
  await page.getByRole("button", { name: /^(Discard proposal…|Try discard again…)$/ }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Discard proposal", exact: true }).click();
}
for (const width of [360, 720, 1440])
  test(`owned list opens exact evidence by keyboard without pasting at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await enter(page);
    await expect(page.getByLabel("Connection proposal reference")).toBeHidden();
    expect(await calls(page)).toHaveLength(0);
    await load(page);
    await expect(list(page).getByRole("button")).toHaveCount(2);
    await expect(list(page).locator("time").first()).toHaveAttribute("datetime", "2026-10-03T12:00:00.000000Z");
    await expect(article(page)).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath("saved-list.png") });
    await row(page).focus();
    await page.keyboard.press("Enter");
    await expect(article(page)).toBeVisible();
    await expect(article(page)).toBeFocused();
    await expect(article(page)).toBeInViewport();
    await expect(article(page).getByText("Launch review → Launch approval")).toBeVisible();
    await expect(row(page)).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({ path: test.info().outputPath("saved-selected.png") });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    expect((await calls(page)).map((call: any) => call.args.request)).toEqual([
      { action: "pending" }, { action: "proposal", proposalId: proposalReference },
    ]);
    await page.getByRole("button", { name: "Search current sources" }).click();
    await expect(page.getByRole("tab", { name: "Search sources", exact: true })).toHaveAttribute("data-state", "active");
  });

test("empty and failed lists offer explicit recovery without automatic requests", async ({ page }) => {
  await enter(page);
  await control(page, "mode", "unavailable");
  await page.getByRole("button", { name: "Load saved proposals", exact: true }).click();
  await expect(page.getByText(/Saved proposals could not be loaded/)).toBeVisible();
  await expect(page.getByText(/No pending connection proposals/)).toHaveCount(0);
  await expect(list(page)).toHaveCount(0);
  await control(page, "mode", "success");
  await control(page, "saved", []);
  await page.getByRole("button", { name: "Load saved proposals", exact: true }).click();
  await expect(page.getByText(/No pending connection proposals/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh saved proposals" })).toBeEnabled();
  await page.locator("summary").filter({ hasText: "Open a proposal reference" }).click();
  await page.getByLabel("Connection proposal reference").fill(proposalReference);
  await page.getByRole("button", { name: "Open connection proposal", exact: true }).click();
  await expect(article(page)).toBeVisible();
  expect((await calls(page)).map((call: any) => call.args.request.action)).toEqual(["pending", "pending", "proposal"]);
});

test("corrupt metadata refuses the entire list and leaves local navigation available", async ({ page }) => {
  await enter(page);
  await control(page, "saved", [
    { proposalId: proposalReference, createdAtUtc: "2026-10-03T12:00:00Z" },
    { proposalId: "bad-reference", createdAtUtc: "2026-10-03T11:00:00Z" },
  ]);
  await page.getByRole("button", { name: "Load saved proposals", exact: true }).click();
  await expect(page.getByText(/inconsistent proposal list/)).toBeVisible();
  await expect(list(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Search current sources" }).click();
  await expect(page.getByRole("tab", { name: "Search sources", exact: true })).toHaveAttribute("data-state", "active");
});

test("only confirmed discard removes a row; lost receipt keeps the same-ref retry", async ({ page }) => {
  await enter(page);
  await load(page);
  await row(page).click();
  await expect(article(page)).toBeVisible();
  await control(page, "mode", "lostDiscardReceipt");
  await discard(page);
  await expect(page.getByText(/It may already have completed/)).toBeVisible();
  await expect(row(page)).toBeVisible();
  await expect(row(page, otherReference)).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh saved proposals" })).toBeDisabled();
  await page.locator("summary").filter({ hasText: "Open a proposal reference" }).click();
  await expect(page.getByLabel("Connection proposal reference")).toBeDisabled();
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(proposalReference);
  await discard(page);
  await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
  await expect(row(page)).toHaveCount(0);
  await expect(row(page, otherReference)).toBeEnabled();
  await row(page, otherReference).click();
  await expect(article(page)).toBeVisible();
  expect((await calls(page)).filter((call: any) => call.args.request.action === "discard")
    .map((call: any) => call.args.request.proposalId)).toEqual([proposalReference, proposalReference]);
});

test("account changes hide owned metadata and ignore delayed list receipts", async ({ page }) => {
  await enter(page);
  await load(page);
  await row(page).click();
  await expect(article(page)).toBeVisible();
  await control(page, "delay");
  await page.getByRole("button", { name: "Refresh saved proposals" }).click();
  await journey(page, "recheckConnection", "2");
  await control(page, "release");
  await expect(list(page)).toHaveCount(0);
  await expect(article(page)).toHaveCount(0);
  await page.locator("summary").filter({ hasText: "Open a proposal reference" }).click();
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Load saved proposals", exact: true })).toBeEnabled();
  await load(page);
  expect((await calls(page)).at(-1).args.authorityRevision).toBe("2");
});

test("cancelled list waits for native read completion before admitting another request", async ({ page }) => {
  await enter(page);
  await control(page, "delay");
  await page.getByRole("button", { name: "Load saved proposals", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText(/Saved proposal loading cancelled/)).toBeVisible();
  expect(await calls(page)).toHaveLength(1);
  await expect(page.getByRole("button", { name: "Load saved proposals", exact: true })).toHaveCount(0);
  await control(page, "release");
  await expect(list(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Load saved proposals", exact: true })).toBeEnabled();
  await load(page);
  expect(await calls(page)).toHaveLength(2);
});

test("offline transition hides metadata and preserves an uncertain discard reference", async ({ page }) => {
  await enter(page);
  await load(page);
  await row(page, otherReference).click();
  await expect(article(page)).toBeVisible();
  await control(page, "delay");
  await control(page, "mode", "lostDiscardReceipt");
  await discard(page);
  await journey(page, "setAvailable", false);
  await expect(list(page)).toHaveCount(0);
  await expect(article(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Load saved proposals", exact: true })).toBeDisabled();
  await control(page, "release");
  await journey(page, "setAvailable", true);
  await page.locator("summary").filter({ hasText: "Open a proposal reference" }).click();
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(otherReference);
  await expect(page.getByRole("button", { name: "Load saved proposals", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Try discard again…", exact: true })).toBeEnabled();
  await discard(page);
  await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
  await load(page);
  await expect(row(page, otherReference)).toHaveCount(0);
  await expect(row(page)).toBeEnabled();
});

test("owned stale metadata can be cleaned up when source inspection is denied", async ({ page }) => {
  await enter(page);
  await load(page);
  await control(page, "mode", "denied");
  await row(page).click();
  await expect(page.getByText(/has not granted access to this proposal/)).toBeVisible();
  await expect(article(page)).toHaveCount(0);
  await expect(row(page)).toBeVisible();
  await control(page, "mode", "success");
  await discard(page);
  await expect(row(page)).toHaveCount(0);
  await expect(row(page, otherReference)).toBeVisible();
});


test("row inspection exposes cancellation while manual reference remains collapsed", async ({ page }) => {
  await enter(page);
  await load(page);
  await control(page, "delay");
  await row(page).click();
  await expect(page.getByLabel("Connection proposal reference")).toBeHidden();
  await expect(page.getByText("Reading saved proposal…", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText(/Proposal inspection cancelled/)).toBeVisible();
  await expect(row(page)).toBeDisabled();
  await control(page, "release");
  await expect(article(page)).toHaveCount(0);
  await expect(row(page)).toBeEnabled();
  await row(page).click();
  await expect(article(page)).toBeVisible();
});


test("a completed inspection does not move focus from another task", async ({ page }) => {
  await enter(page);
  await load(page);
  await control(page, "delay");
  await row(page).click();
  const searchTab = page.getByRole("tab", { name: "Search sources", exact: true });
  await searchTab.click();
  await expect(searchTab).toBeFocused();
  await control(page, "release");
  await expect(page.getByRole("button", { name: "Refresh saved proposals", includeHidden: true })).toBeEnabled();
  await expect(searchTab).toBeFocused();
  await expect(searchTab).toHaveAttribute("data-state", "active");
  await page.getByRole("tab", { name: "Review proposals", exact: true }).click();
  await expect(article(page)).toBeVisible();
});
