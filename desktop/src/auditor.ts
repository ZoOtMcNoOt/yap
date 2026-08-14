import { invoke } from "@tauri-apps/api/core";

import type { LibrarianEvidenceItem } from "@/librarian";

export type AuditorReportStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "complete"
  | "evidence-unavailable"
  | "cancelled"
  | "failed";

export type AuditorFinding = Readonly<{
  kind: "potential-contradiction";
  summary: "These two current reviewed knowledge statements may conflict.";
  citations: readonly [LibrarianEvidenceItem, LibrarianEvidenceItem];
  findingSha256: string;
  requiresReview: true;
}>;

export type AuditorReport = Readonly<{
  schemaVersion: 1;
  generationSha256: string;
  sourceAdmissionSha256: string;
  evidenceSha256: string;
  findings: readonly AuditorFinding[];
  citationSha256: string;
  canonical: false;
  requiresReview: true;
  reportSha256: string;
}>;

export type AuditorReportJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: AuditorReportStatus;
  report?: AuditorReport | null;
  reason?: string | null;
}>;

export function startAuditorReport(
  focus: string,
  maximumFindings: number,
  expectedGenerationSha256: string | null,
) {
  return invoke<AuditorReportJobView>("start_auditor_report", {
    focus,
    maximumFindings,
    expectedGenerationSha256,
  });
}

export function auditorReportStatus(requestId: string) {
  return invoke<AuditorReportJobView>("auditor_report_status", { requestId });
}

export function cancelAuditorReport(requestId: string) {
  return invoke<AuditorReportJobView>("cancel_auditor_report", { requestId });
}

export function auditorReportIsActive(status: AuditorReportStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
