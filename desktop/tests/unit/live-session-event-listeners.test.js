import { describe, expect, it } from "vitest";

import {
  registerLiveSessionEventListeners,
  waitForLiveSessionSavedEvent,
} from "../wdio/live-session-event-listeners.js";


describe("transactional live-session event listeners", () => {
  it("immediately unregisters earlier listeners when partial setup fails", async () => {
    const calls = [];
    const unlisten = () => calls.push("unlisten-live-session");
    const priorTauri = globalThis.__TAURI__;
    globalThis.__TAURI__ = {
      event: {
        async listen(name) {
          calls.push(name);
          if (name === "live-level") throw new Error("registration failed");
          return unlisten;
        },
      },
    };

    try {
      await expect(registerLiveSessionEventListeners()).rejects.toThrow("registration failed");
      expect(calls).toEqual(["live-overlay-session", "live-level", "unlisten-live-session"]);
    } finally {
      globalThis.__TAURI__ = priorTauri;
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("unregisters all listeners exactly once", async () => {
    const unlistened = [];
    const priorTauri = globalThis.__TAURI__;
    globalThis.__TAURI__ = {
      event: {
        async listen(name) {
          return () => unlistened.push(name);
        },
      },
    };

    try {
      await expect(registerLiveSessionEventListeners()).resolves.toBe(2);
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup()).resolves.toBe(2);
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup()).resolves.toBe(0);
      expect(unlistened).toEqual(["live-overlay-session", "live-level"]);
    } finally {
      globalThis.__TAURI__ = priorTauri;
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("keeps saved artifact events on a separate main-window listener", async () => {
    const priorTauri = globalThis.__TAURI__;
    let handler;
    globalThis.__TAURI__ = {
      event: {
        async listen(name, callback) {
          expect(name).toBe("live-session-saved");
          handler = callback;
          return () => undefined;
        },
      },
    };

    try {
      await expect(registerLiveSessionEventListeners({}, { target: "main" })).resolves.toBe(1);
      handler({ payload: { name: "live-s-1-2-3" } });
      expect(globalThis.__yapLiveSessionEventListeners.saved).toEqual([{ name: "live-s-1-2-3" }]);
      expect(globalThis.__yapLiveSessionEventListeners.sessions).toEqual([]);
      expect(globalThis.__yapLiveSessionEventListeners.levels).toEqual([]);
    } finally {
      globalThis.__TAURI__ = priorTauri;
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("can add full main-window lifecycle evidence without changing the default listener", async () => {
    const priorTauri = globalThis.__TAURI__;
    const handlers = new Map();
    globalThis.__TAURI__ = {
      event: {
        async listen(name, callback) {
          handlers.set(name, callback);
          return () => undefined;
        },
      },
    };

    try {
      await expect(registerLiveSessionEventListeners({}, {
        includeSessions: true,
        target: "main",
      })).resolves.toBe(2);
      handlers.get("live-session")({ payload: { route: "localFallback", status: "listening" } });
      handlers.get("live-session-saved")({ payload: { name: "live-s-1-2-3" } });
      expect(globalThis.__yapLiveSessionEventListeners.sessions).toEqual([
        { route: "localFallback", status: "listening" },
      ]);
      expect(globalThis.__yapLiveSessionEventListeners.saved).toEqual([{ name: "live-s-1-2-3" }]);
    } finally {
      globalThis.__TAURI__ = priorTauri;
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("retains a rejecting unlistener for a later successful retry", async () => {
    let rejectOnceAttempts = 0;
    const priorTauri = globalThis.__TAURI__;
    globalThis.__TAURI__ = {
      event: {
        async listen(name) {
          if (name !== "live-overlay-session") return () => undefined;
          return async () => {
            rejectOnceAttempts += 1;
            if (rejectOnceAttempts === 1) throw new Error("unlisten retry required");
          };
        },
      },
    };

    try {
      await registerLiveSessionEventListeners();
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup())
        .rejects.toThrow("unlisten retry required");
      expect(globalThis.__yapLiveSessionEventListeners.unlisteners).toHaveLength(1);
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup()).resolves.toBe(1);
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup()).resolves.toBe(0);
    } finally {
      globalThis.__TAURI__ = priorTauri;
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("preserves failed registration cleanup handles for outer-finally recovery", async () => {
    let cleanupAttempts = 0;
    const priorTauri = globalThis.__TAURI__;
    globalThis.__TAURI__ = {
      event: {
        async listen(name) {
          if (name === "live-level") throw new Error("registration failed");
          return async () => {
            cleanupAttempts += 1;
            if (cleanupAttempts === 1) throw new Error("partial cleanup failed");
          };
        },
      },
    };

    try {
      await expect(registerLiveSessionEventListeners())
        .rejects.toThrow(/registration failed.*partial cleanup failed/i);
      expect(globalThis.__yapLiveSessionEventListeners.unlisteners).toHaveLength(1);
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup()).resolves.toBe(1);
      await expect(globalThis.__yapLiveSessionEventListeners.cleanup()).resolves.toBe(0);
    } finally {
      globalThis.__TAURI__ = priorTauri;
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("waits through delayed saved-event dispatch before returning evidence", async () => {
    globalThis.__yapLiveSessionEventListeners = { levels: [], saved: [], sessions: [] };
    const dispatch = setTimeout(() => {
      globalThis.__yapLiveSessionEventListeners.saved.push({ name: "live-s-1-2-3" });
    }, 10);

    try {
      await expect(waitForLiveSessionSavedEvent({}, {
        expectedCount: 1,
        pollIntervalMs: 1,
        timeoutMs: 100,
      })).resolves.toMatchObject({
        saved: [{ name: "live-s-1-2-3" }],
      });
    } finally {
      clearTimeout(dispatch);
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });

  it("fails within the bounded saved-event deadline", async () => {
    globalThis.__yapLiveSessionEventListeners = { levels: [], saved: [], sessions: [] };
    try {
      await expect(waitForLiveSessionSavedEvent({}, {
        expectedCount: 1,
        pollIntervalMs: 1,
        timeoutMs: 10,
      })).rejects.toThrow(/timed out waiting for 1 saved event/i);
    } finally {
      delete globalThis.__yapLiveSessionEventListeners;
    }
  });
});
