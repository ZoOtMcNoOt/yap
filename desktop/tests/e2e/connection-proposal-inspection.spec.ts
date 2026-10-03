import { expect, test, type Page } from "@playwright/test";
import {
  installProposalInspectionBridge,
  proposalReference,
} from "./connection-proposal-bridge";

async function enter(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page
    .getByRole("tab", { name: "Review proposals", exact: true })
    .click();
  await expect(page.getByLabel("Connection proposal reference")).toBeEnabled();
}
async function read(page: Page) {
  await page
    .getByLabel("Connection proposal reference")
    .fill(proposalReference);
  await page.getByRole("button", { name: "Open connection proposal" }).click();
}
async function control(page: Page, method: string, value?: string) {
  await page.evaluate(
    ({ method, value }) =>
      (globalThis as any).__proposalInspection[method](value),
    { method, value },
  );
}
async function journey(
  page: Page,
  method: string,
  ...values: Array<string | boolean>
) {
  await page.evaluate(
    ({ method, values }) =>
      (globalThis as any).__knowledgeJourney[method](...values),
    { method, values },
  );
}
for (const width of [360, 720, 1440])
  test(`saved proposal and exact source details fit ${width}px with keyboard access`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await installProposalInspectionBridge(page);
    await enter(page);
    await page
      .getByLabel("Connection proposal reference")
      .fill(proposalReference);
    await page
      .getByRole("button", { name: "Open connection proposal" })
      .focus();
    await page.keyboard.press("Enter");
    const result = page.getByRole("article", {
      name: "Saved connection proposal",
    });
    await expect(result).toBeVisible();
    await expect(
      result.getByText("Proposed · Requires human review"),
    ).toBeVisible();
    await expect(
      result.getByText("Launch review → Launch approval"),
    ).toBeVisible();
    await expect(
      result.getByText("The reviewed launch was approved for Friday.", {
        exact: true,
      }),
    ).toHaveCount(2);
    await result.locator("summary").first().focus();
    await page.keyboard.press("Enter");
    await expect(
      result.getByText("meetings/launch-review.md", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    expect(
      await result.evaluate((article) => {
        const panel = article.closest("section")!;
        const style = getComputedStyle(panel);
        const width =
          panel.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight);
        return [
          ...panel.querySelectorAll(
            "article, form, [data-slot=badge], [data-slot=button]",
          ),
        ].every(
          (element) => element.getBoundingClientRect().width <= width + 1,
        );
      }),
    ).toBe(true);
    const calls = await page.evaluate(
      () => (globalThis as any).__proposalInspection.calls,
    );
    expect(calls).toHaveLength(1);
    expect(calls[0].args.request).toEqual({
      action: "proposal",
      proposalId: proposalReference,
    });
    expect(calls[0].args.authorityRevision).toBe("1");
    expect(
      await page.evaluate(
        () => (globalThis as any).__knowledgeJourney.mutations,
      ),
    ).toEqual([]);
  });
test("editing the reference hides old evidence; tab changes retain the owned draft", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await read(page);
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
  await page.getByLabel("Connection proposal reference").fill("f".repeat(64));
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "Search sources", exact: true }).click();
  await page
    .getByRole("tab", { name: "Review proposals", exact: true })
    .click();
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(
    "f".repeat(64),
  );
});
test("unavailable and stale proposals explain recovery and retry without publishing", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await control(page, "mode", "notFound");
  await read(page);
  await expect(
    page.getByText(/This connection proposal is unavailable/),
  ).toBeVisible();
  await control(page, "mode", "knowledgeChanged");
  await page
    .getByRole("button", { name: "Try again: Open connection proposal" })
    .click();
  await expect(
    page.getByText(/Knowledge changed since this proposal/),
  ).toBeVisible();
  await control(page, "mode", "success");
  await page
    .getByRole("button", { name: "Try again: Open connection proposal" })
    .click();
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Search current sources" }).click();
  await expect(
    page.getByRole("tab", { name: "Search sources", exact: true }),
  ).toHaveAttribute("data-state", "active");
});
test("cancel waits for read completion and ignores its late evidence", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await control(page, "delay");
  await read(page);
  await page.getByRole("button", { name: /Cancel/ }).click();
  await expect(page.getByLabel("Connection proposal reference")).toBeDisabled();
  await control(page, "release");
  await expect(page.getByLabel("Connection proposal reference")).toBeEnabled();
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toHaveCount(0);
  const calls = await page.evaluate(
    () => (globalThis as any).__proposalInspection.calls,
  );
  expect(
    calls.filter((c: any) => c.command === "cancel_knowledge_connections"),
  ).toHaveLength(1);
  expect(calls[1].args.requestId).toBe(calls[0].args.requestId);
});
test("offline drafts stay with their owner; changed identity clears drafts and ignores late reads", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await read(page);
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
  await journey(page, "setAvailable", false);
  await expect(
    page.getByText(/Saved connections need your organization server/),
  ).toBeVisible();
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(
    proposalReference,
  );
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toHaveCount(0);
  await journey(page, "setAvailable", true);
  await control(page, "delay");
  await page.getByRole("button", { name: "Open connection proposal" }).click();
  await journey(page, "recheckConnection", "2");
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(
    "",
  );
  await control(page, "release");
  await expect(page.getByLabel("Connection proposal reference")).toBeEnabled();
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toHaveCount(0);
});

