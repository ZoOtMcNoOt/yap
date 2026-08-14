import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelCuratorProposal,
  curatorProposalIsActive,
  curatorProposalStatus,
  startCuratorProposal,
  type CuratorProposalJobView,
} from "@/curator";
import type { StudentQuestion } from "@/student";

const pollIntervalMs = 1_000;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function curatorStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: CuratorProposalJobView;
}) {
  if (starting) return "Submitting the reviewed answer for source validation…";
  if (!available && !view) {
    return "Connect to your organization server with Curator enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared review route…";
    case "running":
      return "Checking the reviewed answer against its exact source…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "proposed":
      return "A noncanonical proposal is ready for review.";
    case "rejected":
      return "Curator found the reviewed answer unsupported by its cited source.";
    case "cancelled":
      return "Knowledge-proposal request cancelled.";
    case "failed":
      return "The organization knowledge-proposal request could not complete.";
    default:
      return "Write an answer, review it, then propose it without changing source knowledge.";
  }
}

function validReviewedContent(value: string) {
  const content = value.trim();
  return content.length > 0
    && [...content].length <= 2_048
    && [...content].some((character) => /[\p{L}\p{N}]/u.test(character));
}

export function useCuratorProposal({
  available,
  generationSha256,
  studentQuestion,
}: {
  available: boolean;
  generationSha256: string;
  studentQuestion: StudentQuestion;
}) {
  const [reviewedContent, setReviewedContent] = useState("");
  const [view, setView] = useState<CuratorProposalJobView>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedContentRef = useRef("");
  const questionIdentity = JSON.stringify(studentQuestion);

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelCuratorProposal(requestId).catch((cause) => {
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
    setReviewedContent("");
    setView(undefined);
    setStarting(false);
    setError("");
  }, [abandonActiveRequest, available, generationSha256, questionIdentity]);

  const pollUntilTerminal = useCallback(async (requestId: string, epoch: number) => {
    while (activeRequestRef.current === requestId) {
      await pause(pollIntervalMs);
      if (activeRequestRef.current !== requestId || epochRef.current !== epoch) return;
      try {
        const next = await curatorProposalStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!curatorProposalIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") {
            setError("The server could not complete this source-bound proposal review.");
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
  }, []);

  const submit = useCallback(async (content: string) => {
    const normalized = content.trim();
    if (
      !available
      || !validReviewedContent(normalized)
      || startPendingRef.current
      || activeRequestRef.current
    ) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedContentRef.current = normalized;
    try {
      const next = await startCuratorProposal(
        generationSha256,
        normalized,
        studentQuestion,
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
        setError("The server could not complete this source-bound proposal review.");
      }
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      startPendingRef.current = false;
      if (epochRef.current === epoch) setStarting(false);
    }
  }, [available, generationSha256, pollUntilTerminal, studentQuestion]);

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
    try {
      const next = await cancelCuratorProposal(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!curatorProposalIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      cancelPendingRef.current = false;
    }
  }, []);

  const active = starting || (view ? curatorProposalIsActive(view.status) : false);
  const statusLine = useMemo(
    () => curatorStatusLine({ available, starting, view }),
    [available, starting, view],
  );

  return {
    active,
    canRun: available && validReviewedContent(reviewedContent) && !active,
    cancel,
    error,
    retry,
    reviewedContent,
    run,
    setReviewedContent,
    statusLine,
    view,
  };
}
