import { useEffect, useRef, useState } from "react";
import {
  terminology,
  terminologyError,
  type Term,
  type TerminologyScope,
  type TerminologyRequest,
  type Sensitivity,
} from "@/terminology";
import type { ServerConnectionSnapshot } from "@/server";

export type TermDraft = {
  scopeId: string;
  authorityRevision: string;
  recordId?: string;
  expectedVersion?: number;
  locale: string;
  canonicalForm: string;
  variantsText: string;
  sensitivity: Sensitivity;
};
export type TerminologyControl = ReturnType<typeof useTerminology>;

export function useTerminology(
  active: boolean,
  snapshot: ServerConnectionSnapshot,
  initialLocale: string,
) {
  const [scopeId, setScopeId] = useState("personal");
  const [authorityRevision, setAuthorityRevision] = useState<string | null>(
    null,
  );
  const [scopes, setScopes] = useState<TerminologyScope[]>([]);
  const scope = scopes.find((s) => s.scopeId === scopeId);
  const canManage = scope?.canManage ?? false;
  const [locale, setLocale] = useState(initialLocale);
  const [records, setRecords] = useState<Term[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [draft, setDraft] = useState<TermDraft | null>(null);
  const [deleting, setDeleting] = useState<Term | null>(null);
  const [latest, setLatest] = useState<Term | null>(null);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingAction, setPendingAction] = useState<
    "load" | "save" | "compare" | "delete" | null
  >(null);
  const pending = pendingAction !== null;
  const [loaded, setLoaded] = useState(false);
  const running = useRef(false);
  const localeChosen = useRef(false);
  const epoch = useRef(0);
  const creation = useRef<{ signature: string; mutationId: string } | null>(
    null,
  );
  const available =
    snapshot.state === "ready" && snapshot.capabilities.personalTerminology;
  const accountUnavailable = [
    "sign_in_required",
    "access_denied",
    "disabled",
    "not_set",
  ].includes(snapshot.state);

  useEffect(() => {
    epoch.current += 1;
    setAuthorityRevision(null);
    setScopes([]);
    setRecords([]);
    setNextCursor(null);
    setLoaded(false);
    setLatest(null);
    setNotice("");
    if (accountUnavailable) {
      setScopeId("personal");
      setDraft(null);
      setDeleting(null);
      setConflict(false);
      setError("");
      creation.current = null;
    }
  }, [
    snapshot.state,
    snapshot.capabilities.personalTerminology,
    accountUnavailable,
  ]);

  useEffect(() => {
    if (
      !localeChosen.current &&
      !draft &&
      !pending &&
      initialLocale !== locale
    ) {
      epoch.current += 1;
      setLocale(initialLocale);
      setLoaded(false);
      setRecords([]);
      setNextCursor(null);
      setError("");
    }
  }, [initialLocale, locale, draft, pending]);

  async function run(
    operation: (current: () => boolean) => Promise<void>,
    action: "load" | "save" | "compare" | "delete" = "load",
  ) {
    if (running.current || !available) return;
    running.current = true;
    setPendingAction(action);
    setError("");
    setNotice("");
    const started = epoch.current;
    const current = () => started === epoch.current;
    try {
      await operation(current);
    } catch (failure) {
      if (current()) {
        const failureView = terminologyError(failure);
        setError(failureView.message);
        setConflict(failureView.conflict);
      }
    } finally {
      running.current = false;
      setPendingAction(null);
    }
  }

  async function loadPage(
    after: string | null,
    current: () => boolean,
    revision = authorityRevision,
  ) {
    const response = await terminology(
      {
        action: "list",
        scopeId,
        locale,
        after,
      },
      revision,
    );
    if (
      response.kind !== "page" ||
      response.value.scopeId !== scopeId ||
      response.value.records.some((r) => r.scopeId !== scopeId)
    )
      throw { code: "invalidResponse" };
    if (!current()) return;
    setRecords((previous) =>
      after ? [...previous, ...response.value.records] : response.value.records,
    );
    setNextCursor(response.value.nextCursor);
    setLoaded(true);
  }

  function refresh() {
    return run(async (current) => {
      const response = await terminology({ action: "discover" });
      if (response.kind !== "scopes") throw { code: "invalidResponse" };
      if (!current()) return;
      const revision = response.value.authorityRevision;
      if (draft && draft.authorityRevision !== revision) {
        setDraft(null);
        setDeleting(null);
        setLatest(null);
        setConflict(false);
        creation.current = null;
        setNotice(
          "Your server or sign-in changed. The previous draft was cleared; review this connection before adding terms.",
        );
      }
      setAuthorityRevision(revision);
      setScopes(response.value.scopes);
      const selected = response.value.scopes.find((s) => s.scopeId === scopeId);
      if (!selected) {
        setRecords([]);
        setNextCursor(null);
        setLoaded(false);
        setError(
          "Your access to this scope changed. Cancel any draft and choose another scope, or retry Refresh terms.",
        );
        return;
      }
      await loadPage(null, current, revision);
    });
  }
  function more() {
    return nextCursor
      ? run((current) => loadPage(nextCursor, current))
      : Promise.resolve();
  }

  useEffect(() => {
    if (active && available && !loaded && !pending && !error) void refresh();
  }, [active, available, loaded, pending, error, locale, scopeId]);

  function changeLocale(value: string) {
    if (running.current || draft) return;
    localeChosen.current = true;
    epoch.current += 1;
    setLocale(value);
    setLoaded(false);
    setRecords([]);
    setNextCursor(null);
    setError("");
  }

  function changeScope(value: string) {
    if (
      running.current ||
      draft ||
      deleting ||
      !scopes.some((s) => s.scopeId === value)
    )
      return;
    epoch.current += 1;
    setScopeId(value);
    setLoaded(false);
    setRecords([]);
    setNextCursor(null);
    setLatest(null);
    setConflict(false);
    setError("");
    setNotice("");
    creation.current = null;
  }

  function start(term?: Term) {
    if (
      running.current ||
      !authorityRevision ||
      !canManage ||
      (term && term.scopeId !== scopeId)
    )
      return;
    localeChosen.current = true;
    setDraft(
      term
        ? {
            scopeId,
            authorityRevision: authorityRevision!,
            recordId: term.recordId,
            expectedVersion: term.version,
            locale: term.locale,
            canonicalForm: term.canonicalForm,
            variantsText: term.variants.join("\n"),
            sensitivity: term.sensitivity,
          }
        : {
            authorityRevision: authorityRevision!,
            scopeId,
            locale,
            canonicalForm: "",
            variantsText: "",
            sensitivity: "internal",
          },
    );
    setLatest(null);
    setConflict(false);
    setError("");
    setNotice("");
    creation.current = null;
  }

  function cancel() {
    if (running.current) return;
    setDraft(null);
    setLatest(null);
    setConflict(false);
    setError("");
    creation.current = null;
  }

  function save() {
    if (
      !draft ||
      !canManage ||
      draft.scopeId !== scopeId ||
      draft.authorityRevision !== authorityRevision
    )
      return Promise.resolve();
    const canonicalForm = draft.canonicalForm.trim();
    const variants = draft.variantsText
      .split(/\r?\n/)
      .map((v) => v.trim())
      .filter(Boolean);
    if (
      !canonicalForm ||
      [...canonicalForm].length > 512 ||
      variants.length < 1 ||
      variants.length > 64 ||
      variants.some((v) => [...v].length > 512) ||
      new Set(variants.map((v) => v.toLocaleLowerCase())).size !==
        variants.length
    ) {
      setError(
        "Enter a preferred spelling and 1–64 distinct variants, up to 512 characters each.",
      );
      return Promise.resolve();
    }
    const content = { canonicalForm, variants, sensitivity: draft.sensitivity };
    let request: TerminologyRequest;
    if (draft.recordId && draft.expectedVersion)
      request = {
        action: "edit",
        scopeId,
        recordId: draft.recordId,
        expectedVersion: draft.expectedVersion,
        ...content,
      };
    else {
      const signature = JSON.stringify({
        scopeId,
        locale: draft.locale,
        ...content,
      });
      if (creation.current?.signature !== signature)
        creation.current = { signature, mutationId: crypto.randomUUID() };
      request = {
        action: "create",
        scopeId,
        mutationId: creation.current.mutationId,
        locale: draft.locale,
        ...content,
      };
    }
    return run(async (current) => {
      const response = await terminology(request, draft.authorityRevision);
      if (response.kind !== "record" || response.value.scopeId !== scopeId)
        throw { code: "invalidResponse" };
      if (!current()) return;
      setDraft(null);
      setLatest(null);
      setConflict(false);
      creation.current = null;
      setNotice("Term saved. Existing jobs keep their original terminology.");
      try {
        await loadPage(null, current);
      } catch {
        if (current())
          setError(
            "Term saved, but the list could not refresh. Retry Refresh terms.",
          );
      }
    }, "save");
  }

  function compareLatest() {
    if (!draft?.recordId) return Promise.resolve();
    const recordId = draft.recordId;
    return run(async (current) => {
      const response = await terminology(
        { action: "read", scopeId, recordId },
        draft.authorityRevision,
      );
      if (response.kind !== "record" || response.value.scopeId !== scopeId)
        throw { code: "invalidResponse" };
      if (current()) {
        setLatest(response.value);
        setConflict(true);
      }
    }, "compare");
  }

  function applyDraftToLatest() {
    if (!latest || running.current) return;
    setDraft((previous) =>
      previous ? { ...previous, expectedVersion: latest.version } : null,
    );
    setLatest(null);
    setConflict(false);
    setError("");
    setNotice(
      "Draft retained against the latest version. Review it, then save.",
    );
  }

  function remove() {
    if (!deleting || !canManage || deleting.scopeId !== scopeId)
      return Promise.resolve();
    const term = deleting;
    return run(async (current) => {
      const response = await terminology(
        {
          action: "delete",
          scopeId,
          recordId: term.recordId,
          expectedVersion: term.version,
        },
        authorityRevision,
      );
      if (response.kind !== "deleted" || response.value.scopeId !== scopeId)
        throw { code: "invalidResponse" };
      if (!current()) return;
      setDeleting(null);
      setNotice("Term deleted. Existing jobs keep their original terminology.");
      setRecords((previous) =>
        previous.filter((record) => record.recordId !== term.recordId),
      );
      try {
        await loadPage(null, current);
      } catch {
        if (current())
          setError(
            "Term deleted, but the list could not refresh. Retry Refresh terms.",
          );
      }
    }, "delete");
  }

  return {
    scopeId,
    scopes,
    scope,
    canManage,
    changeScope,
    available,
    accountUnavailable,
    records,
    nextCursor,
    draft,
    setDraft,
    deleting,
    setDeleting,
    latest,
    conflict,
    error,
    notice,
    pending,
    pendingAction,
    loaded,
    locale,
    changeLocale,
    refresh,
    more,
    start,
    cancel,
    save,
    remove,
    compareLatest,
    applyDraftToLatest,
  };
}
