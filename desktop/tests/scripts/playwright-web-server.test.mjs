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
  test("serves a separate bundled browser artifact before one test worker starts", async () => {
    const configSource = await readFile(playwrightConfigPath, "utf8");
    const buildSource = await readFile(
      path.resolve(scriptsDirectory, "..", "vite.playwright.config.ts"),
      "utf8",
    );
    const shippedSource = await readFile(
      path.resolve(scriptsDirectory, "..", "..", "vite.config.ts"),
      "utf8",
    );

    expect(configSource).toContain(
      'globalSetup: "./scripts/warm-playwright-application.mjs"',
    );
    expect(configSource).toContain(
      "vite build --config tests/vite.playwright.config.ts",
    );
    expect(configSource).toContain(
      "vite preview --config tests/vite.playwright.config.ts --host 127.0.0.1",
    );
    expect(configSource).toContain("workers: 1");
    expect(buildSource).toContain('outDir: "tests/results/playwright-app"');
    expect(buildSource).toContain('"import.meta.env.DEV": "true"');
    expect(buildSource).toContain("fixtures/archivist-ingestion-owner.html");
    expect(buildSource).toContain("fixtures/transcript-correction-owner.html");
    expect(shippedSource).not.toContain("fixtures/");
    expect(shippedSource).not.toContain('"import.meta.env.DEV"');
  });
});
