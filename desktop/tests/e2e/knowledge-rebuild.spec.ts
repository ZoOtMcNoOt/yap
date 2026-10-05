import { expect, test, type Page } from "@playwright/test";
import { installRebuildBridge } from "./rebuild-bridge";
async function enter(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page.getByRole("tab", { name: "Rebuild", exact: true }).click();
}
async function control(page: Page, method: string, arg?: string) {
  await page.evaluate(
    ({ method, arg }) =>
      (
        globalThis as unknown as {
          __rebuild: Record<string, (arg?: string) => void>;
        }
      ).__rebuild[method](arg),
    { method, arg },
  );
}
const button = (page: Page, name: string) =>
  page.getByRole("button", { name, exact: true });
async function prepare(page: Page) {
  await button(page, "Inspect reviewed source").click();
  await button(page, "Stage reviewed source").click();
  await button(page, "Prepare embeddings").click();
  await button(page, "Inspect prepared generation").click();
  await expect(button(page, "Review publication")).toBeEnabled();
}
async function publish(page: Page) {
  await button(page, "Review publication").click();
  await expect(page.getByRole("alertdialog")).toContainText(
    "Expected current reference",
  );
  await button(page, "Publish knowledge").click();
}

test("reviewed source to explicit publication and retained restore preserves local controls", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await expect(
    page.getByRole("heading", {
      name: "Rebuild reviewed knowledge",
      exact: true,
    }),
  ).toBeVisible();
  await expect(button(page, "Review publication")).toBeDisabled();
  await prepare(page);
  await expect(
    page.getByText("reviewed/organization", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("tab", { name: "Rebuild", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/yap-rebuild-wide.png", fullPage: true });
  await publish(page);
  await expect(page.getByRole("status")).toContainText(
    "Reviewed knowledge published.",
  );
  await expect(
    page.getByRole("textbox", { name: "Saved generation reference" }),
  ).toHaveValue("b".repeat(64));
  await button(page, "Inspect saved generation").click();
  await button(page, "Review restore").click();
  await button(page, "Restore knowledge").click();
  await expect(page.getByRole("status")).toContainText(
    "Retained knowledge restored.",
  );
  const calls = await page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __rebuild: {
            calls: { request: { action: string }; authorityRevision: string }[];
          };
        }
      ).__rebuild.calls,
  );
  expect(calls.map((c) => c.request.action)).toEqual([
    "source",
    "stage",
    "embeddings",
    "inspect",
    "publish",
    "inspect",
    "restore",
  ]);
  expect(calls.every((c) => c.authorityRevision === "1")).toBe(true);
  await expect(
    page.getByRole("button", { name: "Transcribe", exact: true }),
  ).toBeEnabled();
});
test("lost activation reply stays unconfirmed and explicit replay confirms without automatic retry", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await prepare(page);
  await control(page, "loseNextReply");
  await publish(page);
  await expect(
    page.getByText(/The write outcome is unconfirmed/),
  ).toBeVisible();
  await expect(button(page, "Review publication")).toBeDisabled();
  await button(page, "Inspect reviewed source").click();
  await button(page, "Confirm previous request").click();
  await expect(page.getByRole("status")).toContainText("Activation confirmed.");
  const actions = await page.evaluate(() =>
    (
      globalThis as unknown as {
        __rebuild: { calls: { request: { action: string } }[] };
      }
    ).__rebuild.calls.map((c) => c.request.action),
  );
  expect(actions).toEqual([
    "source",
    "stage",
    "embeddings",
    "inspect",
    "publish",
    "source",
    "publish",
  ]);
});
test("failed provider and inconsistent metadata prevent publication while staged replay recovers", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await button(page, "Inspect reviewed source").click();
  await button(page, "Stage reviewed source").click();
  await control(page, "failNext", "unavailable");
  await button(page, "Prepare embeddings").click();
  await expect(page.getByRole("alert")).toContainText("unavailable");
  await expect(button(page, "Review publication")).toBeDisabled();
  await button(page, "Prepare embeddings").click();
  await control(page, "wrongDescriptor");
  await button(page, "Inspect prepared generation").click();
  await expect(page.getByRole("alert")).toContainText("could not be verified");
  await expect(button(page, "Review publication")).toBeDisabled();
  await button(page, "Prepare embeddings").click();
  await button(page, "Inspect prepared generation").click();
  await expect(button(page, "Review publication")).toBeEnabled();
});
test("source drift refuses stale publication and a new inspection requires a renewed decision", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await prepare(page);
  await control(page, "changeActive");
  await publish(page);
  await expect(page.getByRole("alert")).toContainText("Knowledge changed");
  await expect(button(page, "Review publication")).toBeDisabled();
  await button(page, "Inspect reviewed source").click();
  await expect(button(page, "Review publication")).toBeDisabled();
});
test("switching Knowledge tabs retains the request but an account change hides late private replies", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await control(page, "delayNext");
  await button(page, "Inspect reviewed source").click();
  await page.getByRole("tab", { name: "Connections", exact: true }).click();
  await page.getByRole("tab", { name: "Rebuild", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Checking");
  await control(page, "changeOwner");
  await control(page, "release");
  await expect(
    page.getByText("reviewed/organization", { exact: true }),
  ).not.toBeVisible();
  await button(page, "Inspect reviewed source").click();
  await expect(
    page.getByText("reviewed/organization", { exact: true }),
  ).toBeVisible();
});
test("unavailable rebuilding does not disable offline capture", async ({
  page,
}) => {
  await installRebuildBridge(page, { unavailable: true });
  await enter(page);
  await expect(button(page, "Inspect reviewed source")).toBeDisabled();
  await expect(
    page.getByText(/local capture and saved history remain available/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Transcribe", exact: true }),
  ).toBeEnabled();
});
test("narrow reduced-motion rebuilding remains keyboard operable without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installRebuildBridge(page);
  await enter(page);
  await button(page, "Inspect reviewed source").focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("reviewed/organization", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("tab", { name: "Rebuild", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "/tmp/yap-rebuild-narrow.png",
    fullPage: true,
  });
});

test("denied reviewers and pruned retained references remain contained", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await control(page, "failNext", "denied");
  await button(page, "Inspect reviewed source").click();
  await expect(page.getByRole("alert")).toContainText(
    "not granted this reviewer action",
  );
  await expect(button(page, "Review publication")).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Saved generation reference" })
    .fill("f".repeat(64));
  await button(page, "Inspect saved generation").click();
  await expect(page.getByRole("alert")).toContainText("unavailable, pruned");
  await expect(button(page, "Review restore")).toBeDisabled();
});

test("revoked reviewer access clears private inspection and saved references", async ({
  page,
}) => {
  await installRebuildBridge(page);
  await enter(page);
  await button(page, "Inspect reviewed source").click();
  await expect(
    page.getByText("reviewed/organization", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Saved generation reference" })
    .fill("b".repeat(64));
  await control(page, "failNext", "denied");
  await button(page, "Inspect reviewed source").click();
  await expect(page.getByRole("alert")).toContainText(
    "not granted this reviewer action",
  );
  await expect(
    page.getByText("reviewed/organization", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Saved generation reference" }),
  ).toHaveValue("");
});
