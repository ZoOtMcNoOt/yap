import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelStudentQuestion,
  startStudentQuestion,
  studentQuestionIsActive,
  studentQuestionStatus,
  type StudentQuestionJobView,
} from "@/student";

const pollIntervalMs = 1_000;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

export function studentStatusLine({
  available,
  starting,
  view,
}: {
  available: boolean;
  starting: boolean;
  view?: StudentQuestionJobView;
}) {
  if (starting) return "Submitting a source-bound learning request…";
  if (!available && !view) {
    return "Connect to your organization server with Student enabled.";
  }
  switch (view?.status) {
    case "queued":
      return "Waiting for the shared learning route…";
    case "running":
      return "Creating one question from the current reviewed source…";
    case "cancellation-requested":
      return "Waiting for cancellation acknowledgement…";
    case "complete":
      return "Your source-cited learning prompt is ready.";
    case "evidence-unavailable":
      return "No current learning prompt is available from that source.";
    case "cancelled":
      return "Learning request cancelled.";
    case "failed":
      return "The organization learning request could not complete.";
    default:
      return "Create one question from this reviewed meeting source.";
  }
}

function validTopic(value: string) {
  const topic = value.trim();
  return topic.length > 0
    && [...topic].length <= 128
    && !/[?\r\n]/u.test(topic)
    && [...topic].some((character) => /[\p{L}\p{N}]/u.test(character));
}

export function useStudentQuestion({
  available,
  conversationConceptId,
  generationSha256,
}: {
  available: boolean;
  conversationConceptId: string;
  generationSha256: string;
}) {
  const [topic, setTopic] = useState("");
  const [view, setView] = useState<StudentQuestionJobView>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const activeRequestRef = useRef<string | undefined>(undefined);
  const epochRef = useRef(0);
  const startPendingRef = useRef(false);
  const cancelPendingRef = useRef(false);
  const lastSubmittedTopicRef = useRef("");

  const abandonActiveRequest = useCallback((showError: boolean) => {
    const requestId = activeRequestRef.current;
    activeRequestRef.current = undefined;
    if (!requestId) return;
    void cancelStudentQuestion(requestId).catch((cause) => {
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
  }, [abandonActiveRequest, available, conversationConceptId, generationSha256]);

  const pollUntilTerminal = useCallback(async (requestId: string, epoch: number) => {
    while (activeRequestRef.current === requestId) {
      await pause(pollIntervalMs);
      if (activeRequestRef.current !== requestId || epochRef.current !== epoch) return;
      try {
        const next = await studentQuestionStatus(requestId);
        if (epochRef.current !== epoch) return;
        setView(next);
        if (!studentQuestionIsActive(next.status)) {
          activeRequestRef.current = undefined;
          if (next.status === "failed") {
            setError("The server could not complete this source-bound learning request.");
          }
          return;
        }
      } catch (cause) {
        if (epochRef.current !== epoch) return;
        activeRequestRef.current = undefined;
        void cancelStudentQuestion(requestId).catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
        return;
      }
    }
  }, []);

  const submit = useCallback(async (requestedTopic: string) => {
    const normalized = requestedTopic.trim();
    if (
      !available
      || !validTopic(normalized)
      || startPendingRef.current
      || activeRequestRef.current
    ) return;
    startPendingRef.current = true;
    const epoch = ++epochRef.current;
    setStarting(true);
    setView(undefined);
    setError("");
    lastSubmittedTopicRef.current = normalized;
    try {
      const next = await startStudentQuestion(
        conversationConceptId,
        generationSha256,
        normalized,
      );
      if (epochRef.current !== epoch) {
        if (studentQuestionIsActive(next.status)) {
          void cancelStudentQuestion(next.requestId).catch(() => undefined);
        }
        return;
      }
      setView(next);
      if (studentQuestionIsActive(next.status)) {
        activeRequestRef.current = next.requestId;
        void pollUntilTerminal(next.requestId, epoch);
      } else if (next.status === "failed") {
        setError("The server could not complete this source-bound learning request.");
      }
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      startPendingRef.current = false;
      if (epochRef.current === epoch) setStarting(false);
    }
  }, [available, conversationConceptId, generationSha256, pollUntilTerminal]);

  const run = useCallback(() => submit(topic), [submit, topic]);
  const retry = useCallback(
    () => submit(lastSubmittedTopicRef.current || topic),
    [submit, topic],
  );

  const cancel = useCallback(async () => {
    const requestId = activeRequestRef.current;
    if (!requestId || cancelPendingRef.current) return;
    const epoch = epochRef.current;
    cancelPendingRef.current = true;
    try {
      const next = await cancelStudentQuestion(requestId);
      if (epochRef.current !== epoch) return;
      setView(next);
      if (!studentQuestionIsActive(next.status)) activeRequestRef.current = undefined;
    } catch (cause) {
      if (epochRef.current === epoch) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      cancelPendingRef.current = false;
    }
  }, []);

  const active = starting || (view ? studentQuestionIsActive(view.status) : false);
  const statusLine = useMemo(
    () => studentStatusLine({ available, starting, view }),
    [available, starting, view],
  );

  return {
    active,
    canRun: available && validTopic(topic) && !active,
    cancel,
    error,
    retry,
    run,
    setTopic,
    statusLine,
    topic,
    view,
  };
}
