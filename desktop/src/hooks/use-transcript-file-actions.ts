import { invoke } from "@tauri-apps/api/core";
import { toast } from "sonner";

import type { RecordingJobView } from "@/lib/recording-job";

type TranscriptTextLoader = (path: string) => Promise<string>;

export function useTranscriptFileActions(loadTranscriptText: TranscriptTextLoader) {
  async function copyTranscript(item: RecordingJobView) {
    if (!item.outputPath) return;

    try {
      const text = await loadTranscriptText(item.outputPath);
      await navigator.clipboard.writeText(text);
      toast.success(text.trim() ? "Transcript copied" : "Empty transcript copied");
    } catch {
      toast.error("Copy failed");
    }
  }

  async function openAppPath(path: string) {
    try {
      await invoke("open_app_path", { path });
      toast.success("Opened file");
    } catch {
      toast.error("Open failed");
    }
  }

  async function revealPath(path: string) {
    try {
      await invoke("reveal_app_path", { path });
    } catch {
      toast.error("Reveal failed");
    }
  }

  return {
    copyTranscript,
    openAppPath,
    revealPath,
  };
}
