import { useRequestLifecycle } from "@/hooks/use-request-lifecycle";

import { useCallback, useRef, useState } from "react";

import {
  analystAnswerIsActive,
  analystAnswerStatus,
  cancelAnalystAnswer,
  startAnalystAnswer,
  type AnalystAnswerJobView,
} from "@/analyst";

const maximumResults = 3;

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
  return (
    question.length > 0 &&
    [...question].length <= 1_024 &&
    [...question].some((character) => /[\p{L}\p{N}]/u.test(character))
  );
}

export function useAnalystAnswer({
  available,
  authorityRevision,
}: {
  available: boolean;
  authorityRevision: string;
}) {
  const [question, setQuestion] = useState("");
  const lastSubmittedQuestionRef = useRef("");
  const resetDraft = useCallback(() => {
    setQuestion("");
    lastSubmittedQuestionRef.current = "";
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
  } = useRequestLifecycle<AnalystAnswerJobView>({
    available,
    authorityRevision,
    resetDraft,
    status: analystAnswerStatus,
    cancelRequest: cancelAnalystAnswer,
    isActive: analystAnswerIsActive,
    failureMessage: "The server could not complete this source-cited answer.",
  });

  const submit = useCallback(
    async (requestedQuestion: string) => {
      const normalized = requestedQuestion.trim();
      if (!current || !validQuestion(normalized)) return;
      await submitRequest(() => {
        lastSubmittedQuestionRef.current = normalized;
        return startAnalystAnswer(
          normalized,
          maximumResults,
          null,
          authorityRevision,
        );
      });
    },
    [authorityRevision, current, submitRequest],
  );

  const run = useCallback(() => submit(question), [question, submit]);
  const retry = useCallback(
    () => submit(lastSubmittedQuestionRef.current || question),
    [question, submit],
  );

  const statusLine = cancelling
    ? "Waiting for cancellation acknowledgement…"
    : analystStatusLine({ available, starting, view });

  return {
    active,
    answer:
      view?.status === "complete" ? (view.citedAnswer ?? undefined) : undefined,
    canRun: current && validQuestion(question) && !active,
    cancel,
    error,
    question: ownsDraft ? question : "",
    retry,
    run,
    setQuestion,
    statusLine,
    view,
  };
}
