import { expect, test } from "@playwright/test";

test("correction stays native-owned, publishes immutably, and cancels on source change", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, "isTauri", { value: true });
    const calls: Array<{ args: unknown; command: string }> = [];
    let callbackId = 0;
    let requestSequence = 0;
    Object.assign(globalThis, {
      __transcriptCorrectionCalls: calls,
      __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener() {} },
      __TAURI_INTERNALS__: {
        metadata: {
          currentWebview: { label: "main" },
          currentWindow: { label: "main" },
        },
        transformCallback: () => ++callbackId,
        invoke: async (command: string, args?: unknown) => {
          calls.push({ args, command });
          const requestId = `correction-${Math.max(requestSequence, 1)}`;
          if (command === "start_transcript_correction") {
            requestSequence += 1;
            return {
              applied: false,
              correctedText: null,
              reason: null,
              requestId: `correction-${requestSequence}`,
              schemaVersion: 1,
              sourceRevisionSha256: "a".repeat(64),
              sourceSha256: "b".repeat(64),
              terminologySnapshotSha256: "c".repeat(64),
              status: "queued",
            };
          }
          if (command === "transcript_correction_status") {
            const polledId = (args as { requestId: string }).requestId;
            return {
              applied: polledId === "correction-1",
              correctedText: polledId === "correction-1" ? "Dose is 25 mg." : null,
              reason: null,
              requestId: polledId,
              schemaVersion: 1,
              sourceRevisionSha256: "a".repeat(64),
              sourceSha256: "b".repeat(64),
              terminologySnapshotSha256: "c".repeat(64),
              status: polledId === "correction-1" ? "complete" : "running",
            };
          }
          if (command === "cancel_transcript_correction") {
            return {
              applied: false,
              correctedText: null,
              reason: null,
              requestId: (args as { requestId: string }).requestId,
              schemaVersion: 1,
              sourceRevisionSha256: "a".repeat(64),
              sourceSha256: "b".repeat(64),
              terminologySnapshotSha256: "c".repeat(64),
              status: "cancelled",
            };
          }
          if (command === "publish_transcript_correction") {
            return {
              correctedSha256: "c".repeat(64),
              correctedText: "Dose is 25 mg.",
              requestId,
              revision: 1,
              revisionPath: "C:/meeting-one.transcript-correction.r00000000000000000001.json",
              sourceRevisionSha256: "a".repeat(64),
              sourceSha256: "b".repeat(64),
              terminologySnapshotSha256: "c".repeat(64),
            };
          }
          return undefined;
        },
      },
    });
  });
  await page.goto("/tests/fixtures/transcript-correction-owner.html");

  await page.getByRole("button", { name: "Correct transcript" }).click();
  await expect(page.getByText("Dose is 25 mg.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Save revision" }).click();
  await expect(page.getByText(/Saved immutable revision 1/)).toBeVisible();

  await page.getByRole("button", { name: "Correct transcript" }).click();
  await expect(page.getByText("Applying source-bound corrections…")).toBeVisible();
  await page.getByRole("button", { name: "Switch transcript" }).click();
  await expect(page.getByText("Second source.", { exact: true })).toBeVisible();

  const calls = await page.evaluate(() => (
    globalThis as unknown as {
      __transcriptCorrectionCalls: Array<{ args: Record<string, unknown>; command: string }>;
    }
  ).__transcriptCorrectionCalls);
  expect(calls.filter(({ command }) => command === "start_transcript_correction"))
    .toEqual([
      { args: { outputPath: "C:/meeting-one.txt" }, command: "start_transcript_correction" },
      { args: { outputPath: "C:/meeting-one.txt" }, command: "start_transcript_correction" },
    ]);
  expect(calls.filter(({ command }) => command === "publish_transcript_correction"))
    .toEqual([{
      args: { requestId: "correction-1" },
      command: "publish_transcript_correction",
    }]);
  await expect.poll(async () => page.evaluate(() => (
    globalThis as unknown as {
      __transcriptCorrectionCalls: Array<{ args: Record<string, unknown>; command: string }>;
    }
  ).__transcriptCorrectionCalls.filter(({ command }) =>
    command === "cancel_transcript_correction").length)).toBe(1);
});
