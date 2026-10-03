import type { Page } from "@playwright/test";
import { installQueuedServerBridge } from "./app-server-bridge";

export const journeyTranscript = "We agreed to publish the reviewed interview on Friday.\nThe original recording remains unchanged.";

// This fixture exercises renderer/native command and event boundaries. It does
// not simulate inference accuracy, file admission, or native durability.
export async function installRecordingJourneyBridge(page: Page, restoredStatus?: "queued_server" | "failed" | "complete", pickedName = "interview.mp3") {
  await installQueuedServerBridge(page, "offline");
  await page.addInitScript(({ text, restoredStatus, pickedName }) => {
    type Job = {
      id: string;
      name: string;
      sourcePath: string;
      outputPath?: string;
      status: string;
      error?: string;
      route: string;
      sessionMode: string;
      sessionOrigin: string;
      pipeline: Record<string, string>;
    };
    const host = globalThis as unknown as {
      __TAURI_INTERNALS__: {
        invoke: (command: string, args?: unknown) => Promise<unknown>;
        transformCallback: (callback: (value: unknown) => void) => number;
      };
    };
    const baseInvoke = host.__TAURI_INTERNALS__.invoke;
    const callbacks = new Map<number, (value: unknown) => void>();
    const listeners = new Map<number, { event: string; handler: number }>();
    const mutations: Array<{ command: string; args: unknown }> = [];
    const jobs: Job[] = restoredStatus ? [{
      id: "restored-1", name: "restored.mp3", sourcePath: "C:\\recordings\\restored.mp3",
      outputPath: restoredStatus === "complete" ? "C:\\Yap\\remote-jobs\\restored-1\\transcript.txt" : undefined,
      status: restoredStatus, error: restoredStatus === "failed" ? "The server stopped before producing a result." : undefined,
      route: "serverBatch", sessionMode: "meeting", sessionOrigin: "importedFile", pipeline: {},
    }] : [];
    let nextId = 1000;
    let readFails = false;
    const emit = (event: string, payload: unknown) => {
      for (const [id, listener] of listeners) {
        if (listener.event === event) {
          callbacks.get(listener.handler)?.({ event, id, payload });
        }
      }
    };
    Object.assign(globalThis, {
      __recordingJourney: {
        mutations,
        setState(status: string) {
          const job = jobs.at(-1);
          if (!job) throw new Error("Pick a recording before advancing its fixture.");
          job.status = status;
          job.error = status === "failed" ? "The server stopped before producing a result." : undefined;
          if (status === "complete") {
            job.outputPath = `C:\\Yap\\remote-jobs\\${job.id}\\transcript.txt`;
          }
          emit("recording-jobs-changed", null);
        },
        setReadFails(fails: boolean) { readFails = fails; },
        openWorkspace(action: string) { emit("open-workspace", action); },
        emitNativeEvent(event: string, payload: unknown) { emit(event, payload); },
      },
    });
    host.__TAURI_INTERNALS__.transformCallback = (callback) => {
      const id = ++nextId;
      callbacks.set(id, callback);
      return id;
    };
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "plugin:event|listen") {
        const listener = args as { event: string; handler: number };
        const id = ++nextId;
        listeners.set(id, listener);
        return id;
      }
      if (command === "plugin:event|unlisten") {
        listeners.delete((args as { eventId: number }).eventId);
        return;
      }
      if (command === "server_connection_status" || command === "refresh_server_connection") {
        const snapshot = await baseInvoke(command, args) as { capabilities: Record<string, boolean> };
        return {
          ...snapshot,
          state: "ready",
          errorCode: null,
          capabilities: { ...snapshot.capabilities, batchJobs: true, jobStatus: true },
        };
      }
      if (command === "recording_jobs_snapshot") {
        return jobs.filter((job) => !["complete", "partial", "cancelled"].includes(job.status));
      }
      if (command === "recording_jobs_pick_imports") {
        mutations.push({ command, args });
        const job: Job = {
          id: `journey-${jobs.length + 1}`,
          name: pickedName,
          sourcePath: `C:\\recordings\\${pickedName}`,
          route: "serverBatch",
          sessionMode: "meeting",
          sessionOrigin: "importedFile",
          status: "queued_server",
          pipeline: { intake: "done", preprocessing: "done", transcription: "queued", alignment: "notStarted", diarization: "notStarted", postprocessing: "notStarted" },
        };
        jobs.push(job);
        return [job];
      }
      if (command === "recording_job_cancel" || command === "recording_job_retry") {
        mutations.push({ command, args });
        const job = jobs.find((job) => job.id === (args as { jobId: string }).jobId);
        if (!job) throw new Error("Unknown fixture job");
        if (command === "recording_job_retry" && job.status !== "failed") throw new Error("Only failed fixture jobs are retryable");
        job.status = command === "recording_job_cancel" ? "cancelled" : "queued_server";
        job.error = undefined;
        return job;
      }
      if (command === "history_catalog") {
        return {
          maintenanceWarnings: [],
          sessions: jobs.filter((job) => job.status === "complete").map((job) => ({
            sessionId: job.id, origin: "remote", name: job.name, sourcePath: job.sourcePath,
            outputPath: job.outputPath, createdAtMs: Date.parse("2026-10-02T10:00:00Z"),
            speakerTranscriptAvailable: false,
            resultSummary: { languageBcp47: "en-US", languageStatus: "fixed", timingStatus: "unavailable" },
          })),
        };
      }
      if (command === "read_text_file" || command === "read_text_preview") {
        if (readFails) throw new Error("The saved transcript could not be read.");
        return text;
      }
      if (command === "open_app_path" || command === "reveal_app_path") {
        mutations.push({ command, args });
        return;
      }
      return baseInvoke(command, args);
    };
  }, { text: journeyTranscript, restoredStatus, pickedName });
}
