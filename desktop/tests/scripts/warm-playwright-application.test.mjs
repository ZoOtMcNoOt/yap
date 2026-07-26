import { describe, expect, test, vi } from "vitest";

import { warmPlaywrightApplication } from "./warm-playwright-application.mjs";

describe("Playwright application warmup", () => {
  test("waits for the application to mount", async () => {
    const waitFor = vi.fn().mockResolvedValue(undefined);
    const first = vi.fn(() => ({ waitFor }));
    const locator = vi.fn(() => ({ first }));
    const goto = vi.fn().mockResolvedValue(undefined);

    await warmPlaywrightApplication({ goto, locator }, "http://127.0.0.1:49152");

    expect(goto).toHaveBeenCalledWith("http://127.0.0.1:49152", {
      timeout: 60_000,
      waitUntil: "domcontentloaded",
    });
    expect(locator).toHaveBeenCalledWith("#root > *");
    expect(first).toHaveBeenCalledOnce();
    expect(waitFor).toHaveBeenCalledWith({
      state: "visible",
      timeout: 60_000,
    });
  });

  test("fails closed when the application never mounts", async () => {
    const mountError = new Error("application did not mount");
    const page = {
      goto: vi.fn().mockResolvedValue(undefined),
      locator: vi.fn(() => ({
        first: () => ({
          waitFor: vi.fn().mockRejectedValue(mountError),
        }),
      })),
    };

    await expect(
      warmPlaywrightApplication(page, "http://127.0.0.1:49152"),
    ).rejects.toBe(mountError);
  });
});
