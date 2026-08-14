import { invoke } from "@tauri-apps/api/core";

import type { StudentQuestion } from "@/student";

export type CuratorProposalStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "proposed"
  | "rejected"
  | "cancelled"
  | "failed";

export type CuratorProposalJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  submissionId: string;
  status: CuratorProposalStatus;
  generationSha256: string;
  evidenceSha256?: string | null;
  proposalId?: string | null;
  reason?: string | null;
}>;

export function startCuratorProposal(
  expectedGenerationSha256: string,
  reviewedContent: string,
  studentQuestion: StudentQuestion,
) {
  return invoke<CuratorProposalJobView>("start_curator_proposal", {
    expectedGenerationSha256,
    reviewedContent,
    studentQuestion,
  });
}

export function curatorProposalStatus(requestId: string) {
  return invoke<CuratorProposalJobView>("curator_proposal_status", { requestId });
}

export function cancelCuratorProposal(requestId: string) {
  return invoke<CuratorProposalJobView>("cancel_curator_proposal", { requestId });
}

export function curatorProposalIsActive(status: CuratorProposalStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
