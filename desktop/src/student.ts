import { invoke } from "@tauri-apps/api/core";

export type StudentQuestionStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "complete"
  | "evidence-unavailable"
  | "cancelled"
  | "failed";

export type StudentSourceCitation = Readonly<{
  conceptId: string;
  sourceRevision: string;
  contentSha256: string;
  charStart: number;
  charEnd: number;
}>;

export type StudentQuestionSupport = Readonly<{
  sourceCitation: StudentSourceCitation;
  supportQuote: string;
  supportCharStart: number;
  supportCharEnd: number;
}>;

export type StudentQuestion = Readonly<{
  schemaVersion: 3;
  sourceSubject: string;
  question: string;
  sourceSupports: readonly StudentQuestionSupport[];
}>;

export type StudentQuestionJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: StudentQuestionStatus;
  conversationConceptId: string;
  generationSha256: string;
  evidenceSha256?: string | null;
  questions: readonly StudentQuestion[];
  outputBudgetExhausted: boolean;
  reason?: string | null;
}>;

export function startStudentQuestion(
  conversationConceptId: string,
  expectedGenerationSha256: string,
  topic: string,
) {
  return invoke<StudentQuestionJobView>("start_student_question", {
    conversationConceptId,
    expectedGenerationSha256,
    topic,
  });
}

export function studentQuestionStatus(requestId: string) {
  return invoke<StudentQuestionJobView>("student_question_status", { requestId });
}

export function cancelStudentQuestion(requestId: string) {
  return invoke<StudentQuestionJobView>("cancel_student_question", { requestId });
}

export function studentQuestionIsActive(status: StudentQuestionStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
