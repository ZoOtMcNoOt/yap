import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { isRecordingCancellable, type RecordingJobView } from "@/lib/recording-job";
import type { RecordingImportLanguageChoice } from "@/lib/recording-language";
import {
  cancelRecordingJob,
  confirmRecordingJobLanguage,
  pickRecordingImports,
  dismissRecordingJob,
  recordingJobsSnapshot,
  retryRecordingJob,
} from "@/recording-queue";
import {
  createRecordingJobsRefreshCoordinator,
  startRecordingJobsLifecycle,
} from "@/recording-jobs-refresh";

export function useRecordingJobs(onClear: () => void) {
  const [queue, setQueue] = useState<RecordingJobView[]>([]);
  const refreshCoordinatorRef = useRef<ReturnType<
    typeof createRecordingJobsRefreshCoordinator<RecordingJobView[]>
  > | undefined>(undefined);
  if (!refreshCoordinatorRef.current) {
    refreshCoordinatorRef.current = createRecordingJobsRefreshCoordinator(
      recordingJobsSnapshot,
      setQueue,
    );
  }
  const refresh = refreshCoordinatorRef.current.refresh;
  const onClearRef = useRef(onClear);
  onClearRef.current = onClear;

  useEffect(() => {
    const lifecycle = startRecordingJobsLifecycle({
      failed(error) {
        toast.error(`Recording jobs could not start: ${error.message}`);
      },
      refresh,
      refreshFailed: (error) => {
        toast.error(`Recording jobs could not be refreshed: ${error.message}`);
      },
      subscribe: (handler) => isTauri()
        ? listen("recording-jobs-changed", handler)
        : Promise.resolve(() => {}),
    });
    return lifecycle.dispose;
  }, [refresh]);

  const addRecordings = useCallback(async (choice: RecordingImportLanguageChoice) => {
    const created = await pickRecordingImports(choice);
    await refresh();
    return created[created.length - 1]?.id;
  }, [refresh]);

  const removeItem = useCallback(async (id: string) => {
    const item = queue.find((entry) => entry.id === id);
    if (!item) return;
    if (item.status === "failed") {
      await dismissRecordingJob(id);
    } else if (isRecordingCancellable(item.status)) {
      await cancelRecordingJob(id);
    } else {
      return;
    }
    await refresh();
  }, [queue, refresh]);

  const retryItem = useCallback(async (id: string) => {
    await retryRecordingJob(id);
    await refresh();
  }, [refresh]);

  const confirmLanguage = useCallback(async (
    id: string,
    languageBcp47: string,
    catalogRevision: string,
  ) => {
    await confirmRecordingJobLanguage(id, languageBcp47, catalogRevision);
    await refresh();
  }, [refresh]);

  const clearQueue = useCallback(async () => {
    for (const item of queue) {
      if (item.status === "failed") {
        await dismissRecordingJob(item.id);
      } else if (isRecordingCancellable(item.status)) {
        await cancelRecordingJob(item.id);
      }
    }
    await refresh();
    onClearRef.current();
  }, [queue, refresh]);

  return {
    addRecordings,
    clearQueue,
    confirmLanguage,
    queue,
    refresh,
    removeItem,
    retryItem,
  };
}
