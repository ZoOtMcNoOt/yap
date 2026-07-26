import { execFile } from "node:child_process";
import { promisify } from "node:util";

import {
  assertRecordingRootEmpty,
  listRecordingArtifacts,
} from "./recording-artifact-ownership.js";
import {
  closeMainToTray,
  cycleIdleOverlay,
  pressOverlayFocusShortcutFromExternalWindow,
  recordingRoot,
  sampleWdioProcessTree,
  showIdleOverlay,
  withMainWindowRestored,
} from "./live-overlay-window-fixture.js";

const execFileAsync = promisify(execFile);
const nativeVirtualKey = {
  enter: 0x0D,
  space: 0x20,
  tab: 0x09,
};

describe("Yap live overlay window", () => {
  let overlayWasEnabled;

  beforeEach(async () => {
    assertRecordingRootEmpty(recordingRoot);
    await browser.tauri.switchWindow("main");
    const view = await browser.tauri.execute(({ core }) => core.invoke("live_status"));
    if (view.status !== "idle") {
      throw new Error(`WDIO test began with a non-idle live session: ${view.status}`);
    }
    overlayWasEnabled = view.visibility === "enabled";
  });

  afterEach(async () => {
    const errors = [];
    try {
      await browser.tauri.switchWindow("main");
      const view = await browser.tauri.execute(({ core }) => core.invoke("live_status"));
      if (view.status !== "idle") {
        await browser.tauri.execute(({ core }) => core.invoke("stop_live_session"));
        errors.push(new Error(`Test cleanup found and stopped live status ${view.status}.`));
      }
    } catch (error) {
      errors.push(new Error(`Live-state restoration failed: ${String(error)}`));
    }
    try {
      await browser.tauri.switchWindow("main");
      await browser.tauri.execute(
        ({ core }, enabled) => core.invoke("set_live_overlay_enabled", { enabled }),
        overlayWasEnabled,
      );
    } catch (error) {
      errors.push(new Error(`Overlay preference restoration failed: ${String(error)}`));
    }
    try {
      assertRecordingRootEmpty(recordingRoot);
    } catch (error) {
      errors.push(error);
    }
    if (errors.length > 0) throw new AggregateError(errors, "Live-overlay afterEach cleanup failed");
  });

  // Tauri does not expose a cross-platform skip-taskbar/Alt-Tab readback command here.
  // These probes cover the enforceable surface: exact visible size, unfocused/non-closable state,
  // close-request survival, and command denial from the overlay webview.
  it("opens as a compact system overlay and refuses direct close", async () => {
    await showIdleOverlay();

    await browser.tauri.switchWindow("live-overlay");
    const scaleFactor = await browser.tauri.execute(() => window.devicePixelRatio);
    if (!Number.isFinite(scaleFactor) || scaleFactor <= 0) {
      throw new Error(`Overlay reported invalid devicePixelRatio ${scaleFactor}.`);
    }
    await browser.tauri.switchWindow("main");

    const overlay = await browser.tauri.execute(async ({ core }) => {
      const label = "live-overlay";
      const inner = await core.invoke("plugin:window|inner_size", { label });
      const outer = await core.invoke("plugin:window|outer_size", { label });
      return {
        closable: await core.invoke("plugin:window|is_closable", { label }),
        focused: await core.invoke("plugin:window|is_focused", { label }),
        inner,
        outer,
        visible: await core.invoke("plugin:window|is_visible", { label }),
      };
    });
    const logicalInner = {
      height: overlay.inner.height / scaleFactor,
      width: overlay.inner.width / scaleFactor,
    };
    const logicalOuter = {
      height: overlay.outer.height / scaleFactor,
      width: overlay.outer.width / scaleFactor,
    };
    expect(overlay.visible).toBe(true);
    expect(overlay.focused).toBe(false);
    expect(overlay.closable).toBe(false);
    expect(logicalInner.width).toBeCloseTo(104, 1);
    expect(logicalInner.height).toBeCloseTo(40, 1);
    expect(logicalOuter.width).toBeCloseTo(104, 1);
    expect(logicalOuter.height).toBeCloseTo(40, 1);
    expect(listRecordingArtifacts(recordingRoot)).toEqual([]);
  });

  it("acquires overlay keyboard focus through the native global shortcut and activates child controls", async () => {
    await showIdleOverlay();
    const view = await browser.tauri.execute(({ core }) => core.invoke("live_status"));
    expect(view.overlayFocusHotkey).toBe("Ctrl+Shift+Alt+O");
    expect(await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_focused", { label: "live-overlay" }))).toBe(false);

    const nativeInput = await pressOverlayFocusShortcutFromExternalWindow();
    expect(nativeInput.foregroundProcessId).not.toBe(nativeInput.appProcessId);
    await browser.waitUntil(async () => browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_focused", { label: "live-overlay" })), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "native overlay focus shortcut did not focus the overlay window",
    });

    await browser.tauri.switchWindow("live-overlay");
    const focusedControl = await browser.tauri.execute(() => ({
      ariaLabel: document.activeElement?.getAttribute("aria-label"),
      role: document.activeElement?.getAttribute("role"),
      tagName: document.activeElement?.tagName,
    }));
    expect(
      focusedControl.role === "toolbar"
        || focusedControl.tagName === "BUTTON"
        || Boolean(focusedControl.ariaLabel),
    ).toBe(true);

    await browser.tauri.execute(() => {
      document.addEventListener("click", (event) => {
        const target = event.target instanceof Element
          ? event.target.closest('button[aria-label="Start dictating"]')
          : null;
        if (!target) return;
        document.documentElement.dataset.startKeyboardActivated = "true";
        event.preventDefault();
        event.stopImmediatePropagation();
      }, { capture: true });
    });
    await focusOverlayAction("Start dictating", nativeInput.appProcessId);
    await pressNativeOverlayKey(nativeVirtualKey.enter, nativeInput.appProcessId);
    await browser.waitUntil(async () => browser.tauri.execute(() =>
      document.documentElement.dataset.startKeyboardActivated === "true"), {
      interval: 25,
      timeout: 2_000,
      timeoutMsg: "Enter did not preserve native Start dictating activation",
    });

    await focusOverlayAction("Open scratch", nativeInput.appProcessId);
    await browser.tauri.switchWindow("live-overlay");
    await browser.tauri.execute(() => {
      const root = document.querySelector('[data-overlay-surface="expanded"]');
      if (!root) throw new Error("expanded overlay surface disappeared before pointer exit");
      root.dispatchEvent(new PointerEvent("pointerout", {
        bubbles: true,
        relatedTarget: document.body,
      }));
    });
    await browser.pause(300);
    const focusedAfterPointerExit = await browser.tauri.execute(() => ({
      ariaLabel: document.activeElement?.getAttribute("aria-label"),
      surface: document.querySelector("[data-overlay-surface]")
        ?.getAttribute("data-overlay-surface"),
    }));
    expect(focusedAfterPointerExit).toEqual({
      ariaLabel: "Open scratch",
      surface: "expanded",
    });
    await pressNativeOverlayKey(nativeVirtualKey.space, nativeInput.appProcessId);
    await browser.waitUntil(async () => browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_focused", { label: "main" })), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "Space did not activate Open scratch from the externally focused overlay",
    });
    await browser.tauri.switchWindow("live-overlay");
    await browser.waitUntil(async () => browser.tauri.execute(() =>
      document.querySelector('[data-overlay-surface="collapsed"]') !== null), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "overlay did not collapse after keyboard focus returned to the main window",
    });
    await browser.tauri.switchWindow("main");
  });

  it("reuses one native window whose bounds equal each visible island surface", async () => {
    await showIdleOverlay();
    await browser.tauri.switchWindow("live-overlay");

    const scaleFactor = await browser.tauri.execute(() => window.devicePixelRatio);
    if (!Number.isFinite(scaleFactor) || scaleFactor <= 0) {
      throw new Error(`Overlay reported invalid devicePixelRatio ${scaleFactor}.`);
    }

    const labelsBefore = await browser.tauri.listWindows();
    expect(labelsBefore.filter((label) => label === "live-overlay")).toHaveLength(1);
    await browser.tauri.execute(() => {
      const root = document.querySelector('[data-overlay-surface="collapsed"]');
      root.dispatchEvent(new PointerEvent("pointerover", {
        bubbles: true,
        clientX: 52,
        clientY: 20,
      }));
    });
    await browser.waitUntil(async () => browser.tauri.execute(() => {
      const root = document.querySelector('[data-overlay-surface="expanded"]');
      const island = document.querySelector('[data-testid="live-overlay-island"]');
      if (!root || !island) return false;
      const rootBox = root.getBoundingClientRect();
      const islandBox = island.getBoundingClientRect();
      return rootBox.width === islandBox.width
        && rootBox.height === islandBox.height;
    }), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "expanded webview did not converge to the visible island",
    });
    await browser.tauri.switchWindow("main");
    await browser.waitUntil(async () => browser.tauri.execute(async ({ core }, scale) => {
      const inner = await core.invoke("plugin:window|inner_size", { label: "live-overlay" });
      return Math.abs(inner.width / scale - 180) <= 0.5
        && Math.abs(inner.height / scale - 96) <= 0.5;
    }, scaleFactor), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "expanded native bounds did not converge to 180 by 96",
    });
    expect(await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_focused", { label: "live-overlay" }))).toBe(false);
    expect((await browser.tauri.listWindows()).filter((label) => label === "live-overlay")).toHaveLength(1);

    await browser.tauri.switchWindow("live-overlay");
    await browser.tauri.execute(() => {
      const root = document.querySelector('[data-overlay-surface="expanded"]');
      root.dispatchEvent(new PointerEvent("pointerout", {
        bubbles: true,
        relatedTarget: document.body,
      }));
    });
    await browser.waitUntil(async () => browser.tauri.execute(() => {
      const root = document.querySelector('[data-overlay-surface="collapsed"]');
      const island = document.querySelector('[data-testid="live-overlay-island"]');
      if (!root || !island) return false;
      const rootBox = root.getBoundingClientRect();
      const islandBox = island.getBoundingClientRect();
      return rootBox.width === islandBox.width
        && rootBox.height === islandBox.height;
    }), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "collapsed webview did not converge after the grace period",
    });
    await browser.tauri.switchWindow("main");
    await browser.waitUntil(async () => browser.tauri.execute(async ({ core }, scale) => {
      const inner = await core.invoke("plugin:window|inner_size", { label: "live-overlay" });
      return Math.abs(inner.width / scale - 104) <= 0.5
        && Math.abs(inner.height / scale - 40) <= 0.5;
    }, scaleFactor), {
      interval: 25,
      timeout: 5_000,
      timeoutMsg: "collapsed native bounds did not converge to 104 by 40",
    });
    expect(await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_focused", { label: "live-overlay" }))).toBe(false);
    expect(listRecordingArtifacts(recordingRoot)).toEqual([]);
  });

  it("keeps repeated expand-collapse resource growth bounded", async () => {
    await showIdleOverlay();
    await browser.tauri.switchWindow("live-overlay");
    await cycleIdleOverlay();
    await cycleIdleOverlay();
    const before = await sampleWdioProcessTree();

    for (let iteration = 0; iteration < 20; iteration += 1) {
      await cycleIdleOverlay();
    }
    await browser.pause(500);
    const after = await sampleWdioProcessTree();

    expect(after.processCount).toBeLessThanOrEqual(before.processCount + 2);
    expect(after.workingSetBytes - before.workingSetBytes).toBeLessThanOrEqual(96 * 1024 * 1024);
    expect(after.cpuSeconds - before.cpuSeconds).toBeLessThanOrEqual(10);
    expect((await browser.tauri.listWindows()).filter((label) => label === "live-overlay")).toHaveLength(1);
    expect(listRecordingArtifacts(recordingRoot)).toEqual([]);
  });

  it("does not expose raw renderer shortcut mutation commands", async () => {
    await browser.tauri.switchWindow("main");
    const original = await browser.tauri.execute(({ core }) => core.invoke("live_status"));

    for (const command of ["set_live_hotkey", "set_live_paste_hotkey"]) {
      const result = await browser.tauri.execute(async ({ core }, unavailableCommand) => {
        try {
          await core.invoke(unavailableCommand, { hotkey: "Ctrl+Shift+Alt+F11" });
          return { message: "", ok: true };
        } catch (error) {
          return { message: String(error), ok: false };
        }
      }, command);
      expect(result.ok).toBe(false);
      expect(result.message.toLowerCase()).toContain("not found");
    }

    const unchanged = await browser.tauri.execute(({ core }) => core.invoke("live_status"));
    expect(unchanged.hotkey).toBe(original.hotkey);
    expect(unchanged.pasteHotkey).toBe(original.pasteHotkey);
  });

  it("allows only minimized overlay status, rejects privileged commands, and survives close attempts", async () => {
    await showIdleOverlay();
    await browser.tauri.switchWindow("live-overlay");

    const authorization = await browser.tauri.execute(async ({ core }) => {
      const live = await core.invoke("live_overlay_status");
      let fullLive;
      try {
        await core.invoke("live_status");
        fullLive = { ok: true, message: "" };
      } catch (error) {
        fullLive = { ok: false, message: String(error) };
      }
      let setup;
      try {
        await core.invoke("setup_status");
        setup = { ok: true, message: "" };
      } catch (error) {
        setup = { ok: false, message: String(error) };
      }
      let file;
      try {
        await core.invoke("open_app_path", { path: "C:\\not-a-yap-file.txt" });
        file = { ok: true, message: "" };
      } catch (error) {
        file = { ok: false, message: String(error) };
      }
      return { file, fullLive, live, setup };
    });
    expect(typeof authorization.live.status).toBe("string");
    expect(authorization.live.hasFinalText).toBe(false);
    expect(authorization.live).not.toHaveProperty("partialText");
    expect(authorization.live).not.toHaveProperty("finalText");
    expect(authorization.live).not.toHaveProperty("inputDeviceId");
    expect(authorization.live).not.toHaveProperty("inputDeviceLabel");
    expect(authorization.fullLive.ok).toBe(false);
    expect(authorization.fullLive.message).toContain("Command is not available from this window.");
    expect(authorization.setup.ok).toBe(false);
    expect(authorization.setup.message).toContain("Command is not available from this window.");
    expect(authorization.file.ok).toBe(false);
    expect(authorization.file.message).toContain(
      "This file action is only available from the main window.",
    );

    const closeAttempt = await browser.tauri.execute(async ({ core }) => {
      try {
        await core.invoke("plugin:window|close", { label: "live-overlay" });
        return { ok: true, message: "" };
      } catch (error) {
        return { ok: false, message: String(error) };
      }
    });
    expect(closeAttempt.ok).toBe(true);
    await browser.pause(250);

    const windows = await browser.tauri.listWindows();
    expect(windows).toContain("main");
    expect(windows).toContain("live-overlay");
    expect(await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_visible", { label: "live-overlay" }))).toBe(true);
    expect(listRecordingArtifacts(recordingRoot)).toEqual([]);
  });

  it("keeps main alive when closed and restores it from the overlay", async () => {
    await showIdleOverlay();
    await withMainWindowRestored(async () => {
      await closeMainToTray();

      await browser.tauri.switchWindow("live-overlay");
      await browser.tauri.execute(({ core }) =>
        core.invoke("show_main_workspace", { workspace: "home" }));
      await browser.waitUntil(async () => browser.tauri.execute(({ core }) =>
        core.invoke("plugin:window|is_visible", { label: "main" })), {
        interval: 50,
        timeout: 5_000,
        timeoutMsg: "overlay command did not restore the main window",
      });
      expect(await browser.tauri.listWindows()).toContain("main");
    });
  });

  it("restores main and preserves the probe error after a hidden-state failure", async () => {
    await showIdleOverlay();
    const expectedError = new Error("simulated close-to-tray probe failure");
    let observedError;

    try {
      await withMainWindowRestored(async () => {
        await closeMainToTray();
        throw expectedError;
      });
    } catch (error) {
      observedError = error;
    }

    expect(observedError).toBe(expectedError);
    expect(await browser.tauri.listWindows()).toContain("main");
    expect(await browser.tauri.execute(({ core }) =>
      core.invoke("plugin:window|is_visible", { label: "main" }))).toBe(true);
  });
});

