import { expect, test, type Page } from "@playwright/test";
import {
  correctedPlanningText,
  installCorrectionJourneyBridge,
  originalPlanningText,
} from "./correction-journey-bridge";

const planningPath = "C:\\Yap\\remote-jobs\\planning\\transcript.txt";

test("accepting the same corrected text again refreshes the saved revision", async ({ page }) => {
  await installCorrectionJourneyBridge(page, { preaccepted: true, sameCorrectionHash: true });
  await page.goto("/");
  await openPlanning(page);
  await expect(page.getByText("Saved accepted revision 1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Correct transcript", exact: true }).click();
  await fixture(page, "setStatus", "complete");
  await page.getByRole("button", { name: "Save revision", exact: true }).click();
  await expect(page.getByText("Saved accepted revision 2", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Accepted revision", exact: true }).selectOption("1");
  await expect(page.getByText("Saved accepted revision 1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run again", exact: true }).click();
  await fixture(page, "setStatus", "complete");
  await page.getByRole("button", { name: "Save revision", exact: true }).click();
  await expect(page.getByText("Saved accepted revision 3", { exact: true })).toBeVisible();
});

async function fixture(page: Page, method: string, value: string | boolean) {
  await page.evaluate(
    ({ method, value }) =>
      (
        globalThis as unknown as {
          __correctionJourney: Record<
            string,
            (value: string | boolean) => void
          >;
        }
      ).__correctionJourney[method](value),
    { method, value },
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
          __correctionJourney: {
            mutations: Array<{ command: string; args: unknown }>;
          };
        }
      ).__correctionJourney.mutations,
  );
}

