import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelCuratorProposal,
  curatorProposalIsActive,
  curatorProposalStatus,
  startCuratorProposal,
  startConnectionProposal,
  type ConnectionProposalIntent,
  type CuratorProposalJobView,
} from "@/curator";
import { useConnectionAuthority } from "@/hooks/use-connection-authority";
import type { StudentQuestion } from "@/student";

const pollIntervalMs = 1_000;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function curatorStatusLine({
  available,
  starting,
  view,
  connection = false,
}: {
  available: boolean;
  starting: boolean;
  view?: CuratorProposalJobView;
  connection?: boolean;
}) {
  if (starting)
    return connection
      ? "Submitting both sources for connection review…"
      : "Submitting the reviewed answer for source validation…";
  if (!available && !view) {
    return "Connect to your organization server with Curator enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared review route…";
    case "running":
      return connection
        ? "Checking the connection against both cited sources…"
        : "Checking the reviewed answer against its exact source…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "proposed":
      return "A noncanonical proposal is ready for review.";
    case "rejected":
      return connection
        ? "Curator could not support this connection from both sources."
        : "Curator found the reviewed answer unsupported by its cited source.";
    case "cancelled":
      return "Knowledge-proposal request cancelled.";
    case "failed":
      return "The organization knowledge-proposal request could not complete.";
    default:
      return connection
        ? "Describe the connection supported by these two sources."
        : "Write an answer, review it, then propose it without changing source knowledge.";
  }
}

function validReviewedContent(value: string, connection: boolean) {
  const content = value.trim();
  return (
    content.length > 0 &&
    [...content].length <= (connection ? 2_000 : 2_048) &&
    [...content].some((character) => /[\p{L}\p{N}]/u.test(character))
  );
}

export type CuratorProposalSource =
  | Readonly<{
      kind: "student";
      generationSha256: string;
      studentQuestion: StudentQuestion;
    }>
  | Readonly<{ kind: "connection"; intent: ConnectionProposalIntent }>;

export function useCuratorProposal({
  available,
  authorityRevision,
  source,
}: {
  available: boolean;
  authorityRevision: string;
  source: CuratorProposalSource;
}) {
  const connection = source.kind === "connection";
  const [reviewedContent, setReviewedContent] = useState("");
  const [view, setView] = useState<CuratorProposalJobView>();
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedContentRef = useRef("");
  const sourceIdentity = JSON.stringify(source);
  const [ownedSourceIdentity, setOwnedSourceIdentity] =
    useState(sourceIdentity);
  const sourceOwned = ownedSourceIdentity === sourceIdentity;

  const abandonActiveRequest = useCallback(() => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (requestId && !cancelPendingRef.current) {
      void cancelCuratorProposal(requestId).catch(() => undefined);
    }
  }, []);

  const invalidate = useCallback(
    (changed: boolean) => {
      epochRef.current += 1;
      abandonActiveRequest();
      setView(undefined);
      setError("");
      if (changed) {
        setReviewedContent("");
        lastSubmittedContentRef.current = "";
      }
    },
    [abandonActiveRequest],
  );
  const owned = useConnectionAuthority(
    available,
    authorityRevision,
    invalidate,
  );

  useEffect(
    () => () => {
      epochRef.current += 1;
      abandonActiveRequest();
    },
    [abandonActiveRequest],
  );

  useEffect(() => {
    epochRef.current += 1;
    abandonActiveRequest();
    setOwnedSourceIdentity(sourceIdentity);
    if (!connection) setReviewedContent("");
    lastSubmittedContentRef.current = "";
    setView(undefined);
    setError("");
  }, [abandonActiveRequest, connection, sourceIdentity]);

  const pollUntilTerminal = useCallback(
    async (requestId: string, epoch: number) => {
      while (activeRequestRef.current === requestId) {
        await pause(pollIntervalMs);
        if (
          activeRequestRef.current !== requestId ||
          epochRef.current !== epoch
        )
          return;
        try {
          const next = await curatorProposalStatus(requestId);
          if (epochRef.current !== epoch) return;
          setView(next);
          if (!curatorProposalIsActive(next.status)) {
            activeRequestRef.current = undefined;
            if (next.status === "failed") {
              setError(
                "The server could not complete this source-bound proposal review.",
              );
            }
            return;
          }
        } catch (cause) {
          if (epochRef.current !== epoch) return;
          activeRequestRef.current = undefined;
          void cancelCuratorProposal(requestId).catch(() => undefined);
          setError(cause instanceof Error ? cause.message : String(cause));
          return;
        }
      }
    },
    [],
  );

  const submit = useCallback(
    async (content: string) => {
      const normalized = content.trim();
      if (
        !available ||
        !owned ||
        !sourceOwned ||
        cancelPendingRef.current ||
        !validReviewedContent(normalized, connection) ||
        startPendingRef.current ||
        activeRequestRef.current
      )
        return;
      startPendingRef.current = true;
      const epoch = ++epochRef.current;
      setStarting(true);
      setView(undefined);
      setError("");
      lastSubmittedContentRef.current = normalized;
      try {
        const next =
          source.kind === "connection"
            ? await startConnectionProposal(
                source.intent,
                normalized,
                authorityRevision,
              )
            : await startCuratorProposal(
                source.generationSha256,
                normalized,
                source.studentQuestion,
                authorityRevision,
              );
        if (epochRef.current !== epoch) {
          if (curatorProposalIsActive(next.status)) {
            void cancelCuratorProposal(next.requestId).catch(() => undefined);
          }
          return;
        }
        setView(next);
        if (curatorProposalIsActive(next.status)) {
          activeRequestRef.current = next.requestId;
          void pollUntilTerminal(next.requestId, epoch);
        } else if (next.status === "failed") {
          setError(
            "The server could not complete this source-bound proposal review.",
          );
        }
      } catch (cause) {
        if (epochRef.current === epoch) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      } finally {
        startPendingRef.current = false;
        setStarting(false);
      }
    },
    [
      available,
      authorityRevision,
      connection,
      owned,
      pollUntilTerminal,
      source,
      sourceOwned,
    ],
  );

  const run = useCallback(
    () => submit(reviewedContent),
    [reviewedContent, submit],
  );
  const retry = useCallback(
    () => submit(lastSubmittedContentRef.current || reviewedContent),
    [reviewedContent, submit],
  );

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    setCancelling(true);
    try {
      const next = await cancelCuratorProposal(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!curatorProposalIsActive(next.status))
        activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      cancelPendingRef.current = false;
      setCancelling(false);
    }
  }, []);

  const currentView = available && owned && sourceOwned ? view : undefined;
  const content = owned ? reviewedContent : "";
  const active =
    starting ||
    cancelling ||
    (currentView ? curatorProposalIsActive(currentView.status) : false);
  const statusLine = cancelling
    ? "Waiting for cancellation acknowledgement…"
    : curatorStatusLine({ available, starting, view: currentView, connection });

  return {
    active,
    canRun:
      available &&
      owned &&
      sourceOwned &&
      validReviewedContent(content, connection) &&
      !active,
    cancel,
    error: owned && sourceOwned ? error : "",
    retry,
    reviewedContent: content,
    run,
    setReviewedContent,
    statusLine,
    view: currentView,
  };
}
