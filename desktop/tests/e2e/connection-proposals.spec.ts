import { expect, test, type Page } from "@playwright/test";
import { installKnowledgeJourneyBridge } from "./knowledge-journey-bridge";

async function control(page: Page, method: string, ...args: string[]) {
  await page.evaluate(
    ({ method, args }) => {
      const fixture = (
        globalThis as unknown as {
          __knowledgeJourney: Record<string, (...args: string[]) => void>;
        }
      ).__knowledgeJourney;
      fixture[method](...args);
    },
    { method, args },
  );
}
async function mutations(page: Page) {
  return page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __knowledgeJourney: {
            mutations: Array<{
              command: string;
              args: Record<string, unknown>;
            }>;
          };
        }
      ).__knowledgeJourney.mutations,
  );
}
async function search(
  page: Page,
  sources: "pair" | "duplicate" | "long" = "pair",
) {
  await installKnowledgeJourneyBridge(page, sources);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page
    .getByLabel("What reviewed information are you looking for?")
    .fill("launch approval");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await control(page, "setStatus", "librarian_query", "complete");
  await expect(
    page.getByText("Permission-safe evidence is ready.", { exact: true }),
  ).toBeVisible();
}
async function draft(page: Page) {
  await page
    .getByLabel("Why are these connected?")
    .fill("The launch review references the approval decision.");
}

for (const width of [360, 1440]) {
  test(`connection review preserves direction and exact native intent at ${width}px`, async ({
    context,
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await search(page);
    await page.getByText("Check both cited excerpts", { exact: true }).click();
    await expect(
      page
        .locator("details")
        .filter({
          has: page.getByText("Check both cited excerpts", { exact: true }),
        })
        .getByText("Source 2 · launch approval", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Reverse connection direction" })
      .click();
    await expect(page.getByLabel("From source", { exact: true })).toHaveValue(
      "1",
    );
    await expect(page.getByLabel("To source", { exact: true })).toHaveValue(
      "0",
    );
    await page.getByLabel("Relationship type").fill("depends_on");
    await draft(page);
    await page
      .getByRole("button", { name: "Review connection", exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await control(page, "setStatus", "curator_proposal", "proposed");
    await expect(
      page.getByText("Proposal created", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Copy proposal reference", exact: true })
      .click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe("proposal-1");
    const calls = await mutations(page);
    expect(
      calls.find(({ command }) => command === "start_connection_proposal")
        ?.args,
    ).toEqual({
      queryRequestId: "librarian_query-1",
      sourceIndex: 1,
      targetIndex: 0,
      relationshipType: "depends_on",
      rationale: "The launch review references the approval decision.",
      authorityRevision: "1",
    });
    expect(calls.some(({ command }) => /publish|activate/.test(command))).toBe(
      false,
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

for (const sources of ["duplicate", "long"] as const) {
  test(`connection review requires two distinct bounded excerpts: ${sources}`, async ({
    page,
  }) => {
    await search(page, sources);
    await expect(
      page.getByText(
        "To propose a connection, search for two different reviewed sources with excerpts of at most 1,024 characters each.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Review connection", exact: true }),
    ).toHaveCount(0);
    expect(
      (await mutations(page)).some(
        ({ command }) => command === "start_connection_proposal",
      ),
    ).toBe(false);
  });
}

test("connection review validates intent, retries failure, and clears old success when direction changes", async ({
  page,
}) => {
  await search(page);
  await draft(page);
  await page.getByLabel("Relationship type").fill("has spaces");
  await expect(
    page.getByRole("button", { name: "Review connection", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Relationship type").fill("references");
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await control(page, "setStatus", "curator_proposal", "failed");
  await page
    .getByRole("button", { name: "Retry connection", exact: true })
    .click();
  await control(page, "setStatus", "curator_proposal", "rejected");
  await expect(
    page.getByText(
      "Curator could not support this connection from both sources.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await control(page, "setStatus", "curator_proposal", "proposed");
  await expect(
    page.getByText("Proposal created", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Reverse connection direction" })
    .click();
  await expect(page.getByText("Proposal created", { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByLabel("Why are these connected?")).toHaveValue(
    "The launch review references the approval decision.",
  );
});

test("connection cancellation preserves the draft across tasks and sends one cancellation", async ({
  page,
}) => {
  await search(page);
  await draft(page);
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await page.getByRole("tab", { name: "Ask a question", exact: true }).click();
  await page.getByRole("tab", { name: "Search sources", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Retry connection", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Why are these connected?")).toHaveValue(
    "The launch review references the approval decision.",
  );
  expect(
    (await mutations(page)).filter(
      ({ command }) => command === "cancel_curator_proposal",
    ),
  ).toHaveLength(1);
});

test("a new search removes the old connection draft and cancels its active review", async ({
  page,
}) => {
  await search(page);
  await draft(page);
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await page
    .getByLabel("What reviewed information are you looking for?")
    .fill("another launch record");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await expect(page.getByLabel("Why are these connected?")).toHaveCount(0);
  await control(page, "setStatus", "librarian_query", "complete");
  await expect(page.getByLabel("Why are these connected?")).toHaveValue("");
  await expect
    .poll(
      async () =>
        (await mutations(page)).filter(
          ({ command }) => command === "cancel_curator_proposal",
        ).length,
    )
    .toBe(1);
});

test("an account switch contains a late accepted connection review and hides its private draft", async ({
  page,
}) => {
  await search(page);
  await draft(page);
  await control(page, "delayNextSubmission", "curator_proposal");
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await control(page, "recheckConnection", "2");
  await expect(page.getByLabel("Why are these connected?")).toHaveCount(0);
  await control(page, "releaseSubmission", "curator_proposal");
  await expect
    .poll(
      async () =>
        (await mutations(page)).filter(
          ({ command }) => command === "cancel_curator_proposal",
        ).length,
    )
    .toBe(1);
  await expect(page.getByText("Proposal created", { exact: true })).toHaveCount(
    0,
  );
});

test("source invalidation does not issue a second cancellation while acknowledgement is pending", async ({
  page,
}) => {
  await search(page);
  await draft(page);
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await control(page, "delayNextCancellation", "curator_proposal");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page
    .getByLabel("What reviewed information are you looking for?")
    .fill("replacement source");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await control(page, "releaseCancellation", "curator_proposal");
  await expect(page.getByLabel("Why are these connected?")).toHaveCount(0);
  expect(
    (await mutations(page)).filter(
      ({ command }) => command === "cancel_curator_proposal",
    ),
  ).toHaveLength(1);
});
