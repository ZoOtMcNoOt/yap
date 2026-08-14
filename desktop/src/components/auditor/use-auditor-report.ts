import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  auditorReportIsActive,
  auditorReportStatus,
  cancelAuditorReport,
  startAuditorReport,
  type AuditorReportJobView,
} from "@/auditor";

const pollIntervalMs = 1_000;
const maximumFindings = 3;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function auditorStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: AuditorReportJobView;
}) {
  if (starting) return "Submitting a permission-safe audit focus…";
  if (!available && !view) return "Connect to your organization server with Auditor enabled.";
  switch (view?.status) {
    case "queued":
      return "Waiting for idle complex-route capacity…";
    case "running":
      return "Reviewing current, permission-safe knowledge for potential conflicts…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "complete":
      return "A noncanonical source-cited report is ready for review.";
    case "evidence-unavailable":
      return "No permission-safe review finding is available for that focus.";
    case "cancelled":
      return "Audit-report request cancelled.";
    case "failed":
      return "The organization audit-report request could not complete.";
    default:
      return "Describe a focus to review current knowledge for source-cited conflicts.";
  }
}

function validFocus(value: string) {
  const focus = value.trim();
  return focus.length > 0
    && [...focus].length <= 1_024
    && [...focus].some((character) => /[\p{L}\p{N}]/u.test(character));
}

export function useAuditorReport({ available }: { available: boolean }) {
  const [focus, setFocus] = useState("");
  const [view, setView] = useState<AuditorReportJobView>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedFocusRef = useRef("");

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelAuditorReport(requestId).catch((cause) => {
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
        const next = await auditorReportStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!auditorReportIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") setError("The server could not complete this audit report.");
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch) return;
        activeRequestRef.current = undefined;
        void cancelAuditorReport(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const submit = useCallback(async (requestedFocus: string) => {
    const normalized = requestedFocus.trim();
    if (!available || !validFocus(normalized) || startPendingRef.current || activeRequestRef.current) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedFocusRef.current = normalized;
    try {
      const next = await startAuditorReport(normalized, maximumFindings, null);
      if (epochRef.current !== epoch) {
        if (auditorReportIsActive(next.status)) void cancelAuditorReport(next.requestId).catch(() => undefined);
        return;
      }
      setView(next);
      if (auditorReportIsActive(next.status)) {
        activeRequestRef.current = next.requestId;
        void pollUntilTerminal(next.requestId, epoch);
      } else if (next.status === "failed") {
        setError("The server could not complete this audit report.");
      }
    } catch (cause) {
      if (epochRef.current === epoch) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      startPendingRef.current = false;
      if (epochRef.current === epoch) setStarting(false);
    }
  }, [available, pollUntilTerminal]);

  const run = useCallback(() => submit(focus), [focus, submit]);
  const retry = useCallback(() => submit(lastSubmittedFocusRef.current || focus), [focus, submit]);
  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    try {
      const next = await cancelAuditorReport(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!auditorReportIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      cancelPendingRef.current = false;
    }
  }, []);

  const active = starting || (view ? auditorReportIsActive(view.status) : false);
  const statusLine = useMemo(
    () => auditorStatusLine({ available, starting, view }),
    [available, starting, view],
  );
  return {
    active,
    canRun: available && validFocus(focus) && !active,
    cancel,
    error,
    focus,
    report: view?.status === "complete" ? view.report ?? undefined : undefined,
    retry,
    run,
    setFocus,
    statusLine,
    view,
  };
}
