import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { AnalystAnswerResult } from "@/components/analyst/analyst-answer-result";
import { analystStatusLine } from "@/components/analyst/use-analyst-answer";
import {
  analystAnswerIsActive,
  analystAnswerStatus,
  cancelAnalystAnswer,
  startAnalystAnswer,
  type AnalystAnswerJobView,
} from "@/analyst";

const completeView: AnalystAnswerJobView = {
  schemaVersion: 1,
  requestId: `analyst-answer-${"1".repeat(32)}`,
  status: "complete",
  citedAnswer: {
    schemaVersion: 1,
    answer: "The reviewed launch decision requires approval.",
    citations: [{
      conceptId: "meetings/launch-review",
      sourceRevision: "revision-1",
      contentSha256: "a".repeat(64),
      charStart: 8,
      charEnd: 55,
      text: "The reviewed launch decision requires approval.",
    }],
    answerSha256: "b".repeat(64),
    citationSha256: "c".repeat(64),
    evidenceSha256: "d".repeat(64),
  },
};

describe("Analyst product contract", () => {
  beforeEach(() => invokeMock.mockReset().mockResolvedValue({}));

  it("routes questions through the native owner without renderer credentials", async () => {
    const requestId = completeView.requestId;
    await startAnalystAnswer("What was approved?", 3, null);
    await analystAnswerStatus(requestId);
    await cancelAnalystAnswer(requestId);

    expect(invokeMock.mock.calls).toEqual([
      ["start_analyst_answer", {
        question: "What was approved?",
        maximumResults: 3,
        expectedGenerationSha256: null,
      }],
      ["analyst_answer_status", { requestId }],
      ["cancel_analyst_answer", { requestId }],
    ]);
  });

  it("classifies only server-owned in-flight states as active", () => {
    for (const status of ["queued", "running", "cancellation-requested"] as const) {
      expect(analystAnswerIsActive(status)).toBe(true);
    }
    for (const status of ["complete", "evidence-unavailable", "cancelled", "failed"] as const) {
      expect(analystAnswerIsActive(status)).toBe(false);
    }
  });

  it("keeps hidden-only and absent evidence under one unavailable message", () => {
    for (const reason of ["empty-result", "evidence-unavailable"] as const) {
      expect(analystStatusLine({
        available: true,
        starting: false,
        view: { ...completeView, status: "evidence-unavailable", citedAnswer: null, reason },
      })).toBe("No permission-safe cited answer is available for that question.");
    }
  });

  it("renders only the server-derived answer and its exact source citations", () => {
    const markup = renderToStaticMarkup(<AnalystAnswerResult answer={completeView.citedAnswer!} />);

    expect(markup).toContain("The reviewed launch decision requires approval.");
    expect(markup).toContain("meetings/launch-review");
    expect(markup).toContain("characters 8–55");
    expect(markup).not.toContain(completeView.citedAnswer!.answerSha256);
    expect(markup).not.toContain(completeView.citedAnswer!.citationSha256);
    expect(markup).not.toContain(completeView.citedAnswer!.evidenceSha256);
  });
});
