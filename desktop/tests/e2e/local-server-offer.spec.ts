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
  await expect(banner).toContainText("A Yap server is running on this computer.");

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
});
