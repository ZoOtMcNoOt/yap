import { invoke } from "@tauri-apps/api/core";

import type { LibrarianEvidenceItem } from "@/librarian";

export type AnalystAnswerStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "complete"
  | "evidence-unavailable"
  | "cancelled"
  | "failed";

export type AnalystAnswer = Readonly<{
  schemaVersion: 1;
  answer: string;
  citations: readonly LibrarianEvidenceItem[];
  answerSha256: string;
  citationSha256: string;
  evidenceSha256: string;
}>;

export type AnalystAnswerJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: AnalystAnswerStatus;
  citedAnswer?: AnalystAnswer | null;
  reason?: string | null;
}>;

export function startAnalystAnswer(
  question: string,
  maximumResults: number,
  expectedGenerationSha256: string | null,
) {
  return invoke<AnalystAnswerJobView>("start_analyst_answer", {
    question,
    maximumResults,
    expectedGenerationSha256,
  });
}

export function analystAnswerStatus(requestId: string) {
  return invoke<AnalystAnswerJobView>("analyst_answer_status", { requestId });
}

export function cancelAnalystAnswer(requestId: string) {
  return invoke<AnalystAnswerJobView>("cancel_analyst_answer", { requestId });
}

export function analystAnswerIsActive(status: AnalystAnswerStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
