import { expect, test, type Page } from "@playwright/test";
import { installCorrectionJourneyBridge, correctedPlanningText, originalPlanningText } from "./correction-journey-bridge";

const planningPath = "C:\\Yap\\remote-jobs\\planning\\transcript.txt";
const latestText = "The launch date is Friday. Review the timeline.";

async function installSelectionBridge(page: Page) {
  await installCorrectionJourneyBridge(page, { preaccepted: true, available: false });
  await page.addInitScript(({ planningPath, latestText }) => {
    const host = globalThis as unknown as { __TAURI_INTERNALS__: { invoke: (command: string, args?: unknown) => Promise<unknown> } };
    const base = host.__TAURI_INTERNALS__.invoke;
    const state = {
      calls: [] as Array<{ command: string; args: unknown }>,
      readMode: "saved", delayRevision: 0,
      finishRead: undefined as (() => void) | undefined,
      exportPending: false, finishExport: undefined as (() => void) | undefined,
    };
    Object.assign(globalThis, { __acceptedSelection: state });
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "read_accepted_transcript_correction") {
        const request = args as { outputPath: string; revision: number | null };
        state.calls.push({ command, args });
        const result = await base(command, args) as { acceptedRevision: Record<string, unknown> | null };
        if (request.outputPath !== planningPath) return result;
        const selected = request.revision ?? 2;
        if (state.readMode === "failed") throw "Saved correction history is damaged. No files were changed.";
        const number = state.readMode === "misbound" ? 2 : selected;
        const loaded = {
          ...result, revisionCount: 2,
          acceptedRevision: { ...result.acceptedRevision,
            revision: number, requestId: `accepted-${number}`,
            correctedSha256: (number === 1 ? "d" : "e").repeat(64),
            correctedText: number === 1 ? result.acceptedRevision?.correctedText : latestText,
            revisionPath: `C:/saved/correction-${number}.json`,
          },
        };
        if (state.delayRevision === selected) {
          state.delayRevision = 0;
          await new Promise<void>(resolve => { state.finishRead = resolve; });
        }
        return loaded;
      }
      if (command === "export_accepted_transcript_correction") {
        state.calls.push({ command, args });
        const request = args as { revision: number; correctedSha256: string };
        if (state.exportPending) await new Promise<void>(resolve => { state.finishExport = resolve; });
        return { status: "saved", path: `C:/Exports/revision-${request.revision}.txt`, revision: request.revision, correctedSha256: request.correctedSha256 };
      }
      return base(command, args);
    };
  }, { planningPath, latestText });
}

