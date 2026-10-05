import { expect, test, type Page } from "@playwright/test";
import {
  installKnowledgeJourneyBridge,
  launchEvidenceText,
} from "./knowledge-journey-bridge";
import { journeyTranscript } from "./recording-journey-bridge";

async function setTaskStatus(page: Page, task: string, status: string) {
  await page.evaluate(
    ({ task, status }) =>
      (
        globalThis as unknown as {
          __knowledgeJourney: {
            setStatus: (task: string, status: string) => void;
          };
        }
      ).__knowledgeJourney.setStatus(task, status),
    { task, status },
  );
}

async function knowledgeMutations(page: Page) {
  return page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __knowledgeJourney: {
            mutations: Array<{ command: string; args: unknown }>;
          };
        }
      ).__knowledgeJourney.mutations,
  );
}

for (const task of [
  {
    tab: "Search sources",
    field: "What reviewed information are you looking for?",
    button: "Search knowledge",
    command: "librarian_query",
    result: "Permission-safe evidence is ready.",
  },
  {
    tab: "Ask a question",
    field: "What do you want to know?",
    button: "Ask Analyst",
    command: "analyst_answer",
    result: "A permission-safe cited answer is ready.",
  },
  {
    tab: "Review proposals",
    field: "What should the reviewed proposals help coordinate?",
    button: "Build proposal bundle",
    command: "coordinator_bundle",
    result: "A noncanonical proposal bundle is ready for review.",
  },
  {
    tab: "Review conflicts",
    field: "What should Auditor review?",
    button: "Review knowledge",
    command: "auditor_report",
    result: "A noncanonical source-cited report is ready for review.",
  },
]) {
  test(`${task.tab} clears private data on ready-to-ready authority changes`, async ({
    page,
  }) => {
    await installKnowledgeJourneyBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("tab", { name: task.tab, exact: true }).click();
    const input = page.getByRole("textbox", { name: task.field, exact: true });
    await input.fill("private launch review");
    await page.getByRole("button", { name: task.button, exact: true }).click();
    await setTaskStatus(page, task.command, "complete");
    await expect(page.getByText(task.result, { exact: true })).toBeVisible();
    const recheck = (revision: string) =>
      page.evaluate(
        (value) =>
          (
            globalThis as unknown as {
              __knowledgeJourney: {
                recheckConnection: (revision: string) => void;
              };
            }
          ).__knowledgeJourney.recheckConnection(value),
        revision,
      );
    await recheck("1");
    await expect(input).toHaveValue("private launch review");
    await expect(page.getByText(task.result, { exact: true })).toBeVisible();
    await recheck("2");
    await expect(input).toHaveValue("", { timeout: 3000 });
    await expect(page.getByText(task.result, { exact: true })).toHaveCount(0);
    await expect(page.locator("blockquote:visible")).toHaveCount(0);
    expect(
      (await knowledgeMutations(page)).filter(({ command }) =>
        command.startsWith("start_"),
      ),
    ).toHaveLength(1);
  });
  test(`${task.tab} waits for old submission cleanup and rejects its late result after an authority change`, async ({
    page,
  }) => {
    await installKnowledgeJourneyBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("tab", { name: task.tab, exact: true }).click();
    const input = page.getByRole("textbox", { name: task.field, exact: true });
    const submit = page.getByRole("button", { name: task.button, exact: true });
    const control = (method: string, value: string) =>
      page.evaluate(
        ({ method, value }) =>
          (
            globalThis as unknown as {
              __knowledgeJourney: Record<string, (value: string) => void>;
            }
          ).__knowledgeJourney[method](value),
        { method, value },
      );
    await control("delayNextSubmission", task.command);
    await input.fill("private old owner draft");
    await submit.click();
    await expect
      .poll(async () => (await knowledgeMutations(page)).length)
      .toBe(1);
    await control("recheckConnection", "2");
    await expect(input).toHaveValue("");
    await expect(input).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeDisabled();
    await control("releaseSubmission", task.command);
    await expect(input).toBeEnabled();
    await expect(submit).toBeDisabled();
    await input.fill("new owner request");
    await expect(submit).toBeEnabled();
    await expect(page.getByText(task.result, { exact: true })).toHaveCount(0);
    const mutations = await knowledgeMutations(page);
    expect(mutations.map(({ command }) => command)).toEqual([
      `start_${task.command}`,
      `cancel_${task.command}`,
    ]);
    await submit.click();
    await setTaskStatus(page, task.command, "complete");
    await expect(page.getByText(task.result, { exact: true })).toBeVisible();
    const starts = (await knowledgeMutations(page)).filter(({ command }) =>
      command.startsWith("start_"),
    );
    expect(starts).toHaveLength(2);
    expect(
      starts.map(
        ({ args }) => (args as { authorityRevision: string }).authorityRevision,
      ),
    ).toEqual(["1", "2"]);
  });

  test(`${task.tab} keeps cancellation pending through an authority change`, async ({
    page,
  }) => {
    await installKnowledgeJourneyBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("tab", { name: task.tab, exact: true }).click();
    const input = page.getByRole("textbox", { name: task.field, exact: true });
    const control = (method: string, value: string) =>
      page.evaluate(
        ({ method, value }) =>
          (
            globalThis as unknown as {
              __knowledgeJourney: Record<string, (value: string) => void>;
            }
          ).__knowledgeJourney[method](value),
        { method, value },
      );
    await input.fill("private cancelled request");
    await page.getByRole("button", { name: task.button, exact: true }).click();
    await control("delayNextCancellation", task.command);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await control("recheckConnection", "2");
    await expect(input).toHaveValue("");
    await expect(input).toBeDisabled({ timeout: 1000 });
    await expect(
      page.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeDisabled();
    await control("releaseCancellation", task.command);
    await expect(input).toBeEnabled();
    await expect(page.getByText(task.result, { exact: true })).toHaveCount(0);
    expect(
      (await knowledgeMutations(page)).filter(({ command }) =>
        command.startsWith("start_"),
      ),
    ).toHaveLength(1);
    await input.fill("new owner request");
    await expect(
      page.getByRole("button", { name: task.button, exact: true }),
    ).toBeEnabled();
  });

  test(`${task.tab} retains offline drafts for the same owner and clears them when that owner changes`, async ({
    page,
  }) => {
    await installKnowledgeJourneyBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("tab", { name: task.tab, exact: true }).click();
    const input = page.getByRole("textbox", { name: task.field, exact: true });
    const control = (method: string, value: string | boolean) =>
      page.evaluate(
        ({ method, value }) =>
          (
            globalThis as unknown as {
              __knowledgeJourney: Record<
                string,
                (value: string | boolean) => void
              >;
            }
          ).__knowledgeJourney[method](value),
        { method, value },
      );
    await input.fill("private current owner draft");
    await control("setAvailable", false);
    await expect(input).toHaveValue("private current owner draft");
    await expect(
      page.getByRole("button", { name: task.button, exact: true }),
    ).toBeDisabled();
    await input.fill("offline current owner draft");
    await control("recheckConnection", "1");
    await expect(input).toHaveValue("offline current owner draft");
    await control("recheckConnection", "2");
    await expect(input).toHaveValue("");
    await input.fill("offline new owner draft");
    await control("setAvailable", true);
    await expect(input).toHaveValue("offline new owner draft");
    await expect(
      page.getByRole("button", { name: task.button, exact: true }),
    ).toBeEnabled();
    expect(await knowledgeMutations(page)).toHaveLength(0);
  });
}

for (const task of [
  {
    tab: "Ask a question",
    field: "What do you want to know?",
    button: "Ask Analyst",
    command: "analyst_answer",
    argument: "question",
    cancelled: "Cited-answer request cancelled.",
    result: "A permission-safe cited answer is ready.",
  },
  {
    tab: "Review proposals",
    field: "What should the reviewed proposals help coordinate?",
    button: "Build proposal bundle",
    command: "coordinator_bundle",
    argument: "objective",
    cancelled: "Coordination-bundle request cancelled.",
    result: "A noncanonical proposal bundle is ready for review.",
  },
]) {
  test(`${task.tab} ignores a stale poll after cancellation and retries the submitted draft`, async ({
    page,
  }) => {
    await installKnowledgeJourneyBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("tab", { name: task.tab, exact: true }).click();
    const input = page.getByRole("textbox", { name: task.field, exact: true });
    const control = (method: string) =>
      page.evaluate(
        ({ method, task }) =>
          (
            globalThis as unknown as {
              __knowledgeJourney: Record<
                string,
                (task: string) => boolean | void
              >;
            }
          ).__knowledgeJourney[method](task),
        { method, task: task.command },
      );
    await control("delayNextStatus");
    await input.fill("original reviewed launch request");
    await page.getByRole("button", { name: task.button, exact: true }).click();
    await setTaskStatus(page, task.command, "complete");
    await expect.poll(() => control("statusPending")).toBe(true);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByText(task.cancelled, { exact: true })).toBeVisible();
    await control("releaseStatus");
    await expect.poll(() => control("statusPending")).toBe(false);
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await expect(page.getByText(task.cancelled, { exact: true })).toBeVisible();
    await expect(page.getByText(task.result, { exact: true })).toHaveCount(0);
    await expect(page.locator("blockquote:visible")).toHaveCount(0);
    await input.fill("edited draft for a later request");
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await setTaskStatus(page, task.command, "complete");
    await expect(page.getByText(task.result, { exact: true })).toBeVisible();
    const starts = (await knowledgeMutations(page)).filter(
      ({ command }) => command === `start_${task.command}`,
    );
    expect(starts).toHaveLength(2);
    expect(
      starts.map(
        ({ args }) => (args as Record<string, unknown>)[task.argument],
      ),
    ).toEqual([
      "original reviewed launch request",
      "original reviewed launch request",
    ]);
  });
}

