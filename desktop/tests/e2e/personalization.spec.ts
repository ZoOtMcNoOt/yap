import { expect, test, type Page } from "@playwright/test";
import { installPersonalizationBridge } from "./personalization-bridge";

test("shared scopes isolate records and team editing while organization terms remain read-only", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { count: 1, shared: true });
  await open(page);
  const selector = page.getByRole("combobox", {
    name: "Terminology scope",
    exact: true,
  });
  await expect(
    page.getByRole("list", { name: "Personal terms" }),
  ).toContainText("Term 1");
  await selector.selectOption("team:clinical");
  const list = page.getByRole("list", { name: "Team terms" });
  await expect(list).toContainText("Clinical Yap");
  await expect(list).not.toContainText("Term 1");
  await add(page, "Team spelling");
  await expect(selector).toBeDisabled();
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(list).toContainText("Team spelling");
  await page
    .getByRole("button", { name: "Edit Team spelling", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Preferred spelling", exact: true })
    .fill("Team revised");
  await mode(page, "conflict");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("changed elsewhere");
  await page
    .getByRole("button", { name: "Compare latest version", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Apply my draft to latest version",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page
    .getByRole("button", { name: "Delete Team revised", exact: true })
    .click();
  await expect(page.getByRole("alertdialog")).toContainText(
    "Delete team term?",
  );
  await page.getByRole("button", { name: "Delete term", exact: true }).click();
  await expect(list).not.toContainText("Team revised");
  await selector.selectOption("organization");
  await expect(
    page.getByText(
      "You can view these terms. Your organization controls who can edit them.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add term", exact: true }),
  ).toHaveCount(0);
  await selector.selectOption("personal");
  await expect(
    page.getByRole("list", { name: "Personal terms" }),
  ).toContainText("Term 1");
  const calls = await page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __personalization: { calls: Record<string, unknown>[] };
        }
      ).__personalization.calls,
  );
  expect(
    calls
      .filter((c) => ["create", "edit", "delete"].includes(String(c.action)))
      .every((c) => c.scopeId === "team:clinical"),
  ).toBe(true);
});

test("team readers can inspect terms and switch language without mutation controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 520 });
  await installPersonalizationBridge(page, {
    shared: true,
    teamCanManage: false,
  });
  await open(page);
  await page
    .getByRole("combobox", { name: "Terminology scope", exact: true })
    .selectOption("team:clinical");
  await expect(page.getByRole("list", { name: "Team terms" })).toContainText(
    "Clinical Yap",
  );
  await expect(
    page.getByRole("button", { name: "Edit Clinical Yap", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Delete Clinical Yap", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Add term", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "Term language", exact: true })
    .selectOption("und");
  await expect(
    page.getByText("No team terms yet", { exact: true }),
  ).toBeVisible();
  const bounds = await page
    .getByRole("combobox", { name: "Terminology scope", exact: true })
    .boundingBox();
  expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(720);
});

test("organization administrators can save terms in the explicitly selected organization", async ({
  page,
}) => {
  await installPersonalizationBridge(page, {
    shared: true,
    organizationCanManage: true,
  });
  await open(page);
  await page
    .getByRole("combobox", { name: "Terminology scope", exact: true })
    .selectOption("organization");
  await add(page, "Organization spelling");
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(
    page.getByRole("list", { name: "Organization terms" }),
  ).toContainText("Organization spelling");
  await page
    .getByRole("combobox", { name: "Terminology scope", exact: true })
    .selectOption("team:clinical");
  await expect(
    page.getByRole("list", { name: "Team terms" }),
  ).not.toContainText("Organization spelling");
});

test("revoked shared management preserves a draft and prevents retargeting or saving", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { shared: true });
  await open(page);
  const selector = page.getByRole("combobox", {
    name: "Terminology scope",
    exact: true,
  });
  await selector.selectOption("team:clinical");
  await page
    .getByRole("button", { name: "Edit Clinical Yap", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Preferred spelling", exact: true })
    .fill("Private team draft");
  await page.evaluate(() => {
    const fixture = (
      globalThis as unknown as {
        __personalization: {
          scopes: { scopeId: string; canManage: boolean }[];
        };
      }
    ).__personalization;
    fixture.scopes.find((s) => s.scopeId === "team:clinical")!.canManage =
      false;
  });
  await page
    .getByRole("button", { name: "Refresh terms", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("Private team draft");
  await expect(
    page.getByRole("button", { name: "Save changes", exact: true }),
  ).toBeDisabled();
  await expect(selector).toBeDisabled();
  await page.getByRole("button", { name: "Cancel edit", exact: true }).click();
  await selector.selectOption("personal");
  await expect(
    page.getByText("No personal terms yet", { exact: true }),
  ).toBeVisible();
});

test("shared scope discovery failure is recoverable and sign-out discards a delayed shared result", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { shared: true });
  await open(page);
  await mode(page, "discoveryFailure");
  await page
    .getByRole("button", { name: "Refresh terms", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Could not reach terminology",
  );
  await mode(page, "ok");
  await page
    .getByRole("button", { name: "Refresh terms", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Terminology scope", exact: true })
    .selectOption("team:clinical");
  await add(page, "Delayed shared spelling");
  await mode(page, "pending");
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("sign_in_required"),
  );
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() =>
    (
      globalThis as unknown as { __personalization: { finish: () => void } }
    ).__personalization.finish(),
  );
  await expect(page.getByRole("list", { name: "Team terms" })).toHaveCount(0);
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("ready"),
  );
  await expect(
    page.getByRole("combobox", { name: "Terminology scope", exact: true }),
  ).toHaveValue("personal");
  await expect(
    page.getByText("No personal terms yet", { exact: true }),
  ).toBeVisible();
});

