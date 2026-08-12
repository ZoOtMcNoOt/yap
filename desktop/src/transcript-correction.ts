import { invoke } from "@tauri-apps/api/core";

export type TranscriptCorrectionStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "cancelled"
  | "complete"
  | "failed";

export type TranscriptCorrectionJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: TranscriptCorrectionStatus;
  sourceRevisionSha256: string;
  sourceSha256: string;
  terminologySnapshotSha256: string;
  applied: boolean;
  correctedText: string | null;
  reason: string | null;
}>;

export type PublishedTranscriptCorrection = Readonly<{
  requestId: string;
  revision: number;
  sourceRevisionSha256: string;
  sourceSha256: string;
  terminologySnapshotSha256: string;
  correctedSha256: string;
  correctedText: string;
  revisionPath: string;
}>;

export function startTranscriptCorrection(outputPath: string) {
  return invoke<TranscriptCorrectionJobView>("start_transcript_correction", { outputPath });
}

export function transcriptCorrectionStatus(requestId: string) {
  return invoke<TranscriptCorrectionJobView>("transcript_correction_status", { requestId });
}

export function cancelTranscriptCorrection(requestId: string) {
  return invoke<TranscriptCorrectionJobView>("cancel_transcript_correction", { requestId });
}

export function publishTranscriptCorrection(requestId: string) {
  return invoke<PublishedTranscriptCorrection>("publish_transcript_correction", { requestId });
}

export function transcriptCorrectionIsActive(status: TranscriptCorrectionStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
