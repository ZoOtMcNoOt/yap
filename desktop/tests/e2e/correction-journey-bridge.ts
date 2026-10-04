import type { Page } from "@playwright/test";
import { installRecordingJourneyBridge } from "./recording-journey-bridge";

export const originalPlanningText = "The launch date is Frday.";
export const correctedPlanningText = "The launch date is Friday.";

// Native owners supply the sources and revision identities. This fixture
// verifies the connected UI, not native publication or inference correctness.
export async function installCorrectionJourneyBridge(
  page: Page,
  options: {
    preaccepted?: boolean;
    available?: boolean;
    recoveryFailure?: boolean;
    misboundRecovery?: boolean;
    sameCorrectionHash?: boolean;
  } = {},
) {
  await installRecordingJourneyBridge(page);
  await page.addInitScript(
    ({ original, corrected, options }) => {
      const host = globalThis as unknown as {
        __TAURI_INTERNALS__: {
          invoke: (command: string, args?: unknown) => Promise<unknown>;
        };
      };
      const baseInvoke = host.__TAURI_INTERNALS__.invoke;
      const mutations: Array<{ command: string; args: unknown }> = [];
      const planningPath = "C:\\Yap\\remote-jobs\\planning\\transcript.txt";
      const revisions = new Map<string, Record<string, unknown>[]>();
      const delayReads = new Set<string>();
      const releaseReads = new Map<string, () => void>();
      let recoveryFailure = options.recoveryFailure ?? false;
      let misboundRecovery = options.misboundRecovery ?? false;
      let requestedPath = planningPath;
      let suggested = corrected;
      if (options.preaccepted)
        revisions.set(planningPath, [{
          requestId: "accepted-earlier",
          revision: 1,
          sourceRevisionSha256: "a".repeat(64),
          sourceSha256: "b".repeat(64),
          terminologySnapshotSha256: "c".repeat(64),
          correctedSha256: "d".repeat(64),
          correctedText: corrected,
          revisionPath:
            "C:\\Yap\\remote-jobs\\planning\\transcript-corrections\\correction-00000000000000000001.json",
        }]);
      let sequence = 0;
      let publicationFails = false;
      let view = {
        schemaVersion: 1,
        requestId: "",
        status: "queued",
        applied: false,
        correctedText: null as string | null,
        reason: null,
        sourceRevisionSha256: "a".repeat(64),
        sourceSha256: "b".repeat(64),
        terminologySnapshotSha256: "c".repeat(64),
      };
      Object.assign(globalThis, {
        __correctionJourney: {
          mutations,
          setStatus(status: string) {
            view = {
              ...view,
              status,
              applied: status === "complete",
              correctedText: status === "complete" ? suggested : null,
            };
          },
          setRecoveryFailure(failed: boolean) {
            recoveryFailure = failed;
          },
          setMisboundRecovery(misbound: boolean) {
            misboundRecovery = misbound;
          },
          delayNextRead(path: string) {
            delayReads.add(path);
          },
          releaseRead(path: string) {
            releaseReads.get(path)?.();
          },
          setSuggestion(text: string) {
            suggested = text;
          },
          failPublicationOnce() {
            publicationFails = true;
          },
        },
      });
      host.__TAURI_INTERNALS__.invoke = async (command, args) => {
        if (command === "history_catalog") {
          return {
            maintenanceWarnings: [],
            sessions: ["planning", "review"].map((name, index) => ({
              sessionId: name,
              origin: "remote",
              name: `${name}.mp3`,
              sourcePath: `C:\\recordings\\${name}.mp3`,
              outputPath: `C:\\Yap\\remote-jobs\\${name}\\transcript.txt`,
              createdAtMs: Date.parse(
                `2026-10-02T${index ? "11" : "10"}:00:00Z`,
              ),
              speakerTranscriptAvailable: false,
              resultSummary: {
                languageBcp47: "en-US",
                languageStatus: "fixed",
                timingStatus: "unavailable",
              },
            })),
          };
        }
        if (command === "read_text_file" || command === "read_text_preview") {
          return (args as { path: string }).path.includes("planning")
            ? original
            : "The review is complete.";
        }
        if (
          command === "server_connection_status" ||
          command === "refresh_server_connection"
        ) {
          const snapshot = (await baseInvoke(command, args)) as {
            capabilities: Record<string, boolean>;
          };
          return {
            ...snapshot,
            capabilities: {
              ...snapshot.capabilities,
              transcriptCorrection: options.available ?? true,
            },
          };
        }
        if (command === "read_accepted_transcript_correction") {
          mutations.push({ command, args });
          const { outputPath: path, revision: selectedRevision } = args as { outputPath: string; revision: number | null };
          if (recoveryFailure)
            throw new Error(
              "A transcript correction revision conflicts with its source history.",
            );
          const loaded = {
            schemaVersion: 1,
            outputPath: misboundRecovery ? `${path}.different` : path,
            sourceRevisionSha256: "a".repeat(64),
            sourceSha256: "b".repeat(64),
            revisionCount: revisions.get(path)?.length ?? 0,
            acceptedRevision: (selectedRevision === null
              ? revisions.get(path)?.at(-1)
              : revisions.get(path)?.find(entry => entry.revision === selectedRevision)) ?? null,
          };
          if (delayReads.delete(path))
            await new Promise<void>((resolve) =>
              releaseReads.set(path, resolve),
            );
          return loaded;
        }
        if (command === "start_transcript_correction") {
          mutations.push({ command, args });
          requestedPath = (args as { outputPath: string }).outputPath;
          view = {
            ...view,
            requestId: `correction-${++sequence}`,
            status: "queued",
            applied: false,
            correctedText: null,
          };
          return view;
        }
        if (command === "transcript_correction_status") return view;
        if (command === "cancel_transcript_correction") {
          mutations.push({ command, args });
          view = {
            ...view,
            status: "cancelled",
            applied: false,
            correctedText: null,
          };
          return view;
        }
        if (command === "publish_transcript_correction") {
          mutations.push({ command, args });
          if (publicationFails) {
            publicationFails = false;
            throw new Error("The revision could not be saved. Try again.");
          }
          const revision =
            Number(revisions.get(requestedPath)?.at(-1)?.revision ?? 0) + 1;
          const accepted = {
            requestId: view.requestId,
            sourceRevisionSha256: view.sourceRevisionSha256,
            sourceSha256: view.sourceSha256,
            terminologySnapshotSha256: view.terminologySnapshotSha256,
            correctedSha256: options.sameCorrectionHash || revision % 2 ? "d".repeat(64) : "e".repeat(64),
            correctedText: suggested,
            revision,
            revisionPath: requestedPath.replace(
              "transcript.txt",
              `transcript-corrections/correction-${String(revision).padStart(20, "0")}.json`,
            ),
          };
          revisions.set(requestedPath, [...(revisions.get(requestedPath) ?? []), accepted]);
          return accepted;
        }
        return baseInvoke(command, args);
      };
    },
    {
      original: originalPlanningText,
      corrected: correctedPlanningText,
      options,
    },
  );
}
