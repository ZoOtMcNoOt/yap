import { expect, test, type Page } from "@playwright/test";
import { installRecordingJourneyBridge } from "./recording-journey-bridge";

const hash = "a".repeat(64);
async function install(page: Page) {
  await installRecordingJourneyBridge(page, "complete");
  await page.addInitScript(() => {
    const host = globalThis as unknown as {
      __TAURI_INTERNALS__: {
        invoke: (command: string, args?: unknown) => Promise<unknown>;
      };
    };
    const base = host.__TAURI_INTERNALS__.invoke;
    const state = {
      mode: "saved",
      calls: [] as unknown[],
      finish: undefined as (() => void) | undefined,
    };
    Object.assign(globalThis, { __timedExport: state });
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "history_catalog") {
        const catalog = (await base(command, args)) as {
          sessions: Record<string, unknown>[];
        };
        const first = {
          ...catalog.sessions[0],
          speakerTranscriptAvailable: true,
        };
        return {
          ...catalog,
          sessions: [
            first,
            {
              ...first,
              sessionId: "restored-2",
              name: "second.mp3",
              outputPath: "C:\\Yap\\remote-jobs\\restored-2\\transcript.txt",
            },
          ],
        };
      }
      if (command === "history_speaker_transcript") {
        const { identity } = args as { identity: { sessionId: string } };
        return {
          sessionId: identity.sessionId,
          sourceResultSha256: "a".repeat(64),
          turns: [
            {
              turnId: "turn-000001",
              speakerId: "speaker-1",
              startMs: 17,
              endMs: 1900,
              text: "Café — 日本語",
              overlapGroupId: "overlap-1",
            },
            {
              turnId: "turn-000002",
              speakerId: null,
              startMs: 800,
              endMs: 2010,
              text: "Unknown speaker",
              overlapGroupId: "overlap-1",
            },
          ],
        };
      }
      if (command !== "export_speaker_transcript") return base(command, args);
      state.calls.push(args);
      if (state.mode === "cancelled") return { status: "cancelled" };
      if (state.mode === "failed")
        throw "The saved timed speaker transcript could not be verified. Refresh history and retry.";
      if (state.mode === "pending" || state.mode === "pendingFailure") {
        const fail = state.mode === "pendingFailure";
        await new Promise<void>((resolve) => {
          state.finish = resolve;
        });
        if (fail) throw "private first-source failure";
      }
      const identity = args as {
        sessionId: string;
        sourceResultSha256: string;
      };
      return {
        status: "saved",
        path: "C:\\Exports\\timed.json",
        sessionId: identity.sessionId,
        sourceResultSha256:
          state.mode === "wrongHash"
            ? "b".repeat(64)
            : identity.sourceResultSha256,
      };
    };
  });
}
async function mode(page: Page, value: string) {
  await page.evaluate((value) => {
    (
      globalThis as unknown as { __timedExport: { mode: string } }
    ).__timedExport.mode = value;
  }, value);
}
async function review(page: Page, name = "restored.mp3") {
  await page
    .getByRole("button", { name: `Review recording ${name}`, exact: true })
    .click();
  return page.getByRole("dialog", { name, exact: true });
}
async function start(page: Page) {
  await install(page);
  await page.goto("/");
  return review(page);
}
function exportButton(page: Page, name = "restored.mp3") {
  return page.getByRole("button", {
    name: `Export timed speaker transcript for ${name}`,
    exact: true,
  });
}

test("exports the exact saved timed speaker identity while preserving original text actions", async ({
  page,
}) => {
  const dialog = await start(page);
  await expect(
    dialog.getByText("Café — 日本語", { exact: true }),
  ).toBeVisible();
  await exportButton(page).click();
  await expect(
    page.getByText("Timed speaker transcript exported", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        (globalThis as unknown as { __timedExport: { calls: unknown[] } })
          .__timedExport.calls,
    ),
  ).toEqual([
    {
      outputPath: "C:\\Yap\\remote-jobs\\restored-1\\transcript.txt",
      sessionId: "restored-1",
      sourceResultSha256: hash,
    },
  ]);
  await expect(
    dialog.getByRole("button", {
      name: "Export original transcript for restored.mp3",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    dialog.getByText("Unknown speaker", { exact: true }).first(),
  ).toBeVisible();
});
for (const outcome of ["cancelled", "failed", "wrongHash"]) {
  test(`timed speaker export ${outcome} preserves source and permits explicit retry`, async ({
    page,
  }) => {
    const dialog = await start(page);
    await mode(page, outcome);
    const button = exportButton(page);
    await button.click();
    if (outcome === "cancelled")
      await expect(
        page.getByText("Timed speaker export cancelled", { exact: true }),
      ).toBeVisible();
    else
      await expect(dialog.getByRole("alert")).toContainText(
        outcome === "failed"
          ? "could not be verified"
          : "file may already have been saved",
      );
    await expect(
      page.getByText("Timed speaker transcript exported", { exact: true }),
    ).toHaveCount(0);
    await expect(
      dialog.getByText("Café — 日本語", { exact: true }),
    ).toBeVisible();
    await expect(button).toBeFocused();
    await mode(page, "saved");
    await button.click();
    await expect(
      page.getByText("Timed speaker transcript exported", { exact: true }),
    ).toBeVisible();
    await expect(dialog.getByRole("alert")).toHaveCount(0);
  });
}
for (const outcome of ["pending", "pendingFailure"]) {
  test(`changed selection hides late timed export ${outcome} feedback and prevents duplicate exports`, async ({
    page,
  }) => {
    await start(page);
    await mode(page, outcome);
    await exportButton(page).click();
    await expect(exportButton(page)).toBeDisabled();
    await page.keyboard.press("Escape");
    const second = await review(page, "second.mp3");
    await expect(exportButton(page, "second.mp3")).toBeDisabled();
    await page.evaluate(() =>
      (
        globalThis as unknown as { __timedExport: { finish: () => void } }
      ).__timedExport.finish(),
    );
    await expect(exportButton(page, "second.mp3")).toBeEnabled();
    await expect(
      page.getByText("Timed speaker transcript exported", { exact: true }),
    ).toHaveCount(0);
    await expect(second.getByRole("alert")).toHaveCount(0);
    expect(
      await page.evaluate(
        () =>
          (globalThis as unknown as { __timedExport: { calls: unknown[] } })
            .__timedExport.calls.length,
      ),
    ).toBe(1);
  });
}
test("timed export is keyboard accessible and readable at narrow width with reduced motion", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 700 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const dialog = await start(page);
  const button = exportButton(page);
  for (let i = 0; i < 20; i++) {
    if (await button.evaluate((node) => node === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  await expect(button).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("Timed speaker transcript exported", { exact: true }),
  ).toBeVisible();
  expect(
    await dialog
      .getByRole("group", { name: "Transcript actions" })
      .evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  if (process.env.YAP_CAPTURE_TIMED_EXPORT_EVIDENCE === "1") {
    await page.screenshot({
      path: "../docs/evidence/timed-speaker-export/2026-10-05/narrow.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({
      path: "../docs/evidence/timed-speaker-export/2026-10-05/wide.png",
      fullPage: true,
    });
  }
});
