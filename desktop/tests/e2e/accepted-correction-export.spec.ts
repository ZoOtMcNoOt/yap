import { expect, test, type Page } from "@playwright/test";
import {
  correctedPlanningText,
  installCorrectionJourneyBridge,
  originalPlanningText,
} from "./correction-journey-bridge";

async function installExportBridge(page: Page, preaccepted = true) {
  await installCorrectionJourneyBridge(page, { preaccepted, available: false });
  await page.addInitScript(() => {
    const host = globalThis as unknown as {
      __TAURI_INTERNALS__: {
        invoke: (command: string, args?: unknown) => Promise<unknown>;
      };
    };
    const base = host.__TAURI_INTERNALS__.invoke;
    const fixture = {
      mode: "saved",
      advanced: false,
      calls: [] as Array<{ command: string; args: unknown }>,
      finish: undefined as (() => void) | undefined,
    };
    Object.assign(globalThis, { __acceptedExport: fixture });
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "read_accepted_transcript_correction") {
        const result = (await base(command, args)) as {
          acceptedRevision: Record<string, unknown> | null;
        };
        return fixture.advanced && result.acceptedRevision
          ? {
              ...result,
              revisionCount: 2,
              acceptedRevision: {
                ...result.acceptedRevision,
                revision: 2,
                correctedSha256: "e".repeat(64),
              },
            }
          : result;
      }
      if (
        command !== "export_accepted_transcript_correction" &&
        command !== "export_transcript"
      )
        return base(command, args);
      fixture.calls.push({ command, args });
      if (command === "export_transcript")
        return { status: "saved", path: "C:/Exports/original.txt" };
      const request = args as { revision: number; correctedSha256: string };
      if (fixture.mode === "pending")
        await new Promise<void>((resolve) => {
          fixture.finish = resolve;
        });
      if (fixture.mode === "failed")
        throw "That file already exists. Choose a new filename; existing files are preserved.";
      if (fixture.mode === "cancelled") return { status: "cancelled" };
      if (request.revision !== (fixture.advanced ? 2 : 1))
        throw "The saved correction changed. Refresh its history and retry.";
      return {
        status: "saved",
        path: `C:/Exports/transcript-corrected-r${request.revision}.txt`,
        revision: fixture.mode === "misbound" ? 3 : request.revision,
        correctedSha256: request.correctedSha256,
      };
    };
  });
}

async function change(page: Page, mode: string, advanced = false) {
  await page.evaluate(
    ({ mode, advanced }) => {
      const fixture = (
        globalThis as unknown as {
          __acceptedExport: { mode: string; advanced: boolean };
        }
      ).__acceptedExport;
      fixture.mode = mode;
      fixture.advanced = advanced;
    },
    { mode, advanced },
  );
}

async function openPlanning(page: Page) {
  await page
    .getByRole("button", { name: "Review recording planning.mp3", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Review corrections", exact: true })
    .click();
}

async function calls(page: Page) {
  return page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __acceptedExport: {
            calls: Array<{ command: string; args: unknown }>;
          };
        }
      ).__acceptedExport.calls,
  );
}

