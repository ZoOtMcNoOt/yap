import { expect, test } from "@playwright/test";

test("Archivist action sends only the local recording identity and reports staged-not-active", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, "isTauri", { value: true });
    const calls: Array<{ args: unknown; command: string }> = [];
    let callbackId = 0;
    Object.assign(globalThis, {
      __archivistCalls: calls,
      __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener() {} },
      __TAURI_INTERNALS__: {
        metadata: {
          currentWebview: { label: "main" },
          currentWindow: { label: "main" },
        },
        transformCallback: () => ++callbackId,
        invoke: async (command: string, args?: unknown) => {
          calls.push({ args, command });
          if (command === "start_archivist_ingestion") {
            return {
              jobId: "server-job-private",
              requestId: `archivist-ingestion-${"1".repeat(32)}`,
              resultSha256: "a".repeat(64),
              schemaVersion: 1,
              status: "queued",
            };
          }
          if (command === "archivist_ingestion_status") {
            return {
              captureSha256: "b".repeat(64),
              conceptCount: 2,
              generationSha256: "c".repeat(64),
              jobId: "server-job-private",
              permissionCount: 1,
              requestId: `archivist-ingestion-${"1".repeat(32)}`,
              resultSha256: "a".repeat(64),
              schemaVersion: 1,
              sourceAdmissionSha256: "d".repeat(64),
              status: "staged",
            };
          }
          return undefined;
        },
      },
    });
  });
  await page.goto("/tests/fixtures/archivist-ingestion-owner.html");

  await page.getByRole("button", { name: "Stage Reviewed meeting for knowledge review" }).click();
  await expect(page.getByText("Staged for review. The knowledge generation was not activated."))
    .toBeVisible();
  await expect(page.getByRole("button", { name: "Stage Reviewed meeting for knowledge review" }))
    .toHaveText("Staged");

  const calls = await page.evaluate(() => (
    globalThis as unknown as {
      __archivistCalls: Array<{ args: Record<string, unknown>; command: string }>;
    }
  ).__archivistCalls);
  expect(calls.filter(({ command }) => command === "start_archivist_ingestion"))
    .toEqual([{
      args: { recordingId: "recording-local-1" },
      command: "start_archivist_ingestion",
    }]);
  expect(JSON.stringify(calls)).not.toContain("server-job-private");
  expect(JSON.stringify(calls)).not.toContain("aaaaaaaaaaaaaaaa");
});