async function createConnection(page: Page) {
  await page.getByRole("tab", { name: "Search sources", exact: true }).click();
  await page
    .getByLabel("What reviewed information are you looking for?")
    .fill("launch approval");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await journey(page, "setStatus", "librarian_query", "complete");
  await expect(
    page.getByText("Permission-safe evidence is ready.", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Why are these connected?")
    .fill("The launch review references the approval decision.");
  await page
    .getByRole("button", { name: "Review connection", exact: true })
    .click();
  await journey(page, "setStatus", "curator_proposal", "proposed");
  await expect(
    page.getByRole("button", { name: "Inspect saved connection", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Inspect saved connection", exact: true })
    .click();
}
test("new Curator proposals hand off explicitly to their saved source inspection", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await createConnection(page);
  await expect(
    page.getByRole("tab", { name: "Review proposals", exact: true }),
  ).toHaveAttribute("data-state", "active");
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(
    proposalReference,
  );
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
  const calls = await page.evaluate(
    () => (globalThis as any).__knowledgeJourney.mutations,
  );
  expect(
    calls.filter((c: any) => c.command === "start_connection_proposal"),
  ).toHaveLength(1);
  expect(calls.some((c: any) => /publish|activate/.test(c.command))).toBe(
    false,
  );
});
test("a new proposal handoff cancels the old inspection and waits for its acknowledgment", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await page.getByLabel("Connection proposal reference").fill("f".repeat(64));
  await control(page, "delay");
  await page.getByRole("button", { name: "Open connection proposal" }).click();
  await createConnection(page);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (globalThis as any).__proposalInspection.calls.filter(
            (c: any) => c.command === "cancel_knowledge_connections",
          ).length,
      ),
    )
    .toBe(1);
  expect(
    await page.evaluate(
      () =>
        (globalThis as any).__proposalInspection.calls.filter(
          (c: any) => c.command === "knowledge_connections",
        ).length,
    ),
  ).toBe(1);
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(
    proposalReference,
  );
  await control(page, "release");
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
  const calls = await page.evaluate(
    () => (globalThis as any).__proposalInspection.calls,
  );
  expect(
    calls
      .filter((c: any) => c.command === "knowledge_connections")
      .map((c: any) => c.args.request.proposalId),
  ).toEqual(["f".repeat(64), proposalReference]);
});

test("a late cancellation failure cannot attach to a new account's inspection", async ({
  page,
}) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await control(page, "delay");
  await control(page, "delayCancellation");
  await read(page);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await journey(page, "recheckConnection", "2");
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue(
    "",
  );
  await control(page, "release");
  await expect(page.getByLabel("Connection proposal reference")).toBeEnabled();
  await read(page);
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
  await control(page, "rejectCancellation");
  await expect(
    page.getByText(/Cancellation could not be confirmed/),
  ).toHaveCount(0);
  await expect(
    page.getByRole("article", { name: "Saved connection proposal" }),
  ).toBeVisible();
});

async function confirmDiscard(page: Page) {
  await page.getByRole("button", { name: /^(Discard proposal…|Try discard again…)$/ }).click();
  const dialog = page.getByRole("alertdialog", { name: "Discard this connection proposal?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Discard proposal", exact: true }).click();
}

