import type { Page } from "@playwright/test";
import {
  installKnowledgeJourneyBridge,
  launchEvidenceText,
} from "./knowledge-journey-bridge";

export const proposalReference = "d".repeat(64);

// Deterministic native projections exercise interaction, not inference or identity qualification.
export async function installProposalInspectionBridge(page: Page) {
  await installKnowledgeJourneyBridge(page, "pair");
  await page.addInitScript(
    ({ text, reference }) => {
      const host = globalThis as unknown as {
        __TAURI_INTERNALS__: {
          invoke: (command: string, args?: any) => Promise<any>;
        };
        __recordingJourney: {
          emitNativeEvent: (event: string, payload: any) => void;
        };
      };
      const base = host.__TAURI_INTERNALS__.invoke;
      const emit = host.__recordingJourney.emitNativeEvent;
      let revision = "1";
      const decorate = (snapshot: any) => {
        revision = snapshot.authorityRevision;
        snapshot.capabilities.knowledgeConnections =
          snapshot.capabilities.librarianQueries;
        return snapshot;
      };
      host.__recordingJourney.emitNativeEvent = (event, payload) =>
        emit(
          event,
          event === "server-connection" ? decorate(payload) : payload,
        );
      const calls: Array<{ command: string; args: any }> = [];
      let mode = "success";
      let delayed = false;
      let delayedCancellation = false;
      let rejectCancellation: (() => void) | undefined;
      let release: (() => void) | undefined;
      Object.assign(globalThis, {
        __proposalInspection: {
          calls,
          mode(value: string) {
            mode = value;
          },
          delayCancellation() {
            delayedCancellation = true;
          },
          async rejectCancellation() {
            rejectCancellation?.();
            await new Promise<void>((resolve) =>
              requestAnimationFrame(() =>
                requestAnimationFrame(() => resolve()),
              ),
            );
          },
          delay() {
            delayed = true;
          },
          release() {
            release?.();
          },
        },
      });
      host.__TAURI_INTERNALS__.invoke = async (command, args) => {
        if (command === "knowledge_connections") {
          calls.push({ command, args });
          if (args.authorityRevision !== revision)
            throw { code: "identityChanged" };
          if (mode !== "success") throw { code: mode };
          const source = (id: string, title: string, start: number) => ({
            node: {
              conceptId: id,
              title,
              type: "decision",
              sourcePath: `${id}.md`,
              sourceRevision: "reviewed-1",
              contentSha256: "b".repeat(64),
            },
            citation: {
              conceptId: id,
              sourceRevision: "reviewed-1",
              contentSha256: "b".repeat(64),
              charStart: start,
              charEnd: start + text.length,
            },
            text,
          });
          const receipt = {
            authorityRevision: revision,
            response: {
              kind: "proposal",
              value: {
                schemaVersion: 1,
                proposalId: args.request.proposalId,
                status: "proposed",
                generationSha256: "a".repeat(64),
                permissionHash: "c".repeat(64),
                authorizationHash: "e".repeat(64),
                candidate: {
                  schemaVersion: 1,
                  sourceConceptId: "meetings/launch-review",
                  targetConceptId: "decisions/launch-approval",
                  relationshipType: "supports",
                  rationale:
                    "The reviewed meeting records the decision approving Friday’s launch.",
                },
                sources: [
                  source("decisions/launch-approval", "Launch approval", 60),
                  source("meetings/launch-review", "Launch review", 0),
                ],
              },
            },
          };
          if (delayed) {
            delayed = false;
            return new Promise((resolve) => {
              release = () => {
                resolve(receipt);
              };
            });
          }
          return receipt;
        }
        if (command === "cancel_knowledge_connections") {
          calls.push({ command, args });
          // Keep the read unresolved until release, modeling late completion after cancellation.
          if (delayedCancellation) {
            delayedCancellation = false;
            return new Promise((_, reject) => {
              rejectCancellation = () =>
                reject(new Error("fixture late cancellation failure"));
            });
          }
          return;
        }
        const result = await base(command, args);
        if (
          command === "server_connection_status" ||
          command === "refresh_server_connection"
        )
          return decorate(result);
        if (
          command === "curator_proposal_status" &&
          result.status === "proposed"
        )
          return { ...result, proposalId: reference };
        return result;
      };
    },
    { text: launchEvidenceText, reference: proposalReference },
  );
}