test("search completes across task switches and exposes exact citations behind source details", async ({
  page,
}) => {
  await installKnowledgeJourneyBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page
    .getByRole("textbox", {
      name: "What reviewed information are you looking for?",
    })
    .fill("launch approval");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Ask a question", exact: true }).click();
  await page
    .getByRole("textbox", { name: "What do you want to know?" })
    .fill("When was the launch approved?");
  await setTaskStatus(page, "librarian_query", "complete");
  await page.getByRole("tab", { name: "Search sources", exact: true }).click();
  const evidence = page.getByRole("region", {
    name: "Permission-safe knowledge evidence",
  });
  await expect(evidence.locator("blockquote")).toHaveText(launchEvidenceText);
  await expect(
    evidence.getByText("Source 1 · launch review", { exact: true }),
  ).toBeVisible();
  await expect(
    evidence.getByText("meetings/launch-review", { exact: true }),
  ).toBeHidden();
  await evidence.getByText("Source 1 details", { exact: true }).click();
  await expect(
    evidence.getByText("meetings/launch-review", { exact: true }),
  ).toBeVisible();
  await expect(evidence).toContainText(
    `characters 0–${launchEvidenceText.length}`,
  );
  await expect(
    page.getByRole("textbox", {
      name: "What reviewed information are you looking for?",
    }),
  ).toHaveValue("launch approval");
  expect(
    (await knowledgeMutations(page)).some(
      ({ command }) => command === "cancel_librarian_query",
    ),
  ).toBe(false);
  await page.getByRole("tab", { name: "Ask a question", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "What do you want to know?" }),
  ).toHaveValue("When was the launch approved?");
  await page.getByRole("button", { name: "Ask Analyst", exact: true }).click();
  await setTaskStatus(page, "analyst_answer", "complete");
  await expect(page.getByText("Cited answer", { exact: true })).toBeVisible();
  await expect(page.locator("blockquote:visible")).toHaveText(
    launchEvidenceText,
  );
});

