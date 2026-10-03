import { expect, test } from "@playwright/test";
import {
  installRecordingJourneyBridge,
  journeyTranscript,
} from "./recording-journey-bridge";

for (const format of ["flac", "ogg", "m4a", "mp4"]) {
  test(`${format.toUpperCase()} guidance and its queued result retain the selected file through History`, async ({
    page,
  }) => {
    await installRecordingJourneyBridge(page, undefined, `interview.${format}`);
    await page.goto("/");
    await page
      .getByRole("button", { name: "Transcribe a recording", exact: true })
      .click();
    await expect(
      page.getByText(
        "Supported files: WAV, MP3, FLAC, Ogg Vorbis and M4A/MP4 (AAC-LC).",
        { exact: false },
      ),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Choose files", exact: true })
      .click();
    await page
      .getByRole("button", { name: `Select interview.${format}`, exact: true })
      .click();
    await expect(
      page.getByText("Waiting in queue", { exact: true }),
    ).toBeVisible();
    await page.evaluate(() =>
      (
        globalThis as unknown as {
          __recordingJourney: { setState: (state: string) => void };
        }
      ).__recordingJourney.setState("complete"),
    );
    await page
      .getByRole("button", { name: "Review transcript", exact: true })
      .click();
    const review = page.getByRole("dialog", {
      name: `interview.${format}`,
      exact: true,
    });
    await expect(review.locator("pre")).toHaveText(journeyTranscript);
    await page.keyboard.press("Escape");
    await page
      .getByRole("button", { name: "Search past transcripts", exact: true })
      .click();
    await page
      .getByRole("textbox", { name: "Search past transcripts", exact: true })
      .fill("publish the reviewed");
    await expect(page.locator("tr[data-history-entry-row]")).toHaveCount(1);
    await page
      .getByRole("button", {
        name: `Review recording interview.${format}`,
        exact: true,
      })
      .click();
    await expect(
      page
        .getByRole("dialog", { name: `interview.${format}`, exact: true })
        .locator("pre"),
    ).toHaveText(journeyTranscript);
  });
}

test("a recording can be cancelled, re-added, retried after failure, and read/copied from History", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await installRecordingJourneyBridge(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Transcribe a recording", exact: true })
    .click();
  await page.getByRole("button", { name: "Choose files", exact: true }).click();
  await page
    .getByRole("button", { name: "Select interview.mp3", exact: true })
    .click();
  await expect(
    page.getByText("Waiting in queue", { exact: true }),
  ).toBeVisible();

  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __recordingJourney: { setState: (state: string) => void };
      }
    ).__recordingJourney.setState("server_processing"),
  );
  await expect(
    page.getByText("Your organization server is transcribing this recording.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Waiting for the organization server.", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Cancel recording", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Select interview.mp3", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("No audio queued")).toBeVisible();

  await page.getByRole("button", { name: "Choose files", exact: true }).click();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __recordingJourney: { setState: (state: string) => void };
      }
    ).__recordingJourney.setState("failed"),
  );
  await expect(
    page.getByText("The server stopped before producing a result."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry transcription" }).click();
  await expect(
    page.getByText("Waiting in queue", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __recordingJourney: { setState: (state: string) => void };
      }
    ).__recordingJourney.setState("complete"),
  );
  await page
    .getByRole("button", { name: "Review transcript", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "interview.mp3", exact: true }),
  ).toBeVisible();
  const review = page.getByRole("dialog", {
    name: "interview.mp3",
    exact: true,
  });
  await expect(review.locator("pre")).toHaveText(journeyTranscript);
  await review
    .getByRole("button", {
      name: "Copy transcript for interview.mp3",
      exact: true,
    })
    .click();
  await expect
    // Windows clipboard transport exposes CRLF; preserve all other content.
    .poll(() => page.evaluate(async () =>
      (await navigator.clipboard.readText()).replace(/\r\n/g, "\n"),
    ))
    .toBe(journeyTranscript);
  await review
    .getByRole("button", {
      name: "Open transcript for interview.mp3",
      exact: true,
    })
    .click();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Search past transcripts", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Search past transcripts", exact: true })
    .fill("publish the reviewed");
  await expect(page.locator("tr[data-history-entry-row]")).toHaveCount(1);

  const mutations = await page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __recordingJourney: {
            mutations: Array<{ command: string; args: unknown }>;
          };
        }
      ).__recordingJourney.mutations,
  );
  expect(
    mutations.filter(
      (entry) => entry.command === "recording_jobs_pick_imports",
    ),
  ).toHaveLength(2);
  expect(mutations).toContainEqual({
    command: "recording_job_cancel",
    args: { jobId: "journey-1" },
  });
  expect(mutations).toContainEqual({
    command: "recording_job_retry",
    args: { jobId: "journey-2" },
  });
  expect(mutations).toContainEqual({
    command: "open_app_path",
    args: { path: "C:\\Yap\\remote-jobs\\journey-2\\transcript.txt" },
  });
});

