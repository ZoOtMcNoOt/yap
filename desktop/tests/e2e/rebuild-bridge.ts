import type { Page } from "@playwright/test";
import { installWorkspaceAcceptanceBridge } from "./workspace-acceptance-bridge";
export async function installRebuildBridge(
  page: Page,
  options: { unavailable?: boolean } = {},
) {
  await installWorkspaceAcceptanceBridge(page);
  await page.addInitScript((options) => {
    const host = globalThis as unknown as {
      __TAURI_INTERNALS__: {
        invoke: (command: string, args?: unknown) => Promise<unknown>;
      };
    };
    const base = host.__TAURI_INTERNALS__.invoke;
    let authority = "1",
      active: string | null = "b".repeat(64),
      status = "unadmitted",
      prepared = false;
    let failure: string | null = null,
      lost = false,
      delay = false,
      release: (() => void) | null = null;
    const calls: {
      request: {
        action: string;
        generationSha256?: string;
        expectedActiveGenerationSha256?: string | null;
      };
      authorityRevision: string;
    }[] = [];
    const target = "a".repeat(64),
      previous = "b".repeat(64);
    const metadata = (hash: string) => ({
      schemaVersion: 1,
      generationSha256: hash,
      sourceRevision:
        hash === target ? "reviewed-source-2" : "reviewed-source-1",
      status:
        active === hash ? "active" : hash === target ? status : "retained",
      activeGenerationSha256: active,
      conceptCount: 2,
      chunkCount: 2,
      relationshipCount: 1,
      permissionCount: 2,
    });
    function recheck() {
      (
        globalThis as unknown as {
          __recordingJourney: {
            emitNativeEvent: (e: string, p: unknown) => void;
          };
        }
      ).__recordingJourney.emitNativeEvent("server-connection", {
        state: "ready",
        authorityRevision: authority,
        checkedAtMs: 2,
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
          knowledgeConnections: false,
          knowledgeRebuild: !options.unavailable,
          personalTerminology: false,
          studentQuestions: false,
          archivistIngestions: false,
          curatorProposals: false,
        },
      });
    }
    Object.assign(globalThis, {
      __rebuild: {
        calls,
        failNext: (code: string) => {
          failure = code;
        },
        loseNextReply: () => {
          lost = true;
        },
        delayNext: () => {
          delay = true;
        },
        release: () => release?.(),
        changeOwner: () => {
          authority = String(Number(authority) + 1);
          recheck();
        },
        changeActive: () => {
          active = "c".repeat(64);
        },
        recheck,
        wrongDescriptor: () => {
          failure = "descriptor";
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
          capabilities: object;
        };
        return {
          ...snapshot,
          authorityRevision: authority,
          capabilities: {
            ...snapshot.capabilities,
            librarianQueries: false,
            curatorProposals: false,
            knowledgeRebuild: !options.unavailable,
          },
        };
      }
      if (command !== "knowledge_rebuild") return base(command, args);
      const own = args as (typeof calls)[number];
      calls.push(own);
      const { request } = own;
      if (own.authorityRevision !== authority)
        throw { code: "identityChanged", unconfirmed: false };
      if (delay) {
        delay = false;
        await new Promise<void>((resolve) => (release = resolve));
        release = null;
      }
      if (failure && failure !== "descriptor") {
        const code = failure;
        failure = null;
        throw { code, unconfirmed: false };
      }
      let kind = "",
        value: unknown;
      if (request.action === "source" || request.action === "stage") {
        const changed = status === "unadmitted";
        if (request.action === "stage") status = "staged";
        kind = request.action === "source" ? "source" : "staged";
        value = {
          ...metadata(target),
          sourcePath: "reviewed/organization",
          ...(request.action === "stage" ? { changed } : {}),
        };
      } else if (request.action === "embeddings") {
        const changed = !prepared;
        prepared = true;
        kind = "prepared";
        value = {
          schemaVersion: 1,
          generationSha256: target,
          status: "prepared",
          chunkCount: 2,
          embeddingModelId: "fixture-embedding",
          embeddingModelRevision: "f".repeat(64),
          changed,
        };
      } else if (request.action === "inspect") {
        if (![target, previous].includes(request.generationSha256!))
          throw { code: "notFound", unconfirmed: false };
        kind = "generation";
        value = metadata(request.generationSha256!);
      } else {
        const changed = active !== request.generationSha256;
        if (changed && active !== request.expectedActiveGenerationSha256)
          throw { code: "knowledgeChanged", unconfirmed: false };
        const before = active;
        active = request.generationSha256!;
        kind = "activated";
        value = {
          ...metadata(active),
          changed,
          previousActiveGenerationSha256: before,
        };
      }
      if (failure === "descriptor") {
        failure = null;
        value = { ...(value as object), chunkCount: 9 };
      }
      if (lost) {
        lost = false;
        throw { code: "unavailable", unconfirmed: true };
      }
      return { authorityRevision: authority, response: { kind, value } };
    };
  }, options);
}