test("a draft from another native connection cannot be saved into the new account or scope", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { shared: true });
  await open(page);
  await page
    .getByRole("combobox", { name: "Terminology scope", exact: true })
    .selectOption("team:clinical");
  await add(page, "Previous connection draft");
  await page.evaluate(() => {
    (
      globalThis as unknown as {
        __personalization: { authorityRevision: string };
      }
    ).__personalization.authorityRevision = "2";
  });
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your sign-in or server changed",
  );
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("Previous connection draft");
  await page
    .getByRole("button", { name: "Refresh terms", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText(
    "previous draft was cleared",
  );
  await expect(
    page.getByRole("list", { name: "Team terms" }),
  ).not.toContainText("Previous connection draft");
});

test("revoked shared visibility keeps a cancellable draft and requires an explicit new scope", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { shared: true });
  await open(page);
  const selector = page.getByRole("combobox", {
    name: "Terminology scope",
    exact: true,
  });
  await selector.selectOption("team:clinical");
  await add(page, "Revoked draft");
  await page.evaluate(() => {
    const fixture = (
      globalThis as unknown as {
        __personalization: { scopes: { scopeId: string }[] };
      }
    ).__personalization;
    fixture.scopes = fixture.scopes.filter(
      (s) => s.scopeId !== "team:clinical",
    );
  });
  await page
    .getByRole("button", { name: "Refresh terms", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Your access to this scope changed",
  );
  await expect(
    page.getByRole("button", { name: "Save term", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("list", { name: "Team terms" })).toHaveCount(0);
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("Revoked draft");
  await page.getByRole("button", { name: "Cancel edit", exact: true }).click();
  await selector.selectOption("personal");
  await expect(
    page.getByText("No personal terms yet", { exact: true }),
  ).toBeVisible();
});

async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page
    .getByRole("button", { name: "Personalization", exact: true })
    .click();
}
async function mode(page: Page, value: string) {
  await page.evaluate((value) => {
    (
      globalThis as unknown as { __personalization: { mode: string } }
    ).__personalization.mode = value;
  }, value);
}
async function add(page: Page, spelling = "Yap") {
  await page.getByRole("button", { name: "Add term", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("textbox", { name: "Preferred spelling", exact: true })
    .fill(spelling);
  await page
    .getByRole("textbox", { name: "Heard as", exact: true })
    .fill("yapp\nyap app");
}

test("personal terms can be created, edited and explicitly deleted without correction models", async ({
  page,
}) => {
  await installPersonalizationBridge(page);
  await open(page);
  await expect(
    page.getByText("No personal terms yet", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Terms can be saved now; transcript correction is not enabled on this server yet.",
    ),
  ).toBeVisible();
  await add(page);
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(
    page.getByRole("list", { name: "Personal terms" }),
  ).toContainText("Yap");
  await expect(
    page.getByRole("button", { name: "Add term", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Edit Yap", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Preferred spelling", exact: true })
    .fill("YAP");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Edit YAP", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete YAP", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Delete YAP", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Delete YAP", exact: true }).click();
  await page.getByRole("button", { name: "Delete term", exact: true }).click();
  await expect(
    page.getByText("No personal terms yet", { exact: true }),
  ).toBeVisible();
});

test("creation retries retain the draft and mutation identity after a lost committed response", async ({
  page,
}) => {
  await installPersonalizationBridge(page);
  await open(page);
  await add(page);
  await mode(page, "lostResponse");
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Your draft is kept");
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("Yap");
  await page.getByRole("button", { name: "System", exact: true }).click();
  await page
    .getByRole("button", { name: "Personalization", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Heard as", exact: true }),
  ).toHaveValue("yapp\nyap app");
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(
    page.getByRole("list", { name: "Personal terms" }).getByRole("listitem"),
  ).toHaveCount(1);
  const calls = await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { calls: Record<string, unknown>[] };
      }
    ).__personalization.calls.filter((c) => c.action === "create"),
  );
  expect(calls).toHaveLength(2);
  expect(calls[0]?.mutationId).toBe(calls[1]?.mutationId);
  expect(Object.keys(calls[0]!).sort()).toEqual([
    "action",
    "canonicalForm",
    "locale",
    "mutationId",
    "scopeId",
    "sensitivity",
    "variants",
  ]);
});

