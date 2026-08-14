import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  archivistIngestionIsActive,
  archivistIngestionStatus,
  cancelArchivistIngestion,
  startArchivistIngestion,
  type ArchivistIngestionJobView,
} from "@/archivist";

const pollIntervalMs = 1_000;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function archivistStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: ArchivistIngestionJobView;
}) {
  if (starting) return "Submitting this reviewed transcript for knowledge staging…";
  if (!available && !view) {
    return "Connect to the transcript's organization server with Archivist enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared knowledge staging route…";
    case "running":
      return "Reviewing and staging a new knowledge generation…";
    case "cancellation-requested":
      return "Waiting for knowledge staging cancellation…";
    case "staged":
      return "Staged for review. The knowledge generation was not activated.";
    case "cancelled":
      return "Knowledge staging cancelled.";
    case "failed":
      return "This transcript could not be staged for knowledge.";
    default:
      return "Stage this reviewed server transcript without activating it.";
  }
}

export function useArchivistIngestion({
  available,
  recordingId,
}: {
  available: boolean;
  recordingId?: string;
}) {
  const [view, setView] = useState<ArchivistIngestionJobView>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelArchivistIngestion(requestId).catch((cause) => {
      if (showError) setError(cause instanceof Error ? cause.message : String(cause));
    });
  }, []);

  useEffect(() => () => {
    epochRef.current += 1;
    abandonActiveRequest(false);
  }, [abandonActiveRequest]);

  useEffect(() => {
    epochRef.current += 1;
    abandonActiveRequest(false);
    setView(undefined);
    setStarting(false);
    setError("");
  }, [abandonActiveRequest, available, recordingId]);

  const pollUntilTerminal = useCallback(async (requestId: string, epoch: number) => {
    while (activeRequestRef.current === requestId) {
      await pause(pollIntervalMs);
      if (activeRequestRef.current !== requestId || epochRef.current !== epoch) return;
      try {
        const next = await archivistIngestionStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!archivistIngestionIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") {
            setError("The organization server could not stage this transcript.");
          }
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch) return;
        activeRequestRef.current = undefined;
        void cancelArchivistIngestion(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const stage = useCallback(async () => {
    if (!available || !recordingId || startPendingRef.current || activeRequestRef.current) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    try {
      const next = await startArchivistIngestion(recordingId);
      if (epochRef.current !== epoch) {
        if (archivistIngestionIsActive(next.status)) {
          void cancelArchivistIngestion(next.requestId).catch(() => undefined);
        }
        return;
      }
      setView(next);
      if (archivistIngestionIsActive(next.status)) {
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
  }, [available, pollUntilTerminal, recordingId]);

  const active = starting || (view ? archivistIngestionIsActive(view.status) : false);
  const statusLine = useMemo(
    () => archivistStatusLine({ available, starting, view }),
    [available, starting, view],
  );

  return {
    active,
    canStage: available && Boolean(recordingId) && !active && view?.status !== "staged",
    error,
    stage,
    statusLine,
    view,
  };
}
