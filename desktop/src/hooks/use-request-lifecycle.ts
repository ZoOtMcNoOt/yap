import { useCallback, useEffect, useRef, useState } from "react";

import { useConnectionAuthority } from "@/hooks/use-connection-authority";

const pollIntervalMs = 1_000;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

// Own the asynchronous request, while callers own their draft, validation and
// native submission arguments. Pending starts/cancellations remain blocked
// across authority changes until their original native calls settle.
export function useRequestLifecycle<
  View extends { requestId: string; status: string },
>({
  available,
  authorityRevision,
  resetDraft,
  status,
  cancelRequest,
  isActive,
  failureMessage,
}: {
  available: boolean;
  authorityRevision: string;
  resetDraft: () => void;
  status: (requestId: string) => Promise<View>;
  cancelRequest: (requestId: string) => Promise<View>;
  isActive: (status: View["status"]) => boolean;
  failureMessage: string;
}) {
  const [view, setView] = useState<View>();
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const mountedRef = useRef(true);

  const abandonActiveRequest = useCallback(() => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId || cancelPendingRef.current) return;
    void cancelRequest(requestId).catch(() => undefined);
  }, [cancelRequest]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      epochRef.current += 1;
      abandonActiveRequest();
    };
  }, [abandonActiveRequest]);

  const invalidate = useCallback(
    (changed: boolean) => {
      epochRef.current += 1;
      abandonActiveRequest();
      if (changed) resetDraft();
      setView(undefined);
      setError("");
    },
    [abandonActiveRequest, resetDraft],
  );
  const ownsDraft = useConnectionAuthority(
    available,
    authorityRevision,
    invalidate,
  );
  const current = available && ownsDraft;
  const currentView = current ? view : undefined;

  const pollUntilTerminal = useCallback(
    async (requestId: string, epoch: number) => {
      const ownsRequest = () =>
        activeRequestRef.current === requestId && epochRef.current === epoch;
      while (ownsRequest()) {
        await pause(pollIntervalMs);
        if (!ownsRequest()) return;
        try {
          const next = await status(requestId);
          // A terminal cancellation may settle while this status call is pending.
          if (!ownsRequest()) return;
          setView(next);
          if (!isActive(next.status)) {
            activeRequestRef.current = undefined;
            if (next.status === "failed") setError(failureMessage);
            return;
          }
        } catch (cause) {
          if (!ownsRequest()) return;
          activeRequestRef.current = undefined;
          void cancelRequest(requestId).catch(() => undefined);
          setError(cause instanceof Error ? cause.message : String(cause));
          return;
        }
      }
    },
    [cancelRequest, failureMessage, isActive, status],
  );

  const submit = useCallback(
    async (start: () => Promise<View>) => {
      if (
        !current ||
        !mountedRef.current ||
        cancelPendingRef.current ||
        startPendingRef.current ||
        activeRequestRef.current
      )
        return;
      startPendingRef.current = true;
      const epoch = ++epochRef.current;
      setStarting(true);
      setView(undefined);
      setError("");
      try {
        const next = await start();
        if (epochRef.current !== epoch) {
          if (isActive(next.status))
            void cancelRequest(next.requestId).catch(() => undefined);
          return;
        }
        setView(next);
        if (isActive(next.status)) {
          activeRequestRef.current = next.requestId;
          void pollUntilTerminal(next.requestId, epoch);
        } else if (next.status === "failed") {
          setError(failureMessage);
        }
      } catch (cause) {
        if (epochRef.current === epoch)
          setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        startPendingRef.current = false;
        if (mountedRef.current) setStarting(false);
      }
    },
    [cancelRequest, current, failureMessage, isActive, pollUntilTerminal],
  );

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    setCancelling(true);
    try {
      const next = await cancelRequest(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!isActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch)
        setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      cancelPendingRef.current = false;
      if (mountedRef.current) setCancelling(false);
    }
  }, [cancelRequest, isActive]);

  return {
    active:
      starting ||
      cancelling ||
      (currentView ? isActive(currentView.status) : false),
    cancel,
    cancelling,
    current,
    error: current ? error : "",
    ownsDraft,
    starting,
    submit,
    view: currentView,
  };
}
