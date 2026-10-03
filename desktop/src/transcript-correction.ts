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
  return invoke<TranscriptCorrectionJobView>("start_transcript_correction", {
    outputPath,
  });
}

export function transcriptCorrectionStatus(requestId: string) {
  return invoke<TranscriptCorrectionJobView>("transcript_correction_status", {
    requestId,
  });
}

export function cancelTranscriptCorrection(requestId: string) {
  return invoke<TranscriptCorrectionJobView>("cancel_transcript_correction", {
    requestId,
  });
}

export function publishTranscriptCorrection(requestId: string) {
  return invoke<PublishedTranscriptCorrection>(
    "publish_transcript_correction",
    { requestId },
  );
}

export function transcriptCorrectionIsActive(
  status: TranscriptCorrectionStatus,
) {
  return (
    status === "queued" ||
    status === "running" ||
    status === "cancellation-requested"
  );
}

export type RecoveredTranscriptCorrection = Readonly<{
  schemaVersion: 1;
  outputPath: string;
  sourceRevisionSha256: string;
  sourceSha256: string;
  revisionCount: number;
  acceptedRevision: PublishedTranscriptCorrection | null;
}>;

export async function exportAcceptedTranscriptCorrection(
  outputPath: string,
  revision: PublishedTranscriptCorrection,
) {
  const result = await invoke<
    | { status: "cancelled" }
    | {
        status: "saved";
        path: string;
        revision: number;
        correctedSha256: string;
      }
  >("export_accepted_transcript_correction", {
    outputPath,
    revision: revision.revision,
    correctedSha256: revision.correctedSha256,
  });
  if (
    !result ||
    (result.status !== "cancelled" &&
      (result.status !== "saved" ||
        result.revision !== revision.revision ||
        result.correctedSha256 !== revision.correctedSha256 ||
        typeof result.path !== "string" ||
        !result.path.trim()))
  ) {
    throw new Error(
      "The export receipt did not match the saved correction. Check the selected destination before trying again; the file may already have been saved.",
    );
  }
  return result;
}

export async function readAcceptedTranscriptCorrection(
  outputPath: string,
  selectedRevision: number | null = null,
) {
  if (
    selectedRevision !== null &&
    (!Number.isSafeInteger(selectedRevision) ||
      selectedRevision < 1 ||
      selectedRevision > 64)
  ) {
    throw new Error("Choose a saved revision from its history.");
  }
  const result = await invoke<RecoveredTranscriptCorrection>(
    "read_accepted_transcript_correction",
    { outputPath, revision: selectedRevision },
  );
  const sha = (value: unknown): value is string =>
    typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  if (
    !result ||
    result.schemaVersion !== 1 ||
    result.outputPath !== outputPath ||
    !sha(result.sourceSha256) ||
    !sha(result.sourceRevisionSha256) ||
    !Number.isSafeInteger(result.revisionCount) ||
    result.revisionCount < 0 ||
    result.revisionCount > 64 ||
    (result.acceptedRevision === null) !== (result.revisionCount === 0) ||
    (selectedRevision !== null && result.acceptedRevision === null) ||
    result.acceptedRevision === undefined
  ) {
    throw new Error(
      "Saved correction history did not match the selected transcript.",
    );
  }
  const revision = result.acceptedRevision;
  if (
    revision !== null &&
    (typeof revision !== "object" || Array.isArray(revision))
  ) {
    throw new Error(
      "Saved correction history contained an invalid accepted revision.",
    );
  }
  if (
    revision &&
    (!Number.isSafeInteger(revision.revision) ||
      revision.revision < 1 ||
      revision.revision > 64 ||
      revision.revision !== (selectedRevision ?? result.revisionCount) ||
      revision.revision > result.revisionCount ||
      revision.sourceSha256 !== result.sourceSha256 ||
      revision.sourceRevisionSha256 !== result.sourceRevisionSha256 ||
      !sha(revision.terminologySnapshotSha256) ||
      !sha(revision.correctedSha256) ||
      revision.correctedSha256 === result.sourceSha256 ||
      typeof revision.correctedText !== "string" ||
      !revision.correctedText ||
      revision.correctedText.includes("\0") ||
      [...revision.correctedText].length > 32_768 ||
      typeof revision.revisionPath !== "string" ||
      !revision.revisionPath ||
      typeof revision.requestId !== "string" ||
      !revision.requestId)
  ) {
    throw new Error(
      "Saved correction history contained an invalid accepted revision.",
    );
  }
  return result;
}
