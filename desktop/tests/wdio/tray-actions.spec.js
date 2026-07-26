import { gracefullyExitWdioApp } from "./graceful-wdio-app-exit.js";

describe("Yap shared tray dispatcher", () => {
  it("restores the hidden main window through the production tray action", async () => {
    await browser.tauri.switchWindow("main");
    await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|close", { label: "main" }));
    await browser.waitUntil(async () => !await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_visible", { label: "main" })), {
      interval: 50,
      timeout: 5_000,
      timeoutMsg: "main window did not hide before the tray restore probe",
    });

    await browser.tauri.execute(({ core }) =>
      core.invoke("wdio_dispatch_tray_action", { action: "show_app" }));
    await browser.waitUntil(async () => browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_visible", { label: "main" })), {
      interval: 50,
      timeout: 5_000,
      timeoutMsg: "shared tray dispatcher did not restore the main window",
    });

    const denied = await browser.tauri.execute(async ({ core }) => {
      try {
        await core.invoke("wdio_dispatch_tray_action", { action: "start_dictating" });
        return "";
      } catch (error) {
        return String(error);
      }
    });
    expect(denied).toContain("only the restore and quit tray actions");
  });

  it("quits the app through the production tray action", async () => {
    const { bridgeClosedDuringQuit } = await gracefullyExitWdioApp(browser);
    if (bridgeClosedDuringQuit) {
      console.info("Tray quit terminated the app before the WDIO bridge returned.");
    }
  });
});
