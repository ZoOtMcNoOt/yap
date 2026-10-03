import { useConnectionAuthority } from "@/hooks/use-connection-authority";

import { useCallback, useEffect, useRef, useState } from "react";

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

export function useAuditorReport({ available, authorityRevision }: { available: boolean; authorityRevision: string }) {
  const [focus, setFocus] = useState("");
  const [view, setView] = useState<AuditorReportJobView>();
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedFocusRef = useRef("");

  const abandonActiveRequest = useCallback(() => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId || cancelPendingRef.current) return;
    void cancelAuditorReport(requestId).catch(() => undefined);
  }, []);

  useEffect(() => () => {
    epochRef.current += 1;
    abandonActiveRequest();
  }, [abandonActiveRequest]);

  const invalidate = useCallback((changed: boolean) => {
    epochRef.current += 1;
    abandonActiveRequest();
    if (changed) {
      setFocus("");
      lastSubmittedFocusRef.current = "";
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
    if (!current || !validFocus(normalized) || cancelPendingRef.current || startPendingRef.current || activeRequestRef.current) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedFocusRef.current = normalized;
    try {
      const next = await startAuditorReport(normalized, maximumFindings, null, authorityRevision);
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
      setStarting(false);
    }
  }, [authorityRevision, current, pollUntilTerminal]);

  const run = useCallback(() => submit(focus), [focus, submit]);
  const retry = useCallback(() => submit(lastSubmittedFocusRef.current || focus), [focus, submit]);
  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    setCancelling(true);
    try {
      const next = await cancelAuditorReport(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!auditorReportIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      cancelPendingRef.current = false;
      setCancelling(false);
    }
  }, []);

  const active = starting || cancelling || (currentView ? auditorReportIsActive(currentView.status) : false);
  const statusLine = cancelling
    ? "Waiting for cancellation acknowledgement…"
    : auditorStatusLine({ available, starting, view: currentView });

  return {
    active,
    canRun: current && validFocus(focus) && !active,
    cancel,
    error: current ? error : "",
    focus: ownsDraft ? focus : "",
    report: currentView?.status === "complete" ? currentView.report ?? undefined : undefined,
    retry,
    run,
    setFocus,
    statusLine,
    view: currentView,
  };
}
