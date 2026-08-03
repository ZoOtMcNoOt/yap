import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import {
  createRecordingJobsRefreshCoordinator,
  startRecordingJobsLifecycle,
} from "@/recording-jobs-refresh";

const hookSource = readFileSync(
  new URL("../../src/hooks/use-imported-recording-queue.ts", import.meta.url),
  "utf8",
);
const bridgeSource = readFileSync(
  new URL("../../src/recording-queue.ts", import.meta.url),
  "utf8",
);
const refreshSource = readFileSync(
  new URL("../../src/recording-jobs-refresh.ts", import.meta.url),
  "utf8",
);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("Rust recording job ownership", () => {
  it("keeps React as a snapshot listener rather than a queue mutator", () => {
    expect(hookSource).toContain("export function useRecordingJobs");
    expect(hookSource).toContain('listen("recording-jobs-changed"');
    expect(hookSource).toContain("recordingJobsSnapshot,");
    expect(hookSource).not.toMatch(/queueRef|nextRecordingId|writeRecordingQueue|allowRecordingPlaybackPath/);
    expect(bridgeSource).not.toMatch(/setItem|createInitialPipelineState|queuedServerMessage/);
  });

  it("subscribes before the initial snapshot without a browser migration gate", () => {
    expect(refreshSource.indexOf("await subscribe"))
      .toBeLessThan(refreshSource.indexOf('phase = "refresh"'));
    expect(hookSource).not.toMatch(/migration|legacyDiscard|localStorage/);
    expect(bridgeSource).not.toMatch(/legacyRecordingQueue|localStorage/);
  });

  it("routes native picker create, remove, retry, and clear through Rust commands", () => {
    expect(hookSource).toContain("pickRecordingImports(choice)");
    expect(bridgeSource).not.toMatch(/recording_jobs_create_imports|recording_jobs_import_legacy/);
    expect(hookSource).toContain("cancelRecordingJob(id)");
    expect(hookSource).toContain("dismissRecordingJob(id)");
    expect(hookSource).toContain("retryRecordingJob(id)");
    expect(hookSource).toContain("cancelRecordingJob(item.id)");
    expect(hookSource).toContain("dismissRecordingJob(item.id)");
  });

  it("runs a trailing snapshot when an event arrives during an in-flight refresh", async () => {
    const stale = deferred<string[]>();
    const stable = deferred<string[]>();
    const load = vi.fn()
      .mockImplementationOnce(() => stale.promise)
      .mockImplementationOnce(() => stable.promise);
    const applied: string[][] = [];
    const coordinator = createRecordingJobsRefreshCoordinator(load, (snapshot) => {
      applied.push(snapshot);
    });

    const initialRefresh = coordinator.refresh();
    const eventRefresh = coordinator.refresh();
    stale.resolve(["before-commit"]);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    stable.resolve(["after-commit"]);

    await expect(initialRefresh).resolves.toEqual(["after-commit"]);
    await expect(eventRefresh).resolves.toEqual(["after-commit"]);
    expect(applied).toEqual([["before-commit"], ["after-commit"]]);
  });

  it("settles startup only after subscription and a stable snapshot", async () => {
    const stale = deferred<string[]>();
    const stable = deferred<string[]>();
    const load = vi.fn()
      .mockImplementationOnce(() => stale.promise)
      .mockImplementationOnce(() => stable.promise);
    const coordinator = createRecordingJobsRefreshCoordinator(load, vi.fn());
    let publishEvent!: () => void;
    const lifecycle = startRecordingJobsLifecycle({
      failed: vi.fn(),
      refresh: coordinator.refresh,
      refreshFailed: vi.fn(),
      subscribe: vi.fn(async (handler) => {
        publishEvent = handler;
        return vi.fn();
      }),
    });
    let settled = false;
    void lifecycle.settled.then(() => {
      settled = true;
    });

    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    publishEvent();
    stale.resolve(["before-event"]);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(settled).toBe(false);
    stable.resolve(["after-event"]);
    await lifecycle.settled;

    expect(settled).toBe(true);
  });

  it("fails startup without loading a snapshot when listener registration rejects", async () => {
    const failed = vi.fn();
    const refresh = vi.fn();
    const lifecycle = startRecordingJobsLifecycle({
      failed,
      refresh,
      refreshFailed: vi.fn(),
      subscribe: vi.fn().mockRejectedValue(new Error("listener unavailable")),
    });

    await lifecycle.settled;

    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({ message: "listener unavailable" }),
      "subscribe",
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("attributes an initial snapshot failure to the refresh phase", async () => {
    const snapshotFailed = vi.fn();
    const snapshotLifecycle = startRecordingJobsLifecycle({
      failed: snapshotFailed,
      refresh: vi.fn().mockRejectedValue(new Error("snapshot unavailable")),
      refreshFailed: vi.fn(),
      subscribe: vi.fn().mockResolvedValue(vi.fn()),
    });
    await snapshotLifecycle.settled;
    expect(snapshotFailed).toHaveBeenCalledWith(
      expect.objectContaining({ message: "snapshot unavailable" }),
      "refresh",
    );
  });

  it("unlistens a listener that resolves after lifecycle disposal", async () => {
    const listener = deferred<() => void>();
    const unlisten = vi.fn();
    const refresh = vi.fn();
    const lifecycle = startRecordingJobsLifecycle({
      failed: vi.fn(),
      refresh,
      refreshFailed: vi.fn(),
      subscribe: vi.fn(() => listener.promise),
    });

    lifecycle.dispose();
    listener.resolve(unlisten);
    await lifecycle.settled;

    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(refresh).not.toHaveBeenCalled();
  });
});