for (const width of [360, 720, 1440])
  test(`discard needs explicit confirmation and preserves navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installProposalInspectionBridge(page);
    await enter(page);
    await read(page);
    await page.getByRole("button", { name: "Discard proposal…", exact: true }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("discard-confirmation.png") });
    await dialog.getByRole("button", { name: "Keep proposal" }).focus();
    await page.keyboard.press("Enter");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Discard proposal…", exact: true })).toBeFocused();
    expect(await page.evaluate(() => (globalThis as any).__proposalInspection.calls
      .filter((c: any) => c.args.request?.action === "discard").length)).toBe(0);
    await confirmDiscard(page);
    await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("discard-confirmed.png") });
    await expect(page.getByRole("article", { name: "Saved connection proposal" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const mutations = await page.evaluate(() => (globalThis as any).__proposalInspection.calls
      .filter((c: any) => c.args.request?.action === "discard"));
    expect(mutations).toHaveLength(1);
    expect(mutations[0].args.request).toEqual({ action: "discard", proposalId: proposalReference });
    expect(mutations[0].args.authorityRevision).toBe("1");
    await page.getByRole("button", { name: "Search current sources" }).click();
    await expect(page.getByRole("tab", { name: "Search sources", exact: true })).toHaveAttribute("data-state", "active");
  });

test("lost discard confirmation retries the same reference instead of claiming cancelled or failed write", async ({ page }) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await read(page);
  await control(page, "mode", "lostDiscardReceipt");
  await confirmDiscard(page);
  await expect(page.getByText(/It may already have completed/)).toBeVisible();
  await expect(page.getByText(/Proposal discarded\. Its history/)).toHaveCount(0);
  await confirmDiscard(page);
  await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
  await page.getByLabel("Connection proposal reference").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
  const calls = await page.evaluate(() => (globalThis as any).__proposalInspection.calls);
  expect(calls.filter((c: any) => c.args.request?.action === "discard")
    .map((c: any) => c.args.request.proposalId)).toEqual([proposalReference, proposalReference]);
  await page.getByLabel("Connection proposal reference").fill("f".repeat(64));
  await expect(page.getByText(/Proposal discarded\. Its history/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Discard proposal…", exact: true })).toBeEnabled();
});

test("obsolete owned proposals can be discarded without reopening unavailable source evidence", async ({ page }) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await control(page, "mode", "knowledgeChanged");
  await read(page);
  await expect(page.getByText(/Knowledge changed since this proposal/)).toBeVisible();
  await control(page, "mode", "success");
  await confirmDiscard(page);
  await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
});

test("identity changes close confirmation and ignore delayed discard receipts", async ({ page }) => {
  await installProposalInspectionBridge(page);
  await enter(page);
  await read(page);
  await page.getByRole("button", { name: "Discard proposal…", exact: true }).click();
  await journey(page, "recheckConnection", "2");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(await page.evaluate(() => (globalThis as any).__proposalInspection.calls
    .filter((c: any) => c.args.request?.action === "discard").length)).toBe(0);
  await read(page);
  await control(page, "delay");
  await confirmDiscard(page);
  await expect(page.getByText("Discarding saved proposal…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
  await journey(page, "recheckConnection", "3");
  await control(page, "release");
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue("");
  await expect(page.getByText(/Proposal discarded\. Its history/)).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Saved connection proposal" })).toHaveCount(0);
});

for (const delivery of ["confirmed", "lost"])
  test(`new handoffs retain an in-flight discard and its ${delivery} receipt recovery`, async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 900 });
    await installProposalInspectionBridge(page);
    await enter(page);
    const oldReference = "f".repeat(64);
    await page.getByLabel("Connection proposal reference").fill(oldReference);
    await page.getByRole("button", { name: "Open connection proposal" }).click();
    await expect(page.getByRole("article", { name: "Saved connection proposal" })).toBeVisible();
    await control(page, "delay");
    if (delivery === "lost") await control(page, "mode", "lostDiscardReceipt");
    await confirmDiscard(page);
    await createConnection(page);
    const next = page.getByRole("button", { name: "Open new saved connection" });
    await expect(page.getByLabel("Connection proposal reference")).toHaveValue(oldReference);
    expect(await page.evaluate(() => (globalThis as any).__proposalInspection.calls
      .filter((c: any) => c.command === "cancel_knowledge_connections").length)).toBe(0);
    await expect(next).toBeDisabled();
    await control(page, "release");
    if (delivery === "lost") {
      await expect(page.getByText(/It may already have completed/)).toBeVisible();
      await expect(next).toBeDisabled();
      await expect(page.getByLabel("Connection proposal reference")).toHaveValue(oldReference);
      await confirmDiscard(page);
    }
    await expect(page.getByText(/Proposal discarded\. Its history/)).toBeVisible();
    await expect(next).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
    await next.click();
    await expect(page.getByLabel("Connection proposal reference")).toHaveValue(proposalReference);
    await expect(page.getByRole("article", { name: "Saved connection proposal" })).toBeVisible();
    const calls = await page.evaluate(() => (globalThis as any).__proposalInspection.calls);
    expect(calls.filter((c: any) => c.args.request?.action === "discard")
      .map((c: any) => c.args.request.proposalId)).toEqual(
        delivery === "lost" ? [oldReference, oldReference] : [oldReference],
      );
    expect(calls.some((c: any) => c.command === "cancel_knowledge_connections")).toBe(false);
  });
