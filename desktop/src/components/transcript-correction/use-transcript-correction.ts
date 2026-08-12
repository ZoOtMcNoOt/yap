import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { isRecordingFinished, type RecordingJobView } from "@/lib/recording-job";
import {
  cancelTranscriptCorrection,
  publishTranscriptCorrection,
  startTranscriptCorrection,
  transcriptCorrectionIsActive,
  transcriptCorrectionStatus,
  type PublishedTranscriptCorrection,
  type TranscriptCorrectionJobView,
} from "@/transcript-correction";

const pollIntervalMs = 1_000;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

function correctionStatusLine({
  available,
  ready,
  view,
}: {
  available: boolean;
  ready: boolean;
  view?: TranscriptCorrectionJobView;
}) {
  if (!ready) return "Select a finished transcript to correct.";
  if (!available && !view) {
    return "Connect to your organization server with transcript correction enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared warm correction route…";
    case "running":
      return "Applying source-bound corrections…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "cancelled":
      return "Correction cancelled. Raw transcript unchanged.";
    case "failed":
      return "Correction failed. Raw transcript unchanged.";
    case "complete":
      return view.applied
        ? "Correction ready. Review the changes before saving."
        : "No safe correction was accepted. Raw transcript unchanged.";
    default:
      return "Ready for a source-bound correction.";
  }
}

export function useTranscriptCorrection({
  available,
  item,
}: {
  available: boolean;
  item?: RecordingJobView;
}) {
  const outputPath = item?.outputPath ?? "";
  const ready = Boolean(outputPath && isRecordingFinished(item?.status));
  const contextRef = useRef(outputPath);
  const epochRef = useRef(0);
  const activeRequestRef = useRef<string | undefined>(undefined);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const publishPendingRef = useRef(false);
  const [view, setView] = useState<TranscriptCorrectionJobView>();
  const [published, setPublished] = useState<PublishedTranscriptCorrection>();
  const [starting, setStarting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState("");

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelTranscriptCorrection(requestId).catch((cause) => {
      if (showError) toast.error(cause instanceof Error ? cause.message : String(cause));
    });
  }, []);

  useEffect(() => {
    contextRef.current = outputPath;
    epochRef.current += 1;
    abandonActiveRequest(false);
    setView(undefined);
    setPublished(undefined);
    setStarting(false);
    setPublishing(false);
    setError("");
    return () => {
      epochRef.current += 1;
      abandonActiveRequest(false);
    };
  }, [abandonActiveRequest, outputPath]);

  const pollUntilTerminal = useCallback(async (
    requestId: string,
    requestedPath: string,
    epoch: number,
  ) => {
    while (activeRequestRef.current === requestId) {
      await pause(pollIntervalMs);
      if (
        activeRequestRef.current !== requestId
        || epochRef.current !== epoch
        || contextRef.current !== requestedPath
      ) return;
      try {
        const next = await transcriptCorrectionStatus(requestId);
        if (epochRef.current !== epoch || contextRef.current !== requestedPath) return;
        setView(next);
        if (!transcriptCorrectionIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") setError("The server could not safely correct this transcript.");
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch || contextRef.current !== requestedPath) return;
        activeRequestRef.current = undefined;
        void cancelTranscriptCorrection(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const run = useCallback(async () => {
    if (
      !available
      || !ready
      || !outputPath
      || starting
      || startPendingRef.current
      || activeRequestRef.current
    ) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    const requestedPath = outputPath;
    setStarting(true);
    setView(undefined);
    setPublished(undefined);
    setError("");
    try {
      const next = await startTranscriptCorrection(requestedPath);
      if (epochRef.current !== epoch || contextRef.current !== requestedPath) {
        if (transcriptCorrectionIsActive(next.status)) {
          void cancelTranscriptCorrection(next.requestId).catch(() => undefined);
        }
        return;
      }
      setView(next);
      if (transcriptCorrectionIsActive(next.status)) {
        activeRequestRef.current = next.requestId;
        void pollUntilTerminal(next.requestId, requestedPath, epoch);
      }
    } catch (cause) {
      if (epochRef.current === epoch && contextRef.current === requestedPath) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      startPendingRef.current = false;
      if (epochRef.current === epoch && contextRef.current === requestedPath) setStarting(false);
    }
  }, [available, outputPath, pollUntilTerminal, ready, starting]);

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    const requestedPath = contextRef.current;
    cancelPendingRef.current = true;
    try {
      const next = await cancelTranscriptCorrection(requestId);
      if (epochRef.current !== epoch || contextRef.current !== requestedPath) return;
      setView(next);
      if (!transcriptCorrectionIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current !== epoch || contextRef.current !== requestedPath) return;
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      cancelPendingRef.current = false;
    }
  }, []);

  const publish = useCallback(async () => {
    if (
      !view
      || view.status !== "complete"
      || !view.applied
      || published
      || publishing
      || publishPendingRef.current
    ) return;
    const epoch = epochRef.current;
    const requestedPath = contextRef.current;
    publishPendingRef.current = true;
    setPublishing(true);
    setError("");
    try {
      const revision = await publishTranscriptCorrection(view.requestId);
      if (epochRef.current !== epoch || contextRef.current !== requestedPath) return;
      setPublished(revision);
      toast.success(`Correction revision ${revision.revision} saved`);
    } catch (cause) {
      if (epochRef.current !== epoch || contextRef.current !== requestedPath) return;
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      toast.error(message);
    } finally {
      publishPendingRef.current = false;
      if (epochRef.current === epoch && contextRef.current === requestedPath) setPublishing(false);
    }
  }, [published, publishing, view]);

  const copy = useCallback(async () => {
    if (!view?.correctedText || view.status !== "complete") return;
    try {
      await navigator.clipboard.writeText(view.correctedText);
      toast.success("Corrected transcript copied");
    } catch {
      toast.error("Copy failed");
    }
  }, [view]);

  const statusLine = useMemo(
    () => correctionStatusLine({ available, ready, view }),
    [available, ready, view],
  );
  const active = starting || (view ? transcriptCorrectionIsActive(view.status) : false);

  return {
    active,
    canRun: available && ready && !active && !publishing,
    cancel,
    copy,
    correctedText: view?.status === "complete" ? view.correctedText ?? undefined : undefined,
    error,
    publish,
    published,
    publishing,
    ready,
    run,
    statusLine,
    view,
  };
}