test("an unreadable saved transcript has a recoverable error instead of endless loading", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await installRecordingJourneyBridge(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Transcribe a recording", exact: true })
    .click();
  await page.getByRole("button", { name: "Choose files", exact: true }).click();
  await expect(
    page.getByText("Waiting in queue", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    const fixture = (
      globalThis as unknown as {
        __recordingJourney: {
          setReadFails: (fails: boolean) => void;
          setState: (state: string) => void;
        };
      }
    ).__recordingJourney;
    fixture.setReadFails(true);
    fixture.setState("complete");
  });
  await page
    .getByRole("button", { name: "Review transcript", exact: true })
    .click();
  const review = page.getByRole("dialog", {
    name: "interview.mp3",
    exact: true,
  });
  await expect(review.getByRole("alert")).toContainText(
    "This transcript could not be read.",
  );
  await expect(review.getByText("Loading transcript...")).toHaveCount(0);
  await expect(
    review.getByRole("button", {
      name: "Open transcript for interview.mp3",
      exact: true,
    }),
  ).toBeEnabled();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __recordingJourney: {
          setReadFails: (fails: boolean) => void;
        };
      }
    ).__recordingJourney.setReadFails(false),
  );
  await review
    .getByRole("button", { name: "Retry reading transcript" })
    .click();
  await expect(review.locator("pre")).toHaveText(journeyTranscript);
  await expect(review.getByRole("alert")).toHaveCount(0);
  await review
    .getByRole("button", {
      name: "Copy transcript for interview.mp3",
      exact: true,
    })
    .click();
  await expect
    .poll(() => page.evaluate(async () =>
      (await navigator.clipboard.readText()).replace(/\r\n/g, "\n"),
    ))
    .toBe(journeyTranscript);
  const commands = await page.evaluate(() =>
    (
      globalThis as unknown as {
        __recordingJourney: { mutations: Array<{ command: string }> };
      }
    ).__recordingJourney.mutations.map((entry) => entry.command),
  );
  expect(commands).not.toContain("recording_job_retry");
  expect(
    commands.filter((command) => command === "recording_jobs_pick_imports"),
  ).toHaveLength(1);
});

for (const status of ["queued_server", "failed", "complete"] as const) {
  test(`startup restores a ${status} recording from its native projection`, async ({
    page,
  }) => {
    await installRecordingJourneyBridge(page, status);
    await page.goto("/");
    if (status === "complete") {
      await page
        .getByRole("button", {
          name: "Review recording restored.mp3",
          exact: true,
        })
        .click();
      await expect(
        page
          .getByRole("dialog", { name: "restored.mp3", exact: true })
          .locator("pre"),
      ).toHaveText(journeyTranscript);
      await page.keyboard.press("Escape");
      await page.reload();
      await expect(
        page.getByRole("button", {
          name: "Review recording restored.mp3",
          exact: true,
        }),
      ).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    } else {
      await page
        .getByRole("button", { name: "Transcribe", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Select restored.mp3", exact: true })
        .click();
      if (status === "failed") {
        await expect(
          page.getByText("The server stopped before producing a result."),
        ).toBeVisible();
        await page
          .getByRole("button", { name: "Retry transcription", exact: true })
          .click();
      }
      await expect(
        page.getByText("Waiting in queue", { exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Remove file", exact: true })
        .click();
      await expect(
        page.getByText("No audio queued", { exact: true }),
      ).toBeVisible();
    }
  });
}

for (const format of ["m4a", "mp4"])
  test(`${format.toUpperCase()} preparation failure and retry fit a narrow window`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 900 });
    await installRecordingJourneyBridge(page, undefined, `interview.${format}`);
    await page.goto("/");
    await page
      .getByRole("button", { name: "Transcribe a recording", exact: true })
      .click();
    await expect(page.getByText(/Supported files:.*M4A\/MP4/)).toBeVisible();
    await page
      .getByRole("button", { name: "Choose files", exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await page
      .getByRole("button", { name: `Select interview.${format}`, exact: true })
      .click();
    await page.evaluate(() =>
      (globalThis as any).__recordingJourney.setState("preprocessing"),
    );
    await expect(
      page.locator('[data-slot="card-description"]').filter({ hasText: /^Preparing audio$/ }),
    ).toBeVisible();
    const title = page.locator('[data-slot="attachment-title"]').filter({ hasText: `interview.${format}` });
    expect(await title.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const queue = page.locator('[data-slot="scroll-area"]').filter({ has: title });
    expect(await queue.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThan(150);
    await page.evaluate(() =>
      (globalThis as any).__recordingJourney.setState("failed"),
    );
    await expect(
      page.getByRole("button", { name: "Retry transcription" }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "Retry transcription" }).click();
    await expect(
      page.getByRole("button", {
        name: `Select interview.${format}`,
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(360);
    await page
      .getByRole("button", { name: "Remove file", exact: true })
      .click();
    await expect(page.getByText("No audio queued")).toBeVisible();
  });
