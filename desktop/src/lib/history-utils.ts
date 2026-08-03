import { transcriptPathIdentity, type TranscriptHistoryEntry } from "@/history-model";
import { createInitialPipelineState, type RecordingJobView } from "@/lib/recording-job";

export function historyEntryToRecordingJob(
  entry: TranscriptHistoryEntry,
  restoredPlaybackPath?: string,
): RecordingJobView {
  const remote = entry.origin === "remote";
  const incomplete = Boolean(entry.warning || entry.recoveryState);
  const alignment = entry.resultSummary
    ? entry.resultSummary.timingStatus === "available" ? "done" : "skipped"
    : "notStarted";
  return {
    error: entry.warning,
    id: `history:${transcriptPathIdentity(entry.outputPath)}`,
    name: entry.name,
    outputPath: entry.outputPath,
    sourcePath: entry.sourcePath,
    playbackPath: restoredPlaybackPath,
    pipeline: {
      ...createInitialPipelineState(),
      intake: "done",
      preprocessing: remote ? "done" : "notStarted",
      transcription: "done",
      alignment,
      postprocessing: incomplete ? "error" : "done",
    },
    resultSummary: entry.resultSummary,
    route: remote ? "serverBatch" : "localFallback",
    sessionMode: remote ? "meeting" : "dictation",
    sessionOrigin: remote ? "importedFile" : "liveCapture",
    status: incomplete ? "partial" : "complete",
  };
}
