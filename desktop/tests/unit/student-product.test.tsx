import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { LibrarianEvidenceResults } from "@/components/librarian/librarian-evidence-results";
import { StudentQuestionResult } from "@/components/student/student-question-result";
import { studentStatusLine } from "@/components/student/use-student-question";
import type { LibrarianEvidencePack } from "@/librarian";
import {
  cancelStudentQuestion,
  startStudentQuestion,
  studentQuestionIsActive,
  studentQuestionStatus,
  type StudentQuestionJobView,
} from "@/student";

const generationSha256 = "a".repeat(64);
const evidenceSha256 = "b".repeat(64);

const meetingPack: LibrarianEvidencePack = {
  operation: "search",
  generationSha256,
  permissionHash: "c".repeat(64),
  authorizationHash: "d".repeat(64),
  evidenceSha256: "e".repeat(64),
  items: [
    {
      conceptId: "meetings/launch-review",
      sourceRevision: "f".repeat(64),
      contentSha256: "1".repeat(64),
      charStart: 8,
      charEnd: 73,
      text: "The launch review identified crash containment as the key lesson.",
    },
    {
      conceptId: "policies/launch-review",
      sourceRevision: "2".repeat(64),
      contentSha256: "3".repeat(64),
      charStart: 0,
      charEnd: 31,
      text: "The launch policy requires review.",
    },
  ],
  outputBudgetExhausted: false,
};

const completeView: StudentQuestionJobView = {
  schemaVersion: 1,
  requestId: `student-question-${"4".repeat(32)}`,
  status: "complete",
  conversationConceptId: "meetings/launch-review",
  generationSha256,
  evidenceSha256,
  questions: [
    {
      schemaVersion: 3,
      sourceSubject: "crash containment",
      question: "What should you remember about crash containment?",
      sourceSupports: [
        {
          sourceCitation: {
            conceptId: "meetings/launch-review",
            sourceRevision: "f".repeat(64),
            contentSha256: "1".repeat(64),
            charStart: 8,
            charEnd: 73,
          },
          supportQuote: "crash containment",
          supportCharStart: 37,
          supportCharEnd: 54,
        },
      ],
    },
  ],
  outputBudgetExhausted: false,
  reason: null,
};

describe("Student product contract", () => {
  beforeEach(() => invokeMock.mockReset().mockResolvedValue({}));

  it("routes source-bound requests through the native owner without renderer credentials", async () => {
    const requestId = `student-question-${"4".repeat(32)}`;
    await startStudentQuestion("meetings/launch-review", generationSha256, "crash containment");
    await studentQuestionStatus(requestId);
    await cancelStudentQuestion(requestId);

    expect(invokeMock.mock.calls).toEqual([
      ["start_student_question", {
        conversationConceptId: "meetings/launch-review",
        expectedGenerationSha256: generationSha256,
        topic: "crash containment",
      }],
      ["student_question_status", { requestId }],
      ["cancel_student_question", { requestId }],
    ]);
  });

  it("classifies only server-owned in-flight states as active", () => {
    for (const status of ["queued", "running", "cancellation-requested"] as const) {
      expect(studentQuestionIsActive(status)).toBe(true);
    }
    for (const status of ["complete", "evidence-unavailable", "cancelled", "failed"] as const) {
      expect(studentQuestionIsActive(status)).toBe(false);
    }
  });

  it("keeps unavailable evidence under one non-disclosing product message", () => {
    for (const reason of ["empty-result", "evidence-unavailable", "stale-generation"] as const) {
      expect(studentStatusLine({
        available: true,
        starting: false,
        view: {
          ...completeView,
          status: "evidence-unavailable",
          evidenceSha256: null,
          questions: [],
          reason,
        },
      })).toBe("No current learning prompt is available from that source.");
    }
  });

  it("offers Student only for current meeting evidence", () => {
    const markup = renderToStaticMarkup(
      <LibrarianEvidenceResults
        onCreateLearningPrompt={() => undefined}
        pack={meetingPack}
        studentAvailable
      />,
    );

    expect(markup.match(/aria-label="Create learning prompt from Source/g)).toHaveLength(1);
    expect(markup).toContain("meetings/launch-review");
    expect(markup).not.toContain("Create learning prompt from Source 2");
  });

  it("renders the server-derived question and exact source support without authority hashes", () => {
    const markup = renderToStaticMarkup(<StudentQuestionResult view={completeView} />);

    expect(markup).toContain("What should you remember about crash containment?");
    expect(markup).toContain("crash containment");
    expect(markup).toContain("meetings/launch-review");
    expect(markup).toContain("characters 37–54");
    expect(markup).not.toContain(generationSha256);
    expect(markup).not.toContain(evidenceSha256);
  });
});