async function openPlanning(page: Page) {
  await page.getByRole("button", { name: "Review recording planning.mp3", exact: true }).click();
  await page.getByRole("button", { name: "Review corrections", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Accepted revision", exact: true })).toHaveValue("2");
  await expect(page.locator("pre").nth(1)).toHaveText(latestText);
}

async function setState(page: Page, values: Record<string, unknown>) {
  await page.evaluate(values => Object.assign((globalThis as unknown as { __acceptedSelection: object }).__acceptedSelection, values), values);
}
async function calls(page: Page) {
  return page.evaluate(() => (globalThis as unknown as { __acceptedSelection: { calls: Array<{command: string; args: unknown}> } }).__acceptedSelection.calls);
}
const selector = (page: Page) => page.getByRole("combobox", { name: "Accepted revision", exact: true });

for (const width of [360, 720, 1440]) {
  test(`earlier accepted revision reads copies and exports offline at ${width}px`, async ({ context, page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await installSelectionBridge(page);
    await page.goto("/");
    await openPlanning(page);
    await selector(page).focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.locator("pre").nth(1)).toHaveText(correctedPlanningText);
    await expect(selector(page)).toBeFocused();
    await page.getByRole("button", { name: "Copy saved correction", exact: true }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(correctedPlanningText);
    const exportButton = page.getByRole("button", { name: "Export saved correction", exact: true });
    await exportButton.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Saved correction revision 1 exported", { exact: true })).toBeVisible();
    await expect(exportButton).toBeFocused();
    await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
    expect((await calls(page)).at(-1)).toEqual({ command: "export_accepted_transcript_correction", args: { outputPath: planningPath, revision: 1, correctedSha256: "d".repeat(64) } });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (process.env.YAP_CAPTURE_ACCEPTED_REVISION_EVIDENCE === "1") {
      await page.screenshot({ path: `../docs/evidence/accepted-correction-selection/2026-10-03/revision-${width}.png`, fullPage: true });
    }
    await selector(page).selectOption("2");
    await expect(page.locator("pre").nth(1)).toHaveText(latestText);
    expect((await calls(page)).at(-1)).toEqual({ command: "read_accepted_transcript_correction", args: { outputPath: planningPath, revision: null } });
    expect((await calls(page)).some(({command}) => /start_transcript|publish_transcript/.test(command))).toBe(false);
  });
}

test("a late earlier read cannot replace the latest selection", async ({ page }) => {
  await installSelectionBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await setState(page, { delayRevision: 1 });
  await selector(page).selectOption("1");
  await expect(page.getByText("Reading saved corrections…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export saved correction", exact: true })).toHaveCount(0);
  await selector(page).selectOption("2");
  await expect(page.locator("pre").nth(1)).toHaveText(latestText);
  await page.evaluate(() => (globalThis as unknown as { __acceptedSelection: { finishRead?: () => void } }).__acceptedSelection.finishRead?.());
  await expect(selector(page)).toHaveValue("2");
  await expect(page.locator("pre").nth(1)).toHaveText(latestText);
  await page.getByRole("button", { name: "Export saved correction", exact: true }).click();
  await expect(page.getByText("Saved correction revision 2 exported", { exact: true })).toBeVisible();
});

test("switching transcripts hides an earlier selection and ignores its late read", async ({ page }) => {
  await installSelectionBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await setState(page, { delayRevision: 1 });
  await selector(page).selectOption("1");
  await expect(page.getByText("Reading saved corrections…", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Choose a transcript", exact: true }).click();
  await page.getByRole("button", { name: "Review recording review.mp3", exact: true }).click();
  await page.getByRole("button", { name: "Review corrections", exact: true }).click();
  await expect(page.getByText("No accepted revision is saved for this transcript.", { exact: true })).toBeVisible();
  await page.evaluate(() => (globalThis as unknown as { __acceptedSelection: { finishRead?: () => void } }).__acceptedSelection.finishRead?.());
  await expect(selector(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Export saved correction", exact: true })).toHaveCount(0);
  await expect(page.locator("pre").first()).toHaveText("The review is complete.");
});

test("damaged history retains the original and retries the selected revision", async ({ page }) => {
  await installSelectionBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await setState(page, { readMode: "failed" });
  await selector(page).selectOption("1");
  await expect(page.getByRole("alert").filter({ hasText: "history is damaged" })).toBeVisible();
  await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
  await expect(page.getByRole("button", { name: "Copy saved correction", exact: true })).toHaveCount(0);
  await setState(page, { readMode: "saved" });
  await page.getByRole("button", { name: "Retry saved corrections", exact: true }).click();
  await expect(page.locator("pre").nth(1)).toHaveText(correctedPlanningText);
  await expect(selector(page)).toHaveValue("1");
});

test("a receipt for a different revision cannot expose or export substituted text", async ({ page }) => {
  await installSelectionBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await setState(page, { readMode: "misbound" });
  await selector(page).selectOption("1");
  await expect(page.getByRole("alert").filter({ hasText: "invalid accepted revision" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export saved correction", exact: true })).toHaveCount(0);
  await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
  expect((await calls(page)).some(({command}) => command === "export_accepted_transcript_correction")).toBe(false);
});

test("a native export retains its revision until completion", async ({ page }) => {
  await installSelectionBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await selector(page).selectOption("1");
  await expect(page.locator("pre").nth(1)).toHaveText(correctedPlanningText);
  await setState(page, { exportPending: true });
  await page.getByRole("button", { name: "Export saved correction", exact: true }).click();
  await expect(selector(page)).toBeDisabled();
  await expect(page.getByRole("button", { name: "Export saved correction", exact: true })).toHaveAttribute("aria-disabled", "true");
  await page.evaluate(() => (globalThis as unknown as { __acceptedSelection: { finishExport?: () => void } }).__acceptedSelection.finishExport?.());
  await expect(page.getByText("Saved correction revision 1 exported", { exact: true })).toBeVisible();
  await expect(selector(page)).toBeEnabled();
  await expect(selector(page)).toHaveValue("1");
});

test("selecting the same pending revision again keeps its owned read alive", async ({ page }) => {
  await installSelectionBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await setState(page, { delayRevision: 1 });
  await selector(page).selectOption("1");
  await expect(page.getByText("Reading saved corrections…", { exact: true })).toBeVisible();
  await selector(page).selectOption("1");
  await page.evaluate(() => (globalThis as unknown as { __acceptedSelection: { finishRead?: () => void } }).__acceptedSelection.finishRead?.());
  await expect(page.locator("pre").nth(1)).toHaveText(correctedPlanningText);
  await expect(page.getByText("Reading saved corrections…", { exact: true })).toHaveCount(0);
  expect((await calls(page)).filter(({ command, args }) => command === "read_accepted_transcript_correction" && (args as {revision: number}).revision === 1)).toHaveLength(1);
});
