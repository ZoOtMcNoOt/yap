import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

const scriptsDirectory = path.dirname(fileURLToPath(import.meta.url));
const playwrightConfigPath = path.resolve(
  scriptsDirectory,
  "..",
  "playwright.config.ts",
);

describe("Playwright web server", () => {
  test("warms the development frontend before one test worker starts", async () => {
    const configSource = await readFile(playwrightConfigPath, "utf8");

    expect(configSource).toContain(
      'globalSetup: "./scripts/warm-playwright-application.mjs"',
    );
    expect(configSource).toContain("pnpm dev --host 127.0.0.1");
    expect(configSource).toContain("workers: 1");
    expect(configSource).not.toContain("pnpm build && pnpm preview");
  });
});
