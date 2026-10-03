import { useConnectionAuthority } from "@/hooks/use-connection-authority";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelLibrarianQuery,
  librarianQueryIsActive,
  librarianQueryStatus,
  startLibrarianQuery,
  type LibrarianQueryJobView,
} from "@/librarian";

const pollIntervalMs = 1_000;
const maximumResults = 3;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function librarianStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: LibrarianQueryJobView;
}) {
  if (starting) return "Submitting a permission-safe knowledge query…";
  if (!available && !view) {
    return "Connect to your organization server with Librarian enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared knowledge route…";
    case "running":
      return "Searching the current authorized knowledge generation…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "complete":
      return "Permission-safe evidence is ready.";
    case "evidence-unavailable":
      return "No permission-safe evidence is available for that query.";
    case "cancelled":
      return "Knowledge query cancelled.";
    case "failed":
      return "The organization knowledge query could not complete.";
    default:
      return "Search reviewed organization knowledge without exposing hidden results.";
  }
}

function validSearchText(value: string) {
  const text = value.trim();
  return text.length > 0 && [...text].length <= 1_024 && [...text].some((character) => /[\p{L}\p{N}]/u.test(character));
}

export function useLibrarianQuery({ available, authorityRevision }: { available: boolean; authorityRevision: string }) {
  const [searchText, setSearchText] = useState("");
  const [view, setView] = useState<LibrarianQueryJobView>();
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedTextRef = useRef("");

  const abandonActiveRequest = useCallback(() => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId || cancelPendingRef.current) return;
    void cancelLibrarianQuery(requestId).catch(() => undefined);
  }, []);

  useEffect(() => () => {
    epochRef.current += 1;
    abandonActiveRequest();
  }, [abandonActiveRequest]);

  const invalidate = useCallback((changed: boolean) => {
    epochRef.current += 1;
    abandonActiveRequest();
    if (changed) {
      setSearchText("");
      lastSubmittedTextRef.current = "";
    }
    setView(undefined);
    setError("");
  }, [abandonActiveRequest]);
  const ownsDraft = useConnectionAuthority(available, authorityRevision, invalidate);
  const current = available && ownsDraft;
  const currentView = current ? view : undefined;

  const pollUntilTerminal = useCallback(async (requestId: string, epoch: number) => {
    while (activeRequestRef.current === requestId) {
      await pause(pollIntervalMs);
      if (activeRequestRef.current !== requestId || epochRef.current !== epoch) return;
      try {
        const next = await librarianQueryStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!librarianQueryIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") {
            setError("The server could not complete this permission-safe query.");
          }
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch) return;
        activeRequestRef.current = undefined;
        void cancelLibrarianQuery(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const submit = useCallback(async (requestedText: string) => {
    const normalized = requestedText.trim();
    if (
      !current
      || !validSearchText(normalized)
      || cancelPendingRef.current
      || startPendingRef.current
      || activeRequestRef.current
    ) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedTextRef.current = normalized;
    try {
      const next = await startLibrarianQuery(normalized, maximumResults, null, authorityRevision);
      if (epochRef.current !== epoch) {
        if (librarianQueryIsActive(next.status)) {
          void cancelLibrarianQuery(next.requestId).catch(() => undefined);
        }
        return;
      }
      setView(next);
      if (librarianQueryIsActive(next.status)) {
        activeRequestRef.current = next.requestId;
        void pollUntilTerminal(next.requestId, epoch);
      }
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      startPendingRef.current = false;
      setStarting(false);
    }
  }, [authorityRevision, current, pollUntilTerminal]);

  const run = useCallback(() => submit(searchText), [searchText, submit]);
  const retry = useCallback(
    () => submit(lastSubmittedTextRef.current || searchText),
    [searchText, submit],
  );

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    setCancelling(true);
    try {
      const next = await cancelLibrarianQuery(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!librarianQueryIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      cancelPendingRef.current = false;
      setCancelling(false);
    }
  }, []);

  const active = starting || cancelling || (currentView ? librarianQueryIsActive(currentView.status) : false);
  const statusLine = cancelling
    ? "Waiting for cancellation acknowledgement…"
    : librarianStatusLine({ available, starting, view: currentView });

  return {
    active,
    canRun: current && validSearchText(searchText) && !active,
    cancel,
    error: current ? error : "",
    evidence: currentView?.status === "complete" ? currentView.evidencePack ?? undefined : undefined,
    retry,
    run,
    searchText: ownsDraft ? searchText : "",
    setSearchText,
    statusLine,
    view: currentView,
  };
}