for (const width of [360, 1440]) {
  test(`accepted corrections reopen and copy without a correction server at ${width}px`, async ({
    context,
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await installCorrectionJourneyBridge(page, {
      preaccepted: true,
      available: false,
    });
    await page.goto("/");
    await openPlanning(page);
    await expect(
      page.getByText("Saved accepted revision 1", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("ins")).toHaveText("i");
    if (width === 360) {
      const previews = page
        .locator("[data-slot=card]")
        .filter({
          has: page.getByRole("heading", {
            name: "Review transcript corrections",
            exact: true,
          }),
        })
        .locator("[data-slot=scroll-area]");
      await expect(previews).toHaveCount(2);
      for (const preview of await previews.all()) {
        expect((await preview.boundingBox())?.height).toBeLessThan(130);
      }
    }
    await expect(
      page.getByRole("button", { name: "Correct transcript", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Save revision", exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "Copy saved correction", exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(correctedPlanningText);
    expect((await calls(page)).map(({ command }) => command)).toEqual([
      "read_accepted_transcript_correction",
    ]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("narrow correction previews fit short originals and bound long suggestions", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 1000 });
  await installCorrectionJourneyBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await fixture(
    page,
    "setSuggestion",
    "A long corrected paragraph.\n".repeat(100),
  );
  await page
    .getByRole("button", { name: "Correct transcript", exact: true })
    .click();
  await fixture(page, "setStatus", "complete");
  const added = page.locator("ins");
  await expect(added).toContainText("A long corrected paragraph.");
  const viewport = page.locator("[data-slot=scroll-area-viewport]").filter({
    has: added,
  });
  const dimensions = await viewport.evaluate((node) => ({
    height: node.clientHeight,
    content: node.scrollHeight,
  }));
  expect(dimensions.height).toBeLessThanOrEqual(260);
  expect(dimensions.content).toBeGreaterThan(dimensions.height);
  await viewport.focus();
  await page.keyboard.press("End");
  await expect
    .poll(() => viewport.evaluate((node) => node.scrollTop))
    .toBeGreaterThan(0);
});

test("saved accepted correction survives navigation after explicit acceptance and retains the original", async ({
  page,
}) => {
  await installCorrectionJourneyBridge(page);
  await page.goto("/");
  await openPlanning(page);
  await expect(
    page.getByText("No accepted revision is saved for this transcript.", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Correct transcript", exact: true })
    .click();
  await fixture(page, "setStatus", "complete");
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Home", exact: true }).click();
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save revision", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
  expect(
    (await calls(page)).filter(
      ({ command }) => command === "publish_transcript_correction",
    ),
  ).toHaveLength(1);
});

test("corrupt saved history offers retry without hiding the original or starting remote work", async ({
  page,
}) => {
  await installCorrectionJourneyBridge(page, {
    preaccepted: true,
    available: false,
    recoveryFailure: true,
  });
  await page.goto("/");
  await openPlanning(page);
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "conflicts with its source history" }),
  ).toBeVisible();
  await expect(page.locator("pre").first()).toHaveText(originalPlanningText);
  await expect(
    page.getByRole("button", { name: "Copy saved correction", exact: true }),
  ).toHaveCount(0);
  await fixture(page, "setRecoveryFailure", false);
  await page
    .getByRole("button", { name: "Retry saved corrections", exact: true })
    .click();
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toBeVisible();
  expect(
    (await calls(page)).some(({ command }) => /start_|publish_/.test(command)),
  ).toBe(false);
});

test("a delayed saved correction read cannot appear in a different selected source", async ({
  page,
}) => {
  await installCorrectionJourneyBridge(page, {
    preaccepted: true,
    available: false,
  });
  await page.goto("/");
  // The fixture uses doubled Windows separators consistently with its source catalog.
  await fixture(page, "delayNextRead", planningPath);
  await openPlanning(page);
  await expect(
    page.getByText("Reading saved corrections…", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Choose a transcript", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Review recording review.mp3", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Review corrections", exact: true })
    .click();
  await expect(
    page.getByText("No accepted revision is saved for this transcript.", {
      exact: true,
    }),
  ).toBeVisible();
  await fixture(page, "releaseRead", planningPath);
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Copy saved correction", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("pre").first()).toHaveText(
    "The review is complete.",
  );
});

test("recovery refuses a response bound to another output path and can retry the right owner", async ({
  page,
}) => {
  await installCorrectionJourneyBridge(page, {
    preaccepted: true,
    available: false,
    misboundRecovery: true,
  });
  await page.goto("/");
  await openPlanning(page);
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "did not match the selected transcript" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Copy saved correction", exact: true }),
  ).toHaveCount(0);
  await fixture(page, "setMisboundRecovery", false);
  await page
    .getByRole("button", { name: "Retry saved corrections", exact: true })
    .click();
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toBeVisible();
});

test("new suggestions remain separate from a saved accepted revision until explicit saving", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await installCorrectionJourneyBridge(page, { preaccepted: true });
  await page.goto("/");
  await openPlanning(page);
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toBeVisible();
  const suggestion = "The launch date is Friday at ten.";
  await fixture(page, "setSuggestion", suggestion);
  await page
    .getByRole("button", { name: "Correct transcript", exact: true })
    .click();
  await fixture(page, "setStatus", "complete");
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(suggestion);
  await page
    .getByRole("button", { name: "Copy saved correction", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(correctedPlanningText);
  await page
    .getByText("Read the previously accepted revision", { exact: true })
    .click();
  await expect(
    page.getByText(correctedPlanningText, { exact: true }).first(),
  ).toBeVisible();
  expect(
    (await calls(page)).some(
      ({ command }) => command === "publish_transcript_correction",
    ),
  ).toBe(false);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByText("Saved accepted revision 2", { exact: true }),
  ).toBeVisible();
});

test("a mounted source switch hides and abandons the previous accepted-revision response", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, "isTauri", { value: true });
    const host = globalThis as unknown as {
      __releaseAcceptedRead?: () => void;
    };
    const proof = {
      sourceRevisionSha256: "a".repeat(64),
      sourceSha256: "b".repeat(64),
    };
    Object.assign(globalThis, {
      __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener() {} },
      __TAURI_INTERNALS__: {
        metadata: {
          currentWebview: { label: "main" },
          currentWindow: { label: "main" },
        },
        transformCallback: () => 1,
        invoke: async (command: string, args: { outputPath: string }) => {
          if (command !== "read_accepted_transcript_correction")
            throw new Error(`Unexpected command: ${command}`);
          const one = args.outputPath === "C:/meeting-one.txt";
          const result = {
            schemaVersion: 1,
            outputPath: args.outputPath,
            ...proof,
            revisionCount: one ? 1 : 0,
            acceptedRevision: one
              ? {
                  ...proof,
                  requestId: "accepted-one",
                  revision: 1,
                  terminologySnapshotSha256: "c".repeat(64),
                  correctedSha256: "d".repeat(64),
                  correctedText: "Dose is 25 mg.",
                  revisionPath: "C:/meeting-one.correction.json",
                }
              : null,
          };
          if (one)
            await new Promise<void>((resolve) => {
              host.__releaseAcceptedRead = resolve;
            });
          return result;
        },
      },
    });
  });
  await page.goto("/tests/fixtures/transcript-correction-owner.html");
  await expect(
    page.getByText("Reading saved corrections…", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Switch transcript", exact: true })
    .click();
  await expect(
    page.getByText("No accepted revision is saved for this transcript.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.evaluate(() =>
    (
      globalThis as unknown as { __releaseAcceptedRead: () => void }
    ).__releaseAcceptedRead(),
  );
  await expect(
    page.getByRole("button", { name: "Copy saved correction", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Saved accepted revision 1", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("pre").first()).toHaveText("Second source.");
});
