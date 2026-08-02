import { expect, test } from "@playwright/test";

import { installQueuedServerBridge, serverCalls } from "./app-server-bridge";

// Discovery must offer, never act: the banner appears only when a yap-server
// answers on loopback while nothing is configured, and the only side effect it
// can cause is the ordinary settings save the user explicitly clicks into.

test("a discovered local server is offered and Connect routes through the settings save", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { localServerOffer: true });
  await page.goto("/");

  const banner = page.getByTestId("local-server-offer");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("A Yap server is available through this computer's local connection.");
  expect(await serverCalls(page)).toEqual([]);

  await banner.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(banner).toHaveCount(0);

  const calls = await serverCalls(page);
  expect(calls).toEqual([
    {
      args: {
        settings: {
          authentication: null,
          baseUrl: "http://127.0.0.1:18765",
          enabled: true,
          schemaVersion: 2,
        },
      },
      command: "set_server_settings",
    },
  ]);
});

test("no local server means no banner, and the probe was actually asked", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");

  await expect(page.getByText("Welcome back")).toBeVisible();
  await expect(page.getByTestId("local-server-offer")).toHaveCount(0);
  const commands = await page.evaluate(() =>
    (globalThis as unknown as { __queuedServerBoundaryTest: { calls: string[] } })
      .__queuedServerBoundaryTest.calls,
  );
  expect(commands).toContain("probe_local_server");
});

test("a local server that starts after Yap is already open is offered", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");

  await expect(page.getByTestId("local-server-offer")).toHaveCount(0);
  await expect.poll(async () => page.evaluate(() =>
    (globalThis as unknown as { __queuedServerBoundaryTest: { calls: string[] } })
      .__queuedServerBoundaryTest.calls.filter((command) => command === "probe_local_server")
      .length
  )).toBeGreaterThan(0);
  await page.evaluate(() => {
    (globalThis as unknown as {
      __queuedServerBoundaryTest: { setLocalServerAvailable: (available: boolean) => void };
    }).__queuedServerBoundaryTest.setLocalServerAvailable(true);
  });

  await expect(page.getByTestId("local-server-offer")).toBeVisible({ timeout: 5_000 });
});

test("an optional server refresh cannot hold local recovery busy", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", {
    fallbackVerifyFails: true,
    serverRefreshNeverSettles: true,
  });
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Ready", exact: true })).toBeVisible();
  await expect(page.getByText("Setup check failed", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("server-route-status")).toContainText("On this device");

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "System", exact: true }).click();
  const verify = page.getByRole("button", { name: "Verify", exact: true });
  await verify.click();
  await expect(page.getByText(/Verify failed:/)).toBeVisible();
  await expect(verify).toBeEnabled();
});

test("a missing local model remains directly setup-able without server or auth", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", {
    localModelStatus: "missing",
    serverRefreshNeverSettles: true,
  });
  await page.goto("/");

  const settings = page.getByRole("dialog", { name: "Settings" });
  await expect(settings).toBeVisible();
  const localRow = settings.getByText("On-device dictation", { exact: true }).locator("..");
  await expect(localRow).toContainText("Not installed");
  await expect(settings.getByRole("button", { name: "Install", exact: true })).toBeEnabled();
  await expect(settings.getByLabel("Server URL")).toHaveCount(0);
  await expect(page.getByText("Setup check failed", { exact: true })).toHaveCount(0);
});

test("on-device setup stays primary and server or SSO configuration stays optional", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set");
  await page.goto("/");

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "System", exact: true }).click();

  await expect(page.getByText("On-device dictation", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Server URL")).toHaveCount(0);
  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  await expect(page.getByLabel("Server URL")).toBeVisible();
  await expect(page.getByText("Local dictation does not require a server or account."))
    .toBeVisible();
});

test("declining the offer sticks across a relaunch", async ({ page }) => {
  await installQueuedServerBridge(page, "not_set", { localServerOffer: true });
  await page.goto("/");

  const banner = page.getByTestId("local-server-offer");
  await expect(banner).toBeVisible();
  await banner.getByRole("button", { name: "Not now", exact: true }).click();
  await expect(banner).toHaveCount(0);

  await page.reload();
  await expect(page.getByText("Welcome back")).toBeVisible();
  await expect(page.getByTestId("local-server-offer")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("yap.localServerOffer.dismissed.v1")))
    .toBe("http://127.0.0.1:18765");
  const commands = await page.evaluate(() =>
    (globalThis as unknown as { __queuedServerBoundaryTest: { calls: string[] } })
      .__queuedServerBoundaryTest.calls,
  );
  expect(commands).not.toContain("probe_local_server");
});

test("a configured but disabled server suppresses loopback discovery", async ({ page }) => {
  await installQueuedServerBridge(page, "disabled", {
    configuredServerUrl: "https://server.example",
  });
  await page.goto("/");

  await expect(page.getByText("Welcome back")).toBeVisible();
  await expect.poll(async () => page.evaluate(() =>
    (globalThis as unknown as { __queuedServerBoundaryTest: { calls: string[] } })
      .__queuedServerBoundaryTest.calls.filter((command) => command === "server_settings").length
  )).toBeGreaterThan(0);
  const commands = await page.evaluate(() =>
    (globalThis as unknown as { __queuedServerBoundaryTest: { calls: string[] } })
      .__queuedServerBoundaryTest.calls,
  );
  expect(commands).not.toContain("probe_local_server");
  await expect(page.getByTestId("local-server-offer")).toHaveCount(0);
});
