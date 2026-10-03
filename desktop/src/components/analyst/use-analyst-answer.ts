import { useConnectionAuthority } from "@/hooks/use-connection-authority";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  analystAnswerIsActive,
  analystAnswerStatus,
  cancelAnalystAnswer,
  startAnalystAnswer,
  type AnalystAnswerJobView,
} from "@/analyst";

const pollIntervalMs = 1_000;
const maximumResults = 3;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function analystStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: AnalystAnswerJobView;
}) {
  if (starting) return "Submitting a permission-safe question…";
  if (!available && !view) {
    return "Connect to your organization server with Analyst enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared cited-answer route…";
    case "running":
      return "Building an answer only from current authorized evidence…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "complete":
      return "A permission-safe cited answer is ready.";
    case "evidence-unavailable":
      return "No permission-safe cited answer is available for that question.";
    case "cancelled":
      return "Cited-answer request cancelled.";
    case "failed":
      return "The organization cited-answer request could not complete.";
    default:
      return "Ask a question and receive only server-derived, source-cited text.";
  }
}

function validQuestion(value: string) {
  const question = value.trim();
  return question.length > 0
    && [...question].length <= 1_024
    && [...question].some((character) => /[\p{L}\p{N}]/u.test(character));
}

export function useAnalystAnswer({ available, authorityRevision }: { available: boolean; authorityRevision: string }) {
  const [question, setQuestion] = useState("");
  const [view, setView] = useState<AnalystAnswerJobView>();
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedQuestionRef = useRef("");

  const abandonActiveRequest = useCallback(() => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId || cancelPendingRef.current) return;
    void cancelAnalystAnswer(requestId).catch(() => undefined);
  }, []);

  useEffect(() => () => {
    epochRef.current += 1;
    abandonActiveRequest();
  }, [abandonActiveRequest]);

  const invalidate = useCallback((changed: boolean) => {
    epochRef.current += 1;
    abandonActiveRequest();
    if (changed) {
      setQuestion("");
      lastSubmittedQuestionRef.current = "";
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
        const next = await analystAnswerStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!analystAnswerIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") {
            setError("The server could not complete this source-cited answer.");
          }
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch) return;
        activeRequestRef.current = undefined;
        void cancelAnalystAnswer(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const submit = useCallback(async (requestedQuestion: string) => {
    const normalized = requestedQuestion.trim();
    if (
      !current
      || !validQuestion(normalized)
      || cancelPendingRef.current
      || startPendingRef.current
      || activeRequestRef.current
    ) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedQuestionRef.current = normalized;
    try {
      const next = await startAnalystAnswer(normalized, maximumResults, null, authorityRevision);
      if (epochRef.current !== epoch) {
        if (analystAnswerIsActive(next.status)) {
          void cancelAnalystAnswer(next.requestId).catch(() => undefined);
        }
        return;
      }
      setView(next);
      if (analystAnswerIsActive(next.status)) {
        activeRequestRef.current = next.requestId;
        void pollUntilTerminal(next.requestId, epoch);
      } else if (next.status === "failed") {
        setError("The server could not complete this source-cited answer.");
      }
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      startPendingRef.current = false;
      setStarting(false);
    }
  }, [authorityRevision, current, pollUntilTerminal]);

  const run = useCallback(() => submit(question), [question, submit]);
  const retry = useCallback(
    () => submit(lastSubmittedQuestionRef.current || question),
    [question, submit],
  );

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    setCancelling(true);
    try {
      const next = await cancelAnalystAnswer(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!analystAnswerIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      cancelPendingRef.current = false;
      setCancelling(false);
    }
  }, []);

  const active = starting || cancelling || (currentView ? analystAnswerIsActive(currentView.status) : false);
  const statusLine = cancelling
    ? "Waiting for cancellation acknowledgement…"
    : analystStatusLine({ available, starting, view: currentView });

  return {
    active,
    answer: currentView?.status === "complete" ? currentView.citedAnswer ?? undefined : undefined,
    canRun: current && validQuestion(question) && !active,
    cancel,
    error: current ? error : "",
    question: ownsDraft ? question : "",
    retry,
    run,
    setQuestion,
    statusLine,
    view: currentView,
  };
}
