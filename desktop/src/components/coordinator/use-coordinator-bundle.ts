import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelCoordinatorBundle,
  coordinatorBundleIsActive,
  coordinatorBundleStatus,
  startCoordinatorBundle,
  type CoordinatorBundleJobView,
} from "@/coordinator";

const pollIntervalMs = 1_000;
const maximumItems = 3;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function coordinatorStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: CoordinatorBundleJobView;
}) {
  if (starting) return "Submitting a permission-safe coordination objective…";
  if (!available && !view) {
    return "Connect to your organization server with Coordinator enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared coordination route…";
    case "running":
      return "Selecting only current, source-cited reviewed proposals…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "complete":
      return "A noncanonical proposal bundle is ready for review.";
    case "evidence-unavailable":
      return "No permission-safe reviewed proposal bundle is available for that objective.";
    case "cancelled":
      return "Coordination-bundle request cancelled.";
    case "failed":
      return "The organization coordination-bundle request could not complete.";
    default:
      return "Describe an objective to select a source-cited bundle for human review.";
  }
}

function validObjective(value: string) {
  const objective = value.trim();
  return objective.length > 0
    && [...objective].length <= 1_024
    && [...objective].some((character) => /[\p{L}\p{N}]/u.test(character));
}

export function useCoordinatorBundle({ available }: { available: boolean }) {
  const [objective, setObjective] = useState("");
  const [view, setView] = useState<CoordinatorBundleJobView>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedObjectiveRef = useRef("");

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelCoordinatorBundle(requestId).catch((cause) => {
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
        const next = await coordinatorBundleStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!coordinatorBundleIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") {
            setError("The server could not complete this coordination bundle.");
          }
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch) return;
        activeRequestRef.current = undefined;
        void cancelCoordinatorBundle(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const submit = useCallback(async (requestedObjective: string) => {
    const normalized = requestedObjective.trim();
    if (
      !available
      || !validObjective(normalized)
      || startPendingRef.current
      || activeRequestRef.current
    ) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedObjectiveRef.current = normalized;
    try {
      const next = await startCoordinatorBundle(normalized, maximumItems, null);
      if (epochRef.current !== epoch) {
        if (coordinatorBundleIsActive(next.status)) {
          void cancelCoordinatorBundle(next.requestId).catch(() => undefined);
        }
        return;
      }
      setView(next);
      if (coordinatorBundleIsActive(next.status)) {
        activeRequestRef.current = next.requestId;
        void pollUntilTerminal(next.requestId, epoch);
      } else if (next.status === "failed") {
        setError("The server could not complete this coordination bundle.");
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

  const run = useCallback(() => submit(objective), [objective, submit]);
  const retry = useCallback(
    () => submit(lastSubmittedObjectiveRef.current || objective),
    [objective, submit],
  );

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    try {
      const next = await cancelCoordinatorBundle(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!coordinatorBundleIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      cancelPendingRef.current = false;
    }
  }, []);

  const active = starting || (view ? coordinatorBundleIsActive(view.status) : false);
  const statusLine = useMemo(
    () => coordinatorStatusLine({ available, starting, view }),
    [available, starting, view],
  );

  return {
    active,
    bundle: view?.status === "complete" ? view.proposalBundle ?? undefined : undefined,
    canRun: available && validObjective(objective) && !active,
    cancel,
    error,
    objective,
    retry,
    run,
    setObjective,
    statusLine,
    view,
  };
}
