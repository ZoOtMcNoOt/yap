import type { Page } from "@playwright/test";
import { installRecordingJourneyBridge } from "./recording-journey-bridge";

export async function installPersonalizationBridge(
  page: Page,
  options: {
    shared?: boolean;
    teamCanManage?: boolean;
    organizationCanManage?: boolean;
    count?: number;
    state?: string;
    capability?: boolean;
    primaryLocale?: string;
  } = {},
) {
  await installRecordingJourneyBridge(page, "complete");
  await page.addInitScript(
    ({
      count,
      state,
      capability,
      primaryLocale,
      shared,
      teamCanManage,
      organizationCanManage,
    }) => {
      const host = globalThis as unknown as {
        __TAURI_INTERNALS__: {
          invoke: (command: string, args?: unknown) => Promise<unknown>;
        };
        __recordingJourney: {
          emitNativeEvent: (event: string, value: unknown) => void;
        };
      };
      const base = host.__TAURI_INTERNALS__.invoke;
      type Term = {
        scopeId: string;
        recordId: string;
        locale: string;
        canonicalForm: string;
        variants: string[];
        sensitivity: string;
        version: number;
        changedAt: string;
      };
      const records: Term[] = Array.from({ length: count }, (_, i) => ({
        scopeId: "personal",
        recordId: `term-${String(i + 1).padStart(5, "0")}`,
        locale: "en-US",
        canonicalForm: `Term ${i + 1}`,
        variants: [`variant ${i + 1}`],
        sensitivity: "internal",
        version: 1,
        changedAt: "2026-10-02T12:00:00Z",
      }));
      const scopes = [
        {
          scopeId: "personal",
          kind: "personal",
          label: "Personal",
          canManage: true,
        },
        ...(shared
          ? [
              {
                scopeId: "organization",
                kind: "organization",
                label: "Example organization",
                canManage: organizationCanManage,
              },
              {
                scopeId: "team:clinical",
                kind: "team",
                label: "Clinical team",
                canManage: teamCanManage,
              },
            ]
          : []),
      ];
      if (shared)
        records.push({
          scopeId: "team:clinical",
          recordId: "term-shared",
          locale: "en-US",
          canonicalForm: "Clinical Yap",
          variants: ["clinical-yap"],
          sensitivity: "internal",
          version: 1,
          changedAt: "2026-10-03T12:00:00Z",
        });
      const replay = new Map<string, Term>();
      const fixture = {
        records,
        scopes,
        authorityRevision: "1",
        calls: [] as Record<string, unknown>[],
        state,
        capability,
        mode: "ok",
        snapshot: null as Record<string, unknown> | null,
        finish: null as (() => void) | null,
        setConnection(next: string, enabled = true) {
          fixture.state = next;
          fixture.capability = enabled;
          if (fixture.snapshot)
            host.__recordingJourney.emitNativeEvent("server-connection", {
              ...fixture.snapshot,
              state: next,
              capabilities: {
                ...(fixture.snapshot.capabilities as object),
                knowledgeConnections: false, personalTerminology: enabled,
              },
            });
        },
      };
      Object.assign(globalThis, { __personalization: fixture });
      host.__TAURI_INTERNALS__.invoke = async (command, args) => {
        if (command === "primary_language_status" && primaryLocale) {
          return {
            ...((await base(command, args)) as object),
            confirmedLanguageBcp47: primaryLocale,
          };
        }
        if (
          command === "server_connection_status" ||
          command === "refresh_server_connection"
        ) {
          const original = (await base(command, args)) as {
            capabilities: Record<string, boolean>;
          };
          const snapshot = {
            ...original,
            state: fixture.state,
            capabilities: {
              ...original.capabilities,
              knowledgeConnections: false, personalTerminology: fixture.capability,
              transcriptCorrection: false,
            },
          };
          fixture.snapshot = snapshot;
          return snapshot;
        }
        if (command !== "terminology") return base(command, args);
        const request = (args as { request: Record<string, unknown> }).request;
        const expected = (args as { authorityRevision: string | null })
          .authorityRevision;
        if (
          request.action !== "discover" &&
          expected !== fixture.authorityRevision
        )
          throw { code: "identityChanged", retryable: false };
        const startedRevision = fixture.authorityRevision;
        const response = await (async () => {
          fixture.calls.push(structuredClone(request));
          if (
            fixture.mode === "pending" &&
            !["list", "discover"].includes(String(request.action))
          )
            await new Promise<void>((resolve) => {
              fixture.finish = resolve;
            });
          if (request.action === "discover") {
            if (fixture.mode === "discoveryFailure")
              throw { code: "unavailable", retryable: true };
            return {
              kind: "scopes",
              value: { scopes: structuredClone(fixture.scopes) },
            };
          }
          const selectedScope = fixture.scopes.find(
            (s) => s.scopeId === request.scopeId,
          );
          if (!selectedScope) throw { code: "notFound", retryable: false };
          if (
            !["list", "read"].includes(String(request.action)) &&
            !selectedScope.canManage
          )
            throw { code: "denied", retryable: false };
          if (request.action === "list") {
            if (fixture.mode === "listFailure")
              throw { code: "unavailable", retryable: true };
            const matching = records
              .filter(
                (r) =>
                  r.scopeId === request.scopeId &&
                  (r.locale === request.locale || r.locale === "und") &&
                  (!request.after || r.recordId > String(request.after)),
              )
              .sort((a, b) => a.recordId.localeCompare(b.recordId));
            const page = matching.slice(0, 10);
            return {
              kind: "page",
              value: {
                scopeId: request.scopeId,
                records: structuredClone(page),
                nextCursor: matching.length > 10 ? page.at(-1)!.recordId : null,
              },
            };
          }
          if (request.action === "create") {
            const mutationId = `${request.scopeId}:${request.mutationId}`;
            let term = replay.get(mutationId);
            if (!term) {
              term = {
                scopeId: String(request.scopeId),
                recordId: `term-${String(records.length + 1).padStart(5, "0")}`,
                locale: String(request.locale),
                canonicalForm: String(request.canonicalForm),
                variants: request.variants as string[],
                sensitivity: String(request.sensitivity),
                version: 1,
                changedAt: "2026-10-02T12:00:00Z",
              };
              records.push(term);
              replay.set(mutationId, structuredClone(term));
            }
            if (fixture.mode === "lostResponse") {
              fixture.mode = "ok";
              throw { code: "unavailable", retryable: true };
            }
            if (fixture.mode === "reloadFails") fixture.mode = "listFailure";
            return { kind: "record", value: structuredClone(term) };
          }
          const term = records.find(
            (r) =>
              r.recordId === request.recordId && r.scopeId === request.scopeId,
          );
          if (!term) throw { code: "notFound", retryable: false };
          if (request.action === "read")
            return { kind: "record", value: structuredClone(term) };
          if (fixture.mode === "conflict") {
            term.version += 1;
            term.canonicalForm = "Saved elsewhere";
            fixture.mode = "ok";
          }
          if (request.expectedVersion !== term.version)
            throw { code: "conflict", retryable: false };
          term.version += 1;
          if (request.action === "delete") {
            records.splice(records.indexOf(term), 1);
            return {
              kind: "deleted",
              value: {
                scopeId: term.scopeId,
                recordId: term.recordId,
                version: term.version,
                deleted: true,
              },
            };
          }
          term.canonicalForm = String(request.canonicalForm);
          term.variants = request.variants as string[];
          term.sensitivity = String(request.sensitivity);
          return { kind: "record", value: structuredClone(term) };
        })();
        if (startedRevision !== fixture.authorityRevision)
          throw { code: "identityChanged", retryable: false };
        return { authorityRevision: startedRevision, response };
      };
    },
    {
      shared: options.shared ?? false,
      teamCanManage: options.teamCanManage ?? true,
      organizationCanManage: options.organizationCanManage ?? false,
      count: options.count ?? 0,
      state: options.state ?? "ready",
      capability: options.capability ?? true,
      primaryLocale: options.primaryLocale,
    },
  );
}
