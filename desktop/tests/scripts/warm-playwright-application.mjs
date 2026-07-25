import { chromium } from "@playwright/test";

const warmupTimeoutMs = 60_000;

export async function warmPlaywrightApplication(page, baseURL) {
  await page.goto(baseURL, {
    timeout: warmupTimeoutMs,
    waitUntil: "domcontentloaded",
  });
  await page.locator("#root > *").first().waitFor({
    state: "visible",
    timeout: warmupTimeoutMs,
  });
}

export default async function warmPlaywrightApplicationBeforeTests(config) {
  const baseURL = config.projects[0]?.use?.baseURL;
  if (typeof baseURL !== "string") {
    throw new Error("Playwright application warmup requires a project baseURL.");
  }

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await warmPlaywrightApplication(page, baseURL);
  } finally {
    await browser.close();
  }
}
