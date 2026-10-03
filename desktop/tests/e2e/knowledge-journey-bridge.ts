import type { Page } from "@playwright/test";
import { installRecordingJourneyBridge } from "./recording-journey-bridge";

export const launchEvidenceText =
  "The reviewed launch was approved for Friday.";

// All requests still cross the native command boundary. Results are fixed
// projections for interaction tests; they do not qualify retrieval/inference.
export async function installKnowledgeJourneyBridge(
  page: Page,
  sources: "single" | "pair" | "duplicate" | "long" = "single",
) {
  await installRecordingJourneyBridge(page);
  await page.addInitScript(
    ({ text, sources }) => {
      const host = globalThis as unknown as {
        __TAURI_INTERNALS__: {
          invoke: (command: string, args?: unknown) => Promise<unknown>;
        };
        __recordingJourney: {
          emitNativeEvent: (event: string, payload: unknown) => void;
        };
      };
      const baseInvoke = host.__TAURI_INTERNALS__.invoke;
      const mutations: Array<{ command: string; args: unknown }> = [];
      const statuses = new Map<string, string>();
      const requests = new Map<string, string>();
      const delayedCancellations = new Set<string>();
      const releaseCancellations = new Map<string, () => void>();
      const delayedSubmissions = new Set<string>();
      const releaseSubmissions = new Map<string, () => void>();
      let sequence = 0;
      let authorityRevision = "1";
      let latestSnapshot: Record<string, unknown> | null = null;
      const generation = "a".repeat(64);
      const citation = {
        conceptId: "meetings/launch-review",
        sourceRevision: "reviewed-1",
        contentSha256: "b".repeat(64),
        charStart: 0,
        charEnd: text.length,
        text,
      };
      const items =
        sources === "single"
          ? [citation]
          : [
              citation,
              {
                ...citation,
                conceptId:
                  sources === "duplicate"
                    ? citation.conceptId
                    : "decisions/launch-approval",
                charStart: 60,
                charEnd: 60 + (sources === "long" ? 1_025 : text.length),
                text: sources === "long" ? "x".repeat(1_025) : text,
              },
            ];
      const support = {
        sourceCitation: citation,
        supportQuote: text,
        supportCharStart: 0,
        supportCharEnd: text.length,
      };
      const question = {
        schemaVersion: 3,
        sourceSubject: "launch review",
        question: "When was the reviewed launch approved?",
        sourceSupports: [support],
      };
      function view(task: string) {
        const status = statuses.get(task) ?? "queued";
        const common = {
          schemaVersion: 1,
          requestId: requests.get(task),
          status,
          reason: null,
        };
        if (task === "librarian_query")
          return {
            ...common,
            evidencePack:
              status === "complete"
                ? {
                    operation: "search",
                    generationSha256: generation,
                    permissionHash: "c".repeat(64),
                    authorizationHash: "d".repeat(64),
                    evidenceSha256: "e".repeat(64),
                    items,
                    outputBudgetExhausted: false,
                  }
                : null,
          };
        if (task === "analyst_answer")
          return {
            ...common,
            citedAnswer:
              status === "complete"
                ? {
                    schemaVersion: 1,
                    answer: text,
                    citations: [citation],
                    answerSha256: "f".repeat(64),
                    citationSha256: "b".repeat(64),
                    evidenceSha256: "e".repeat(64),
                  }
                : null,
          };
        if (task === "coordinator_bundle")
          return {
            ...common,
            proposalBundle:
              status === "complete"
                ? {
                    schemaVersion: 1,
                    generationSha256: generation,
                    evidenceSha256: "e".repeat(64),
                    bundleSha256: "f".repeat(64),
                    citationSha256: "b".repeat(64),
                    canonical: false,
                    requiresReview: true,
                    items: [
                      {
                        proposalId: "proposal-1",
                        proposalType: "summary",
                        proposedContent: text,
                        citations: [citation],
                        citationSha256: "b".repeat(64),
                        candidateSha256: "c".repeat(64),
                      },
                    ],
                  }
                : null,
          };
        if (task === "auditor_report")
          return {
            ...common,
            report:
              status === "complete"
                ? {
                    schemaVersion: 1,
                    generationSha256: generation,
                    sourceAdmissionSha256: "b".repeat(64),
                    evidenceSha256: "e".repeat(64),
                    citationSha256: "b".repeat(64),
                    canonical: false,
                    requiresReview: true,
                    reportSha256: "f".repeat(64),
                    findings: [
                      {
                        kind: "potential-contradiction",
                        summary:
                          "These two current reviewed knowledge statements may conflict.",
                        citations: [
                          citation,
                          {
                            ...citation,
                            conceptId: "meetings/launch-delay",
                            text: "The reviewed launch was delayed.",
                            charEnd: "The reviewed launch was delayed.".length,
                          },
                        ],
                        findingSha256: "c".repeat(64),
                        requiresReview: true,
                      },
                    ],
                  }
                : null,
          };
        if (task === "student_question")
          return {
            ...common,
            conversationConceptId: citation.conceptId,
            generationSha256: generation,
            evidenceSha256: "e".repeat(64),
            questions: status === "complete" ? [question] : [],
            outputBudgetExhausted: false,
          };
        return {
          ...common,
          generationSha256: generation,
          evidenceSha256: "e".repeat(64),
          submissionId: "submission-1",
          proposalId: status === "proposed" ? "proposal-1" : null,
        };
      }
      Object.assign(globalThis, {
        __knowledgeJourney: {
          mutations,
          delayNextCancellation(task: string) {
            delayedCancellations.add(task);
          },
          releaseCancellation(task: string) {
            releaseCancellations.get(task)?.();
          },
          delayNextSubmission(task: string) {
            delayedSubmissions.add(task);
          },
          releaseSubmission(task: string) {
            releaseSubmissions.get(task)?.();
          },
          setStatus(task: string, status: string) {
            statuses.set(task, status);
          },
          setAvailable(available: boolean) {
            if (!latestSnapshot)
              throw new Error("The native snapshot has not loaded");
            latestSnapshot = {
              ...latestSnapshot,
              capabilities: {
                ...(latestSnapshot.capabilities as Record<string, boolean>),
                librarianQueries: available,
                analystAnswers: available,
                coordinatorBundles: available,
                auditorReports: available,
                curatorProposals: available,
              },
            };
            host.__recordingJourney.emitNativeEvent(
              "server-connection",
              latestSnapshot,
            );
          },
          recheckConnection(revision: string) {
            if (!latestSnapshot)
              throw new Error("The native snapshot has not loaded");
            authorityRevision = revision;
            latestSnapshot = {
              ...latestSnapshot,
              authorityRevision: revision,
              checkedAtMs: Date.now(),
            };
            host.__recordingJourney.emitNativeEvent(
              "server-connection",
              latestSnapshot,
            );
          },
        },
      });
      host.__TAURI_INTERNALS__.invoke = async (command, args) => {
        if (
          command === "server_connection_status" ||
          command === "refresh_server_connection"
        ) {
          const snapshot = (await baseInvoke(command, args)) as {
            capabilities: Record<string, boolean>;
          };
          latestSnapshot = {
            ...snapshot,
            authorityRevision,
            capabilities: {
              ...snapshot.capabilities,
              librarianQueries: true,
              analystAnswers: true,
              coordinatorBundles: true,
              auditorReports: true,
              knowledgeConnections: false,
              personalTerminology: false,
              studentQuestions: true,
              curatorProposals: true,
            },
          };
          return latestSnapshot;
        }
        if (command === "start_connection_proposal") {
          mutations.push({ command, args });
          if (
            (args as { authorityRevision: string }).authorityRevision !==
            authorityRevision
          ) {
            throw new Error(
              "Your server or sign-in changed. Refresh before submitting.",
            );
          }
          const task = "curator_proposal";
          requests.set(task, `${task}-${++sequence}`);
          statuses.set(task, "queued");
          const submitted = view(task);
          if (delayedSubmissions.delete(task)) {
            await new Promise<void>((resolve) =>
              releaseSubmissions.set(task, resolve),
            );
            releaseSubmissions.delete(task);
          }
          return submitted;
        }
        const start =
          /^(start|cancel)_(librarian_query|analyst_answer|coordinator_bundle|auditor_report|student_question|curator_proposal)$/.exec(
            command,
          );
        if (start) {
          const [, action, task] = start;
          mutations.push({ command, args });
          if (action === "start") {
            if (
              [
                "librarian_query",
                "analyst_answer",
                "coordinator_bundle",
                "auditor_report",
                "curator_proposal",
              ].includes(task) &&
              (args as { authorityRevision: string }).authorityRevision !==
                authorityRevision
            ) {
              throw new Error(
                "Your server or sign-in changed. Refresh before submitting.",
              );
            }
            requests.set(task, `${task}-${++sequence}`);
            statuses.set(task, "queued");
            if (delayedSubmissions.delete(task)) {
              const submitted = view(task);
              await new Promise<void>((resolve) =>
                releaseSubmissions.set(task, resolve),
              );
              releaseSubmissions.delete(task);
              return submitted;
            }
          } else {
            if (delayedCancellations.delete(task)) {
              await new Promise<void>((resolve) =>
                releaseCancellations.set(task, resolve),
              );
              releaseCancellations.delete(task);
            }
            statuses.set(task, "cancelled");
          }
          return view(task);
        }
        const poll =
          /^(librarian_query|analyst_answer|coordinator_bundle|auditor_report|student_question|curator_proposal)_status$/.exec(
            command,
          );
        if (poll) return view(poll[1]);
        return baseInvoke(command, args);
      };
    },
    { text: launchEvidenceText, sources },
  );
}
