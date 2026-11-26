import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { LiveCaptureMode, LiveInputDeviceView, LiveSessionView } from "@/lib/live-session";
import {
  clearLiveHotkey,
  clearLivePasteHotkey,
  listInputDevices,
  listenLiveSession,
  liveStatus,
  preflightInputDevice,
  recordLiveHotkey,
  recordLivePasteHotkey,
  resetLiveHotkey as resetLiveHotkeyToDefault,
  resetLivePasteHotkey as resetLivePasteHotkeyToDefault,
  setInputDevice,
  setLiveCaptureMode,
  setLiveOverlayEnabled,
  startLiveSession,
  stopLiveSession,
} from "@/live";

const initialLiveView: LiveSessionView = {
  captureMode: "pushToTalk",
  hotkey: "Ctrl+Shift+Space",
  pasteHotkey: "Ctrl+Shift+Alt+V",
  overlayFocusHotkey: "Ctrl+Shift+Alt+O",
  route: "none",
  status: "idle",
  transcriptionDegraded: false,
  visibility: "enabled",
};

type LiveCommand = { run: () => Promise<LiveSessionView> };

export function useLiveControl() {
  const [liveView, setLiveView] = useState<LiveSessionView>(initialLiveView);
  const [liveInputDevices, setLiveInputDevices] = useState<LiveInputDeviceView[]>([]);
  const [pending, setPending] = useState<LiveCommand | null>(null);
  const currentCommand = useRef<LiveCommand | null>(null);
  const [liveSettingsError, setLiveSettingsError] = useState("");

  const viewRevision = useRef(0);
  const acceptLiveView = useCallback((view: LiveSessionView) => {
    viewRevision.current++;
    setLiveView(view);
  }, []);
  const refreshLiveView = useCallback(async () => {
    const revision = ++viewRevision.current;
    const view = await liveStatus();
    if (viewRevision.current === revision) setLiveView(view);
  }, []);
  const refreshLiveState = useCallback(async () => {
    if (!isTauri()) return;
    await Promise.all([refreshLiveView(), listInputDevices().then(setLiveInputDevices)]);
  }, [refreshLiveView]);

  useEffect(() => {
    if (!isTauri()) return;

    let cancelled = false;
    let unlistenLive: (() => void) | undefined;
    void listenLiveSession(acceptLiveView).then((stop) => {
      if (cancelled) {
        stop();
        return;
      }
      unlistenLive = stop;
      // Recover a completion that happened before this window mounted, even
      // if model setup or microphone enumeration is unavailable.
      return refreshLiveView();
    }).catch((error) => {
      if (!cancelled) setLiveSettingsError(String(error));
    });

    return () => {
      cancelled = true;
      viewRevision.current++;
      unlistenLive?.();
    };
  }, [acceptLiveView, refreshLiveView]);

  const updateLive = useCallback(
    async (action: () => Promise<LiveSessionView>, message?: string) => {
      if (!isTauri()) return;
      const previous = currentCommand.current;
      if (previous && !(previous.run === startLiveSession && action === stopLiveSession)) return;

      const command = { run: action };
      currentCommand.current = command;
      setPending(command);
      try {
        setLiveSettingsError("");
        const view = await action();
        if (currentCommand.current !== command) return;
        acceptLiveView(view);
        const devices = await listInputDevices();
        if (currentCommand.current !== command) return;
        setLiveInputDevices(devices);
        if (message) toast.success(message);
      } catch (error) {
        if (currentCommand.current !== command) return;
        const nextMessage = String(error);
        setLiveSettingsError(nextMessage);
        toast.error(nextMessage);
      } finally {
        if (currentCommand.current === command) {
          currentCommand.current = null;
          setPending(null);
        }
      }
    },
    [acceptLiveView],
  );

  const updateLiveOverlay = useCallback(
    (enabled: boolean) => {
      void updateLive(() => setLiveOverlayEnabled(enabled), enabled ? "Live overlay enabled" : "Live overlay hidden");
    },
    [updateLive],
  );

  const updateLiveHotkey = useCallback(
    () => updateLive(recordLiveHotkey, "Live shortcut updated"),
    [updateLive],
  );

  const resetLiveHotkey = useCallback(() => {
    void updateLive(resetLiveHotkeyToDefault, "Live shortcut reset");
  }, [updateLive]);

  const clearLiveShortcut = useCallback(() => {
    void updateLive(clearLiveHotkey, "Live shortcut cleared");
  }, [updateLive]);

  const updateLivePasteHotkey = useCallback(
    () => updateLive(recordLivePasteHotkey, "Paste shortcut updated"),
    [updateLive],
  );

  const clearLivePasteShortcut = useCallback(() => {
    void updateLive(clearLivePasteHotkey, "Paste shortcut cleared");
  }, [updateLive]);

  const resetLivePasteHotkey = useCallback(() => {
    void updateLive(resetLivePasteHotkeyToDefault, "Paste shortcut reset");
  }, [updateLive]);

  const updateLiveCaptureMode = useCallback(
    (captureMode: LiveCaptureMode) => {
      void updateLive(() => setLiveCaptureMode(captureMode));
    },
    [updateLive],
  );

  const updateInputDevice = useCallback(
    (deviceId?: string) => {
      void updateLive(() => setInputDevice(deviceId));
    },
    [updateLive],
  );

  const preflightLiveInput = useCallback(() => {
    void updateLive(preflightInputDevice);
  }, [updateLive]);

  const startLive = useCallback(() => {
    void updateLive(startLiveSession);
  }, [updateLive]);

  const stopLive = useCallback(() => {
    void updateLive(stopLiveSession);
  }, [updateLive]);

  return {
    clearLivePasteShortcut,
    clearLiveShortcut,
    liveBusy: pending !== null,
    liveStartPending: pending?.run === startLiveSession,
    liveInputDevices,
    liveSettingsError,
    liveView,
    preflightLiveInput,
    refreshLiveState,
    resetLiveHotkey,
    resetLivePasteHotkey,
    startLive,
    stopLive,
    updateInputDevice,
    updateLiveCaptureMode,
    updateLiveHotkey,
    updateLiveOverlay,
    updateLivePasteHotkey,
  };
}