for (const width of [360, 1440]) {
  test(`saved correction exports offline with exact native preconditions at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await installExportBridge(page);
    await page.goto("/");
    await openPlanning(page);
    const button = page.getByRole("button", {
      name: "Export saved correction",
      exact: true,
    });
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Saved correction revision 1 exported", { exact: true }),
    ).toBeVisible();
    await expect(button).toBeFocused();
    expect(await calls(page)).toEqual([
      {
        command: "export_accepted_transcript_correction",
        args: {
          outputPath: "C:\\Yap\\remote-jobs\\planning\\transcript.txt",
          revision: 1,
          correctedSha256: "d".repeat(64),
        },
      },
    ]);
    await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
    await expect(page.locator("pre").nth(1)).toHaveText(correctedPlanningText);
    expect(
      await page
        .getByRole("group", { name: "Saved correction actions", exact: true })
        .evaluate((node) => node.scrollWidth <= node.clientWidth),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("cancelling corrected export retains keyboard focus and makes no saved claim", async ({
  page,
}) => {
  await installExportBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await change(page, "cancelled");
  const button = page.getByRole("button", {
    name: "Export saved correction",
    exact: true,
  });
  await button.click();
  await expect(
    page.getByText("Saved correction export cancelled", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Saved correction revision 1 exported", { exact: true }),
  ).toHaveCount(0);
  await expect(button).toBeFocused();
  await expect(button).not.toHaveAttribute("aria-disabled", "true");
  await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
});

test("failed accepted export preserves review and permits explicit retry", async ({
  page,
}) => {
  await installExportBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await change(page, "failed");
  const button = page.getByRole("button", {
    name: "Export saved correction",
    exact: true,
  });
  await button.click();
  const error = page
    .getByRole("alert")
    .filter({ hasText: "That file already exists" });
  await expect(error).toBeVisible();
  await expect(
    page.getByText("Saved correction revision 1 exported", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("pre").nth(1)).toHaveText(correctedPlanningText);
  await change(page, "saved");
  await button.click();
  await expect(error).toHaveCount(0);
  await expect(
    page.getByText("Saved correction revision 1 exported", { exact: true }),
  ).toBeVisible();
  expect(await calls(page)).toHaveLength(2);
});

test("a newer accepted revision requires refresh before exporting the new snapshot", async ({
  page,
}) => {
  await installExportBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await change(page, "saved", true);
  const button = page.getByRole("button", {
    name: "Export saved correction",
    exact: true,
  });
  await button.click();
  await expect(
    page.getByRole("alert").filter({ hasText: "saved correction changed" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Refresh saved corrections", exact: true })
    .click();
  await expect(
    page.getByText("Saved accepted revision 2", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "saved correction changed" }),
  ).toHaveCount(0);
  await button.click();
  await expect(
    page.getByText("Saved correction revision 2 exported", { exact: true }),
  ).toBeVisible();
  expect((await calls(page)).at(-1)?.args).toEqual({
    outputPath: "C:\\Yap\\remote-jobs\\planning\\transcript.txt",
    revision: 2,
    correctedSha256: "e".repeat(64),
  });
});

test("pending corrected export survives navigation and blocks original exports until acknowledgement", async ({
  page,
}) => {
  await installExportBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await change(page, "pending");
  const button = page.getByRole("button", {
    name: "Export saved correction",
    exact: true,
  });
  await button.click();
  await expect(button).toHaveAttribute("aria-disabled", "true");
  await page
    .getByRole("button", { name: "Choose a transcript", exact: true })
    .click();
  await openPlanning(page);
  await expect(button).toHaveAttribute("aria-disabled", "true");
  const originalExport = page.getByRole("button", {
    name: "Export original transcript for planning.mp3",
    exact: true,
  });
  await expect(originalExport).toHaveAttribute("aria-disabled", "true");
  await button.focus();
  await page.keyboard.press("Enter");
  expect(await calls(page)).toHaveLength(1);
  await change(page, "failed");
  await page.evaluate(() =>
    (
      globalThis as unknown as { __acceptedExport: { finish: () => void } }
    ).__acceptedExport.finish(),
  );
  await expect(button).not.toHaveAttribute("aria-disabled", "true");
  await expect(
    page.getByRole("alert").filter({ hasText: "That file already exists" }),
  ).toHaveCount(0);
  await change(page, "saved");
  await button.click();
  await expect(
    page.getByText("Saved correction revision 1 exported", { exact: true }),
  ).toBeVisible();
  expect(await calls(page)).toHaveLength(2);
});

test("a misbound export receipt fails visibly without claiming the wrong revision", async ({
  page,
}) => {
  await installExportBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await change(page, "misbound");
  await page
    .getByRole("button", { name: "Export saved correction", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "receipt did not match" }),
  ).toBeVisible();
  await expect(
    page.getByText("Saved correction revision 1 exported", { exact: true }),
  ).toHaveCount(0);
});

test("an unsaved suggestion cannot use accepted-correction export", async ({
  page,
}) => {
  await installCorrectionJourneyBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await page
    .getByRole("button", { name: "Correct transcript", exact: true })
    .click();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __correctionJourney: { setStatus: (status: string) => void };
      }
    ).__correctionJourney.setStatus("complete"),
  );
  await expect(
    page.getByRole("button", { name: "Save revision", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Export saved correction", exact: true }),
  ).toHaveCount(0);
});