test("cancellation, failure, absent evidence, and retry retain the search without exposing hidden matches", async ({
  page,
}) => {
  await installKnowledgeJourneyBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  const input = page.getByRole("textbox", {
    name: "What reviewed information are you looking for?",
  });
  await input.fill("launch approval");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await expect(
    page.getByText("Waiting for the shared knowledge route…", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByText("Knowledge query cancelled.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await setTaskStatus(page, "librarian_query", "failed");
  await expect(page.getByRole("alert")).toContainText(
    "The server could not complete this permission-safe query.",
  );
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await setTaskStatus(page, "librarian_query", "evidence-unavailable");
  await expect(
    page.getByText("No permission-safe evidence is available for that query.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(input).toHaveValue("launch approval");
  await expect(
    page.getByRole("region", { name: "Permission-safe knowledge evidence" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await setTaskStatus(page, "librarian_query", "complete");
  await expect(page.locator("blockquote:visible")).toHaveText(
    launchEvidenceText,
  );
  const mutations = await knowledgeMutations(page);
  expect(
    mutations.filter(({ command }) => command === "start_librarian_query"),
  ).toHaveLength(4);
  expect(mutations).toContainEqual({
    command: "start_librarian_query",
    args: {
      searchText: "launch approval",
      maximumResults: 3,
      expectedGenerationSha256: null,
      authorityRevision: "1",
    },
  });
});

test("proposal bundles and conflict reports remain review-required and preserve their sources", async ({
  page,
}) => {
  await installKnowledgeJourneyBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page
    .getByRole("tab", { name: "Review proposals", exact: true })
    .click();
  await page
    .getByRole("textbox", {
      name: "What should the reviewed proposals help coordinate?",
    })
    .fill("launch readiness");
  await page
    .getByRole("button", { name: "Build proposal bundle", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Review conflicts", exact: true })
    .click();
  await setTaskStatus(page, "coordinator_bundle", "complete");
  await page
    .getByRole("textbox", { name: "What should Auditor review?" })
    .fill("launch date");
  await page
    .getByRole("button", { name: "Review knowledge", exact: true })
    .click();
  await setTaskStatus(page, "auditor_report", "complete");
  await expect(
    page
      .getByRole("tabpanel", { name: "Review conflicts", exact: true })
      .getByText("Review required · noncanonical", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("blockquote:visible")).toHaveText([
    launchEvidenceText,
    "The reviewed launch was delayed.",
  ]);
  await expect(
    page.getByText(
      "This report does not publish, activate, schedule, or modify organization knowledge.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("tab", { name: "Review proposals", exact: true })
    .click();
  await expect(
    page.getByText("Selected proposal bundle", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("blockquote:visible")).toHaveText(
    launchEvidenceText,
  );
  await expect(
    page.getByText(
      "This bundle does not publish, activate, schedule, or modify organization knowledge.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(
    (await knowledgeMutations(page)).some(({ command }) =>
      command.startsWith("cancel_"),
    ),
  ).toBe(false);
});

test("a reviewed source leads to a learning prompt and a copyable proposal reference for human review", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await installKnowledgeJourneyBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page
    .getByRole("textbox", {
      name: "What reviewed information are you looking for?",
    })
    .fill("launch approval");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await setTaskStatus(page, "librarian_query", "complete");
  await page
    .getByRole("button", {
      name: "Create learning prompt from Source 1",
      exact: true,
    })
    .click();
  await page
    .getByRole("textbox", { name: "What should the prompt help you remember?" })
    .fill("launch timing");
  await page
    .getByRole("button", { name: "Create prompt", exact: true })
    .click();
  await page.getByRole("tab", { name: "Ask a question", exact: true }).click();
  await setTaskStatus(page, "student_question", "complete");
  await page.getByRole("tab", { name: "Search sources", exact: true }).click();
  await expect(
    page.getByText("When was the reviewed launch approved?", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Your reviewed answer", exact: true })
    .fill(launchEvidenceText);
  await page
    .getByRole("button", { name: "Propose for review", exact: true })
    .click();
  await setTaskStatus(page, "curator_proposal", "proposed");
  await expect(
    page.getByText("Proposal created", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Requires review", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Copy proposal reference", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe("proposal-1");
  const mutations = await knowledgeMutations(page);
  expect(mutations).toContainEqual({
    command: "start_student_question",
    args: {
      conversationConceptId: "meetings/launch-review",
      expectedGenerationSha256: "a".repeat(64),
      topic: "launch timing",
    },
  });
  expect(
    mutations.some(({ command }) => command === "cancel_student_question"),
  ).toBe(false);
  expect(
    mutations.some(({ command }) => /publish|activate/.test(command)),
  ).toBe(false);
});

for (const task of [
  {
    tab: "Search sources",
    field: "What reviewed information are you looking for?",
    button: "Search knowledge",
    command: "librarian_query",
  },
  {
    tab: "Ask a question",
    field: "What do you want to know?",
    button: "Ask Analyst",
    command: "analyst_answer",
  },
  {
    tab: "Review proposals",
    field: "What should the reviewed proposals help coordinate?",
    button: "Build proposal bundle",
    command: "coordinator_bundle",
  },
  {
    tab: "Review conflicts",
    field: "What should Auditor review?",
    button: "Review knowledge",
    command: "auditor_report",
  },
]) {
  test(`${task.tab} cancellation cannot resubmit the form`, async ({
    page,
  }) => {
    await installKnowledgeJourneyBridge(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Knowledge", exact: true }).click();
    await page.getByRole("tab", { name: task.tab, exact: true }).click();
    await page
      .getByRole("textbox", { name: task.field, exact: true })
      .fill("launch review");
    await page.getByRole("button", { name: task.button, exact: true }).click();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(
      page.getByRole("button", { name: task.button, exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByRole("textbox", { name: task.field, exact: true }),
    ).toHaveValue("launch review");
    const mutations = await knowledgeMutations(page);
    expect(
      mutations.filter(({ command }) => command === `start_${task.command}`),
    ).toHaveLength(1);
    expect(
      mutations.filter(({ command }) => command === `cancel_${task.command}`),
    ).toHaveLength(1);
  });
}

test("recording completion does not navigate away from a pending Knowledge task", async ({
  page,
}) => {
  await installKnowledgeJourneyBridge(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Transcribe a recording", exact: true })
    .click();
  await page.getByRole("button", { name: "Choose files", exact: true }).click();
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await page
    .getByRole("textbox", {
      name: "What reviewed information are you looking for?",
    })
    .fill("launch approval");
  await page
    .getByRole("button", { name: "Search knowledge", exact: true })
    .click();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __recordingJourney: { setState: (status: string) => void };
      }
    ).__recordingJourney.setState("complete"),
  );
  await expect(
    page.getByRole("button", { name: "Review transcript", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Knowledge", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("textbox", {
      name: "What reviewed information are you looking for?",
    }),
  ).toHaveValue("launch approval");
  expect(
    (await knowledgeMutations(page)).some(
      ({ command }) => command === "cancel_librarian_query",
    ),
  ).toBe(false);
  await page
    .getByRole("button", { name: "Review transcript", exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog", { name: "interview.mp3", exact: true })
      .locator("pre"),
  ).toHaveText(journeyTranscript);
  await expect
    .poll(
      async () =>
        (await knowledgeMutations(page)).filter(
          ({ command }) => command === "cancel_librarian_query",
        ).length,
    )
    .toBe(1);
});
