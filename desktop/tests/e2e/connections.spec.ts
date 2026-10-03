import { expect, test, type Page } from "@playwright/test";
import { installConnectionsBridge } from "./connections-bridge";
async function enter(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page.getByRole("tab", { name: "Connections", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Browse topics", exact: true }),
  ).toBeEnabled();
}
async function browse(page: Page) {
  await page
    .getByRole("button", { name: "Browse topics", exact: true })
    .click();
  await page.getByRole("button", { name: "Yap project", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Yap", exact: true }),
  ).toBeVisible();
}
async function control(page: Page, method: string, arg?: string) {
  await page.evaluate(
    ({ method, arg }) =>
      (
        globalThis as unknown as {
          __connections: Record<string, (arg?: string) => void>;
        }
      ).__connections[method](arg),
    { method, arg },
  );
}

test("model-free graph, list, source details and neighbor navigation remain keyboard operable", async ({
  page,
}) => {
  await installConnectionsBridge(page);
  await enter(page);
  await browse(page);
  const neighbor = page.getByRole("button", {
    name: "Inspect connections with Voice-first interface",
    exact: true,
  });
  await neighbor.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", {
      name: "Why these topics connect",
      exact: true,
    }),
  ).toBeFocused();
  await expect(
    page.getByText("Declared in reviewed source metadata.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(
    page.getByRole("list", { name: "Reviewed connections" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Yap → Private organization server/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Explore Voice-first interface", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Voice-first interface", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Exploration path" })
    .getByRole("button", { name: "Yap", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Yap", exact: true }),
  ).toBeVisible();
  const calls = await page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __connections: {
            calls: Array<{
              command: string;
              args: {
                authorityRevision: string;
                request: { action: string };
              };
            }>;
          };
        }
      ).__connections.calls,
  );
  const reads = calls.filter(
    (call) =>
      call.command === "knowledge_connections" &&
      call.args.request.action === "read",
  );
  expect(reads).toHaveLength(3);
  expect(calls.filter(call => call.command === "knowledge_connections").every(call => call.args.authorityRevision === "1")).toBe(true);
  expect(reads.every((call) => call.args.authorityRevision === "1")).toBe(true);
});
for (const width of [360, 720, 1440])
  test(`connections and source details fit ${width}px without horizontal scrolling`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 740 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installConnectionsBridge(page, { large: true });
    await enter(page);
    await browse(page);
    await page
      .getByRole("button", {
        name: "Inspect connections with Voice-first interface",
        exact: true,
      })
      .click();
    await page
      .getByText("Source revision and fingerprint", { exact: true })
      .click();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await page.getByRole("button", { name: "List", exact: true }).click();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  });
test("cancelled reads and failed retries cannot overwrite the current neighborhood", async ({
  page,
}) => {
  await installConnectionsBridge(page);
  await enter(page);
  await page
    .getByRole("button", { name: "Browse topics", exact: true })
    .click();
  await control(page, "delayNext");
  await page.getByRole("button", { name: "Yap project", exact: true }).click();
  await page
    .getByRole("button", { name: "Cancel exploration", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Exploration cancelled");
  await expect(
    page.getByRole("button", { name: "Try again", exact: true }),
  ).toBeEnabled();
  await control(page, "failNext", "unavailable");
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Connections could not be loaded",
  );
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Yap", exact: true }),
  ).toBeVisible();
});
test("a ready-to-ready identity change clears results and private search before rediscovery", async ({
  page,
}) => {
  await installConnectionsBridge(page);
  await enter(page);
  await browse(page);
  await page
    .getByRole("textbox", { name: "Find a topic", exact: true })
    .fill("Private project phrase");
  await control(page, "changeAuthority");
  await expect(page.getByRole("alert")).toContainText(
    "server or sign-in changed",
  );
  await expect(
    page.getByRole("textbox", { name: "Find a topic", exact: true }),
  ).toHaveValue("");
  await expect(page.getByTestId("knowledge-topic-graph")).toHaveCount(0);
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await page.getByRole("button", { name: "Yap project", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Yap", exact: true }),
  ).toBeVisible();
});
test("a same-authority health recheck preserves exploration without an extra private read", async ({
  page,
}) => {
  await installConnectionsBridge(page);
  await enter(page);
  await browse(page);
  await page
    .getByRole("textbox", { name: "Find a topic", exact: true })
    .fill("Private search draft");
  const callsBefore = await page.evaluate(() => (globalThis as unknown as { __connections: { calls: unknown[] } }).__connections.calls.length);
  await control(page, "recheckAuthority");
  await expect(page.getByTestId("knowledge-topic-graph")).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Find a topic", exact: true }),
  ).toHaveValue("Private search draft");
  expect(await page.evaluate(() => (globalThis as unknown as { __connections: { calls: unknown[] } }).__connections.calls.length)).toBe(callsBefore);
  await expect(
    page.getByRole("heading", { name: "Yap", exact: true }),
  ).toBeVisible();
});
test("stale generations require refreshed topics and unavailable access keeps local controls usable", async ({
  page,
}) => {
  await installConnectionsBridge(page);
  await enter(page);
  await page
    .getByRole("button", { name: "Browse topics", exact: true })
    .click();
  await control(page, "failNext", "knowledgeChanged");
  await page.getByRole("button", { name: "Yap project", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Knowledge changed");
  await expect(page.getByTestId("knowledge-topic-graph")).toHaveCount(0);
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Yap project", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Home", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
});
test("empty authorized topic discovery offers clear recovery", async ({
  page,
}) => {
  await installConnectionsBridge(page, { empty: true });
  await enter(page);
  await page
    .getByRole("button", { name: "Browse topics", exact: true })
    .click();
  await expect(
    page.getByText(/No reviewed topics are available for this search/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Refresh topics", exact: true }),
  ).toBeEnabled();
});
test("connections availability is independent of model search and remains explicit when disabled", async ({
  page,
}) => {
  await installConnectionsBridge(page, { unavailable: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page.getByRole("tab", { name: "Connections", exact: true }).click();
  await expect(
    page.getByText(/Connections are unavailable on this server/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Browse topics", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Check server settings", exact: true }),
  ).toBeVisible();
});

test("an authority change cancels the old graph read before a new browse can commit", async ({ page }) => {
  await installConnectionsBridge(page);
  await enter(page);
  await page.getByRole("button", { name: "Browse topics", exact: true }).click();
  await control(page, "delayNext");
  await page.getByRole("button", { name: "Yap project", exact: true }).click();
  await expect(page.getByRole("button", { name: "Cancel exploration", exact: true })).toBeVisible();
  await control(page, "changeAuthority");
  await expect(page.getByTestId("knowledge-topic-graph")).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("server or sign-in changed");
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await page.getByRole("button", { name: "Yap project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Yap", exact: true })).toBeVisible();
  const calls = await page.evaluate(() => (globalThis as unknown as {
    __connections: { calls: Array<{ command: string; args: { authorityRevision?: string } }> };
  }).__connections.calls);
  expect(calls.filter(call => call.command === "cancel_knowledge_connections")).toHaveLength(1);
  expect(calls.filter(call => call.command === "knowledge_connections").map(call => call.args.authorityRevision)).toEqual(["1", "1", "2", "2"]);
});
