import { expect, test } from "@playwright/test";
import { installCorrectionJourneyBridge } from "./correction-journey-bridge";
import { installKnowledgeJourneyBridge } from "./knowledge-journey-bridge";

for (const command of ["start_librarian_query", "start_transcript_correction"]) {
  test(`${command} exposes cancellation once native admission supplies a request identity`, async ({ page }) => {
    if (command === "start_librarian_query") await installKnowledgeJourneyBridge(page);
    else await installCorrectionJourneyBridge(page);
    await page.addInitScript((command) => {
      const host = globalThis as unknown as { __TAURI_INTERNALS__: { invoke: (command: string, args?: unknown) => Promise<unknown> } };
      const invoke = host.__TAURI_INTERNALS__.invoke;
      let release!: () => void;
      const admission = new Promise<void>((resolve) => { release = resolve; });
      Object.assign(globalThis, { __pendingAdmission: { release } });
      host.__TAURI_INTERNALS__.invoke = async (requested, args) => {
        if (requested === command) await admission;
        return invoke(requested, args);
      };
    }, command);
    await page.goto("/");
    if (command === "start_librarian_query") {
      await page.getByRole("button", { name: "Knowledge", exact: true }).click();
      await page.getByRole("textbox", { name: "What reviewed information are you looking for?" }).fill("launch");
      await page.getByRole("button", { name: "Search knowledge", exact: true }).click();
    } else {
      await page.getByRole("button", { name: "Review recording planning.mp3", exact: true }).click();
      await page.getByRole("button", { name: "Review corrections", exact: true }).click();
      await page.getByRole("button", { name: "Correct transcript", exact: true }).click();
    }
    const cancel = page.getByRole("button", { name: "Cancel", exact: true });
    await expect(cancel).toBeDisabled();
    await expect(cancel).toHaveAttribute("title", "Waiting for the server to accept this request.");
    await page.evaluate(() => (globalThis as unknown as { __pendingAdmission: { release: () => void } }).__pendingAdmission.release());
    await expect(cancel).toBeEnabled();
    await cancel.click();
    await expect(cancel).toHaveCount(0);
    await expect(page.getByRole("button", { name: command === "start_librarian_query" ? "Search knowledge" : "Correct transcript", exact: true })).toBeEnabled();
  });
}