test("conflicting edits keep the draft and require explicit comparison before saving", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { count: 1 });
  await open(page);
  await page.getByRole("button", { name: "Edit Term 1", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Preferred spelling", exact: true })
    .fill("My spelling");
  await mode(page, "conflict");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("changed elsewhere");
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("My spelling");
  await expect(
    page.getByRole("button", { name: "Save changes", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Compare latest version", exact: true })
    .click();
  await expect(
    page.getByText("Latest saved spelling: Saved elsewhere", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Apply my draft to latest version",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Edit My spelling", exact: true }),
  ).toBeVisible();
});

test("paged terminology remains bounded and keyboard controls fit a narrow window", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 520 });
  await installPersonalizationBridge(page, { count: 12 });
  await open(page);
  await expect(
    page.getByRole("list", { name: "Personal terms" }).getByRole("listitem"),
  ).toHaveCount(10);
  await page
    .getByRole("button", { name: "Load more terms", exact: true })
    .click();
  await expect(
    page.getByRole("list", { name: "Personal terms" }).getByRole("listitem"),
  ).toHaveCount(12);
  await page.getByRole("button", { name: "Add term", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toBeFocused();
  const bounds = await page
    .getByRole("textbox", { name: "Preferred spelling", exact: true })
    .boundingBox();
  expect(bounds?.x).toBeGreaterThanOrEqual(0);
  expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(720);
});

test("unconfigured and signed-out servers never load or mutate personal terms", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { capability: false });
  await open(page);
  await expect(
    page.getByText("Terminology is not enabled on this server.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add term", exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("sign_in_required"),
  );
  await expect(
    page.getByText(
      "Sign in to your organization in System settings to manage your terms.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        (globalThis as unknown as { __personalization: { calls: unknown[] } })
          .__personalization.calls.length,
    ),
  ).toBe(0);
});

test("a pending save survives Settings closure without duplicate submission", async ({
  page,
}) => {
  await installPersonalizationBridge(page);
  await open(page);
  await add(page);
  await mode(page, "pending");
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Saving…", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "Settings", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page
    .getByRole("button", { name: "Personalization", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Saving…", exact: true }),
  ).toBeDisabled();
  await page.evaluate(() =>
    (
      globalThis as unknown as { __personalization: { finish: () => void } }
    ).__personalization.finish(),
  );
  await expect(
    page.getByRole("button", { name: "Edit Yap", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        (
          globalThis as unknown as {
            __personalization: { calls: Record<string, unknown>[] };
          }
        ).__personalization.calls.filter((c) => c.action === "create").length,
    ),
  ).toBe(1);
});

test("a successful write with failed reload reports the saved outcome and refresh recovery", async ({
  page,
}) => {
  await installPersonalizationBridge(page);
  await open(page);
  await add(page);
  await mode(page, "reloadFails");
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Term saved, but the list could not refresh",
  );
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveCount(0);
  await mode(page, "ok");
  await page
    .getByRole("button", { name: "Refresh terms", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Edit Yap", exact: true }),
  ).toBeVisible();
});

test("offline recovery retains a draft while sign-out clears personal data", async ({
  page,
}) => {
  await installPersonalizationBridge(page);
  await open(page);
  await add(page, "Private draft");
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("offline"),
  );
  await expect(
    page.getByText("Your draft is kept for when the connection returns.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("ready"),
  );
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("Private draft");
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("sign_in_required"),
  );
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __personalization: { setConnection: (s: string) => void };
      }
    ).__personalization.setConnection("ready"),
  );
  await expect(
    page.getByRole("button", { name: "Add term", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add term", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Preferred spelling", exact: true }),
  ).toHaveValue("");
});

test("term language defaults to the loaded primary preference and stays explicit during editing", async ({
  page,
}) => {
  await installPersonalizationBridge(page, { primaryLocale: "de-DE" });
  await open(page);
  await expect(
    page.getByRole("combobox", { name: "Term language", exact: true }),
  ).toHaveValue("de-DE");
  await add(page, "Projekt");
  await expect(
    page.getByRole("combobox", { name: "Term language", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Save term", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Edit Projekt", exact: true }),
  ).toBeVisible();
  const calls = await page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __personalization: { calls: Record<string, unknown>[] };
        }
      ).__personalization.calls,
  );
  expect(calls.find((c) => c.action === "create")?.locale).toBe("de-DE");
});
