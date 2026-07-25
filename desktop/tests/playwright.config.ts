import { defineConfig, devices } from "@playwright/test";
import {
  parsePlaywrightPort,
  parsePlaywrightServerReuse,
} from "./scripts/playwright-port.mjs";

const testPort = parsePlaywrightPort(process.env.YAP_PLAYWRIGHT_PORT);
const testUrl = `http://127.0.0.1:${testPort}`;
const reuseExistingServer = parsePlaywrightServerReuse(
  process.env.YAP_PLAYWRIGHT_REUSE_SERVER,
);

export default defineConfig({
  expect: {
    timeout: 5_000,
  },
  globalSetup: "./scripts/warm-playwright-application.mjs",
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  outputDir: "./results/playwright",
  testDir: "./e2e",
  timeout: 20_000,
  workers: 1,
  use: {
    baseURL: testUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${testPort} --strictPort`,
    reuseExistingServer,
    timeout: 60_000,
    url: testUrl,
  },
});
