import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

export function useLibrarianQuery({ available }: { available: boolean }) {
  const [searchText, setSearchText] = useState("");
  const [view, setView] = useState<LibrarianQueryJobView>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedTextRef = useRef("");

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelLibrarianQuery(requestId).catch((cause) => {
      if (showError) setError(cause instanceof Error ? cause.message : String(cause));
    });
  }, []);

  useEffect(() => () => {
    epochRef.current += 1;
    abandonActiveRequest(false);
  }, [abandonActiveRequest]);

  useEffect(() => {
    if (available) return;
    epochRef.current += 1;
    abandonActiveRequest(false);
    setView(undefined);
    setStarting(false);
    setError("");
  }, [abandonActiveRequest, available]);

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
      !available
      || !validSearchText(normalized)
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
      const next = await startLibrarianQuery(normalized, maximumResults, null);
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
      if (epochRef.current === epoch) setStarting(false);
    }
  }, [available, pollUntilTerminal]);

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
    }
  }, []);

  const active = starting || (view ? librarianQueryIsActive(view.status) : false);
  const statusLine = useMemo(
    () => librarianStatusLine({ available, starting, view }),
    [available, starting, view],
  );

  return {
    active,
    canRun: available && validSearchText(searchText) && !active,
    cancel,
    error,
    evidence: view?.status === "complete" ? view.evidencePack ?? undefined : undefined,
    retry,
    run,
    searchText,
    setSearchText,
    statusLine,
    view,
  };
}
