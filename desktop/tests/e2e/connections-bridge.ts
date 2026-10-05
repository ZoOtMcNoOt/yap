import type { Page } from "@playwright/test";
import { installWorkspaceAcceptanceBridge } from "./workspace-acceptance-bridge";

// Fixed native-boundary records qualify UI behavior only. Real storage, HTTP,
// and native parsing have separate tests; this fixture invokes no model.
export async function installConnectionsBridge(
  page: Page,
  options: { large?: boolean; empty?: boolean; unavailable?: boolean } = {},
) {
  await installWorkspaceAcceptanceBridge(page);
  await page.addInitScript((options) => {
    const host = globalThis as unknown as {
      __TAURI_INTERNALS__: {
        invoke: (command: string, args?: unknown) => Promise<unknown>;
      };
    };
    const base = host.__TAURI_INTERNALS__.invoke;
    let authority = "1";
    let nextError: string | null = null;
    let delayNext = false;
    let release: (() => void) | null = null;
    let cancelled: (() => void) | null = null;
    const calls: unknown[] = [];
    const generation = "a".repeat(64);
    const common = {
      schemaVersion: 1,
      generationSha256: generation,
      permissionHash: "c".repeat(64),
      authorizationHash: "d".repeat(64),
    };
    const nodes = [
      ["projects/yap", "project", "Yap"],
      ["decisions/interface", "decision", "Voice-first interface"],
      ["concepts/private-server", "concept", "Private organization server"],
      ["conversations/review", "conversation", "Weekly product review"],
    ].map(([conceptId, type, title]) => ({
      conceptId,
      type,
      title,
      sourcePath: `${conceptId}.md`,
      sourceRevision: "reviewed-1",
      contentSha256: "b".repeat(64),
    }));
    if (options.large)
      for (let i = 3; i < 16; i++)
        nodes.push({
          ...nodes[1],
          conceptId: `decisions/topic-${i}`,
          title: `Reviewed topic ${i} with a long descriptive title`,
          sourcePath: `decisions/topic-${i}.md`,
        });
    const relationships = nodes.slice(1).map((node, index) => ({
      relationshipId: index.toString(16).padStart(64, "e"),
      sourceConceptId: index % 2 ? "projects/yap" : node.conceptId,
      targetConceptId: index % 2 ? node.conceptId : "projects/yap",
      type: index % 2 ? "references" : "supports",
      authority:
        index === 0 ? "human_confirmed" : index === 1 ? "derived" : "asserted",
      citation: {
        sourcePath: (index % 2 ? nodes[0] : node).sourcePath,
        sourceRevision: "reviewed-1",
        contentSha256: "b".repeat(64),
        charStart: index === 0 ? null : 12,
        charEnd: index === 0 ? null : 42,
      },
    }));
    let checkedAt = 1;
    function recheck() {
      (
        globalThis as unknown as {
          __recordingJourney: {
            emitNativeEvent: (event: string, payload: unknown) => void;
          };
        }
      ).__recordingJourney.emitNativeEvent("server-connection", {
        state: "ready",
        checkedAtMs: ++checkedAt,
        authorityRevision: authority,
        retryAtMs: null,
        apiVersion: "1",
        errorCode: null,
        capabilities: {
          batchJobs: false,
          liveStreaming: false,
          jobStatus: false,
          transcriptCorrection: false,
          librarianQueries: false,
          analystAnswers: false,
          coordinatorBundles: false,
          auditorReports: false,
          personalTerminology: false,
          studentQuestions: false,
          archivistIngestions: false,
          curatorProposals: false,
          knowledgeConnections: true, knowledgeRebuild: false,
        },
      });
    }
    Object.assign(globalThis, {
      __connections: {
        calls,
        recheckAuthority() {
          recheck();
        },
        failNext(code: string) {
          nextError = code;
        },
        delayNext() {
          delayNext = true;
        },
        release() {
          release?.();
        },
        changeAuthority() {
          authority = "2";
          recheck();
        },
      },
    });
    host.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (
        ["server_connection_status", "refresh_server_connection"].includes(
          command,
        )
      ) {
        const snapshot = (await base(command, args)) as {
          capabilities: Record<string, boolean>;
        };
        return {
          ...snapshot,
          authorityRevision: authority,
          capabilities: {
            ...snapshot.capabilities,
            librarianQueries: false,
            knowledgeConnections: !options.unavailable,
          },
        };
      }
      if (command === "cancel_knowledge_connections") {
        calls.push({ command, args });
        cancelled?.();
        return;
      }
      if (command !== "knowledge_connections") return base(command, args);
      const requestArgs = args as {
        requestId: string;
        authorityRevision: string;
        request: {
          action: string;
          search?: string;
          conceptId?: string;
          generationSha256?: string;
        };
      };
      calls.push({ command, args });
      const { request, authorityRevision } = requestArgs;
      if (authorityRevision !== authority)
        throw { code: "identityChanged" };
      if (nextError) {
        const code = nextError;
        nextError = null;
        throw { code };
      }
      if (delayNext) {
        delayNext = false;
        await new Promise<void>((resolve, reject) => {
          release = resolve;
          cancelled = () => reject({ code: "cancelled" });
        }).finally(() => {
          release = null;
          cancelled = null;
        });
      }
      if (request.action === "browse")
        return {
          authorityRevision: authority,
          response: {
            kind: "topics",
            value: {
              ...common,
              nodes: options.empty
                ? []
                : nodes
                    .filter((node) =>
                      node.title
                        .toLowerCase()
                        .includes(request.search!.toLowerCase()),
                    )
                    .slice(0, 12),
              hasMore: options.large && !request.search,
            },
          },
        };
      const edges = relationships.filter(
        (edge) =>
          edge.sourceConceptId === request.conceptId ||
          edge.targetConceptId === request.conceptId,
      );
      const ids = new Set([
        request.conceptId,
        ...edges.flatMap((edge) => [
          edge.sourceConceptId,
          edge.targetConceptId,
        ]),
      ]);
      return {
        authorityRevision: authority,
        response: {
          kind: "neighborhood",
          value: {
            ...common,
            conceptId: request.conceptId,
            nodes: nodes.filter((node) => ids.has(node.conceptId)),
            relationships: edges,
            hasMore: false,
          },
        },
      };
    };
  }, options);
}
