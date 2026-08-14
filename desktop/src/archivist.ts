import { invoke } from "@tauri-apps/api/core";

export type ArchivistIngestionStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "staged"
  | "cancelled"
  | "failed";

export type ArchivistIngestionJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: ArchivistIngestionStatus;
  jobId: string;
  resultSha256: string;
  captureSha256?: string | null;
  sourceAdmissionSha256?: string | null;
  generationSha256?: string | null;
  conceptCount?: number | null;
  permissionCount?: number | null;
  reason?: string | null;
}>;

export function startArchivistIngestion(recordingId: string) {
  return invoke<ArchivistIngestionJobView>("start_archivist_ingestion", { recordingId });
}

export function archivistIngestionStatus(requestId: string) {
  return invoke<ArchivistIngestionJobView>("archivist_ingestion_status", { requestId });
}

export function cancelArchivistIngestion(requestId: string) {
  return invoke<ArchivistIngestionJobView>("cancel_archivist_ingestion", { requestId });
}

export function archivistIngestionIsActive(status: ArchivistIngestionStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
