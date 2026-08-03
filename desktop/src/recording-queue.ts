import { invoke, isTauri } from "@tauri-apps/api/core";

import type { RecordingJobView } from "@/lib/recording-job";
import type { RecordingImportLanguageChoice } from "@/lib/recording-language";

export async function recordingJobsSnapshot() {
  if (!isTauri()) return [];
  return invoke<RecordingJobView[]>("recording_jobs_snapshot");
}

export async function pickRecordingImports(choice: RecordingImportLanguageChoice) {
  if (!isTauri()) return [];
  return invoke<RecordingJobView[]>("recording_jobs_pick_imports", {
    catalogRevision: choice.catalogRevision,
    languageBcp47: choice.mode === "fixed" ? choice.languageBcp47 : undefined,
    languageMode: choice.mode,
  });
}

export async function cancelRecordingJob(jobId: string) {
  return invoke<RecordingJobView>("recording_job_cancel", { jobId });
}

export async function dismissRecordingJob(jobId: string) {
  return invoke<RecordingJobView>("recording_job_dismiss", { jobId });
}

export async function retryRecordingJob(jobId: string) {
  return invoke<RecordingJobView>("recording_job_retry", { jobId });
}

export async function confirmRecordingJobLanguage(
  jobId: string,
  languageBcp47: string,
  catalogRevision: string,
) {
  return invoke<RecordingJobView>("recording_job_confirm_language", {
    jobId,
    languageBcp47,
    catalogRevision,
  });
}
