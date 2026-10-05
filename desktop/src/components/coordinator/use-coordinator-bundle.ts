import { useRequestLifecycle } from "@/hooks/use-request-lifecycle";

import { useCallback, useRef, useState } from "react";

import {
  cancelCoordinatorBundle,
  coordinatorBundleIsActive,
  coordinatorBundleStatus,
  startCoordinatorBundle,
  type CoordinatorBundleJobView,
} from "@/coordinator";

const maximumItems = 3;

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
  return (
    objective.length > 0 &&
    [...objective].length <= 1_024 &&
    [...objective].some((character) => /[\p{L}\p{N}]/u.test(character))
  );
}

export function useCoordinatorBundle({
  available,
  authorityRevision,
}: {
  available: boolean;
  authorityRevision: string;
}) {
  const [objective, setObjective] = useState("");
  const lastSubmittedObjectiveRef = useRef("");
  const resetDraft = useCallback(() => {
    setObjective("");
    lastSubmittedObjectiveRef.current = "";
  }, []);
  const {
    active,
    cancel,
    cancelling,
    current,
    error,
    ownsDraft,
    starting,
    submit: submitRequest,
    view,
  } = useRequestLifecycle<CoordinatorBundleJobView>({
    available,
    authorityRevision,
    resetDraft,
    status: coordinatorBundleStatus,
    cancelRequest: cancelCoordinatorBundle,
    isActive: coordinatorBundleIsActive,
    failureMessage: "The server could not complete this coordination bundle.",
  });

  const submit = useCallback(
    async (requestedObjective: string) => {
      const normalized = requestedObjective.trim();
      if (!current || !validObjective(normalized)) return;
      await submitRequest(() => {
        lastSubmittedObjectiveRef.current = normalized;
        return startCoordinatorBundle(
          normalized,
          maximumItems,
          null,
          authorityRevision,
        );
      });
    },
    [authorityRevision, current, submitRequest],
  );

  const run = useCallback(() => submit(objective), [objective, submit]);
  const retry = useCallback(
    () => submit(lastSubmittedObjectiveRef.current || objective),
    [objective, submit],
  );

  const statusLine = cancelling
    ? "Waiting for cancellation acknowledgement…"
    : coordinatorStatusLine({ available, starting, view });

  return {
    active,
    bundle:
      view?.status === "complete"
        ? (view.proposalBundle ?? undefined)
        : undefined,
    canRun: current && validObjective(objective) && !active,
    cancel,
    error,
    objective: ownsDraft ? objective : "",
    retry,
    run,
    setObjective,
    statusLine,
    view,
  };
}
