import { useCallback, useEffect, useMemo, useState } from "react";

import type { TranscriptHistoryEntry } from "@/history-model";
import { useRegisteredPlayback } from "@/hooks/use-registered-playback";
import { isRecordingFinished, type RecordingJobView } from "@/lib/recording-job";
import {
  projectHistoryPlaybackAdmission,
  type HistoryPlaybackAdmissions,
} from "@/lib/history-playback";
import { historyEntryToRecordingJob } from "@/lib/history-utils";

type ReviewMorphOrigin = {
  height: number;
  left: number;
  top: number;
  width: number;
};

function withHistoryPlaybackAdmission(
  item: RecordingJobView | undefined,
  entry: TranscriptHistoryEntry | undefined,
  admissions: HistoryPlaybackAdmissions,
) {
  if (!item || !entry || item.outputPath !== entry.outputPath) return item;
  const admission = projectHistoryPlaybackAdmission(entry, admissions);
  return admission ? { ...item, playbackPath: admission.playbackPath } : item;
}

export function useRecordingSelection({
  history,
  queue,
  reviewAvailable,
}: {
  history: TranscriptHistoryEntry[];
  queue: RecordingJobView[];
  reviewAvailable: boolean;
}) {
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedHistoryOutput, setSelectedHistoryOutput] = useState<string>();
  const [historyReviewOpen, setHistoryReviewOpen] = useState(false);
  const [reviewMorphOrigin, setReviewMorphOrigin] = useState<ReviewMorphOrigin>();

  const historyJob = useCallback(
    (entry: TranscriptHistoryEntry) => historyEntryToRecordingJob(entry),
    [],
  );
  const selectedHistoryEntry = history.find((entry) => entry.outputPath === selectedHistoryOutput);
  const selectedHistoryItemWithoutPlayback = selectedHistoryEntry
    ? historyJob(selectedHistoryEntry)
    : undefined;
  const { historyPlaybackAdmissions } = useRegisteredPlayback(
    queue,
    history,
    historyReviewOpen && reviewAvailable ? selectedHistoryEntry : undefined,
  );
  const selectedHistoryItem = useMemo(
    () => withHistoryPlaybackAdmission(
      selectedHistoryItemWithoutPlayback,
      selectedHistoryEntry,
      historyPlaybackAdmissions,
    ),
    [
      historyPlaybackAdmissions,
      selectedHistoryEntry,
      selectedHistoryItemWithoutPlayback,
    ],
  );
  const selectedItem =
    queue.find((item) => item.id === selectedId) ??
    selectedHistoryItem ??
    [...queue].reverse().find((item) => isRecordingFinished(item.status)) ??
    (history[0] ? historyJob(history[0]) : undefined) ??
    queue[0];
  const displayedHistoryEntry = selectedItem?.outputPath
    ? history.find((entry) => entry.outputPath === selectedItem.outputPath)
    : undefined;

  useEffect(() => {
    if (selectedHistoryOutput) return;

    if (!queue.length) {
      setSelectedId(undefined);
      return;
    }

    if (!selectedId || !queue.some((item) => item.id === selectedId)) {
      setSelectedId(queue[queue.length - 1].id);
    }
  }, [queue, selectedId, selectedHistoryOutput]);

  useEffect(() => {
    if (selectedHistoryOutput && !history.some((entry) => entry.outputPath === selectedHistoryOutput)) {
      setSelectedHistoryOutput(undefined);
      setHistoryReviewOpen(false);
    }
  }, [history, selectedHistoryOutput]);

  const closeHistoryReview = useCallback(() => {
    setHistoryReviewOpen(false);
    setReviewMorphOrigin(undefined);
  }, []);

  const clearHistorySelectionIf = useCallback((outputPath: string) => {
    if (selectedHistoryOutput === outputPath) {
      setSelectedHistoryOutput(undefined);
      setHistoryReviewOpen(false);
    }
  }, [selectedHistoryOutput]);

  const selectQueueItem = useCallback((id: string) => {
    setSelectedHistoryOutput(undefined);
    setHistoryReviewOpen(false);
    setSelectedId(id);
  }, []);

  const selectQueueItemOnly = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const selectHistoryEntry = useCallback((entry: TranscriptHistoryEntry, origin?: DOMRect) => {
    setSelectedId(undefined);
    setSelectedHistoryOutput(entry.outputPath);
    setHistoryReviewOpen(true);
    setReviewMorphOrigin(
      origin
        ? {
            height: origin.height,
            left: origin.left,
            top: origin.top,
            width: origin.width,
          }
        : undefined,
    );
  }, []);

  return {
    clearHistorySelectionIf,
    closeHistoryReview,
    displayedHistoryEntry,
    historyJob,
    historyReviewOpen,
    reviewMorphOrigin,
    selectHistoryEntry,
    selectQueueItem,
    selectQueueItemOnly,
    selectedHistoryEntry,
    selectedHistoryItem,
    selectedHistoryOutput,
    selectedId,
    selectedItem,
  };
}