async function focusOverlayAction(label, appProcessId) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const activeLabel = await browser.tauri.execute(() =>
      document.activeElement?.getAttribute("aria-label") ?? "");
    if (activeLabel === label) return;
    await pressNativeOverlayKey(nativeVirtualKey.tab, appProcessId);
  }
  const activeLabel = await browser.tauri.execute(() =>
    document.activeElement?.getAttribute("aria-label") ?? "");
  throw new Error(`Could not focus ${label}; active control was ${activeLabel || "unlabeled"}.`);
}

async function pressNativeOverlayKey(virtualKey, expectedProcessId) {
  if (!Number.isInteger(virtualKey) || virtualKey < 0 || virtualKey > 0xFF) {
    throw new Error(`Invalid native virtual key ${virtualKey}.`);
  }
  if (!Number.isInteger(expectedProcessId) || expectedProcessId <= 0) {
    throw new Error(`Invalid Yap process ID ${expectedProcessId}.`);
  }
  const script = `
$ErrorActionPreference = "Stop"
Add-Type @'
using System;
using System.Runtime.InteropServices;

public static class WdioNativeOverlayKey {
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte virtualKey, byte scanCode, uint flags, UIntPtr extra);

    private const uint KeyUp = 0x0002;

    public static void Press(byte virtualKey, uint expectedProcessId) {
        uint foregroundProcessId;
        GetWindowThreadProcessId(GetForegroundWindow(), out foregroundProcessId);
        if (foregroundProcessId != expectedProcessId) {
            throw new InvalidOperationException("Yap did not own foreground focus before native key input.");
        }
        keybd_event(virtualKey, 0, 0, UIntPtr.Zero);
        keybd_event(virtualKey, 0, KeyUp, UIntPtr.Zero);
    }
}
'@

[WdioNativeOverlayKey]::Press([byte]${virtualKey}, [uint32]${expectedProcessId})
`;
  await execFileAsync(
    "pwsh.exe",
    ["-NoProfile", "-NonInteractive", "-Command", script],
    { maxBuffer: 1024 * 1024, windowsHide: true },
  );
}
