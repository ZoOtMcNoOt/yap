import { invoke } from "@tauri-apps/api/core";
import { useRef, useState } from "react";
import { toast } from "sonner";

import type { RecordingJobView } from "@/lib/recording-job";
import { exportSpeakerTranscript, type SpeakerTranscriptExportIdentity } from "@/speaker-transcript-export";
import {
  exportAcceptedTranscriptCorrection,
  type PublishedTranscriptCorrection,
} from "@/transcript-correction";

export type AcceptedCorrectionExportAction = (
  path: string,
  revision: PublishedTranscriptCorrection,
  isCurrent: () => boolean,
) => Promise<void>;

export type AcceptedCorrectionExportFailure = {
  path: string;
  revision: number;
  correctedSha256: string;
  message: string;
};

type TranscriptTextLoader = (path: string) => Promise<string>;

const exportUnconfirmed =
  "Export could not be confirmed. Check the selected destination before trying again; the file may already have been saved.";

export function useTranscriptFileActions(
  loadTranscriptText: TranscriptTextLoader,
) {
  const exporting = useRef(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportFailure, setExportFailure] = useState<{
    path: string;
    message: string;
  }>();
  const [acceptedExportFailure, setAcceptedExportFailure] =
    useState<AcceptedCorrectionExportFailure>();
  const [speakerExportFailure, setSpeakerExportFailure] = useState<{ scope: string; message: string }>();

  async function exportTimedSpeakerTranscript(identity: SpeakerTranscriptExportIdentity, scope: string, isCurrent: () => boolean) {
    if (!isCurrent()) return;
    await runExport(async () => {
      setSpeakerExportFailure(undefined);
      try {
        const result = await exportSpeakerTranscript(identity);
        if (!isCurrent()) return;
        if (result.status === "saved") toast.success("Timed speaker transcript exported", { description: result.path });
        else toast.info("Timed speaker export cancelled");
      } catch (cause) {
        if (!isCurrent()) return;
        setSpeakerExportFailure({ scope, message: typeof cause === "string" ? cause : cause instanceof Error ? cause.message : exportUnconfirmed });
      }
    });
  }

  async function runExport(action: () => Promise<void>) {
    if (exporting.current) return;
    exporting.current = true;
    setExportBusy(true);
    try {
      await action();
    } finally {
      exporting.current = false;
      setExportBusy(false);
    }
  }

  async function exportTranscript(item: RecordingJobView) {
    if (!item.outputPath) return;
    const path = item.outputPath;
    await runExport(async () => {
      setExportFailure(undefined);
      try {
        const result = await invoke<
          { status: "cancelled" } | { status: "saved"; path: string }
        >("export_transcript", { path });
        if (
          result?.status === "saved" &&
          typeof result.path === "string" &&
          result.path.trim()
        ) {
          toast.success("Transcript exported", { description: result.path });
        } else if (result?.status === "cancelled") {
          toast.info("Export cancelled");
        } else {
          throw exportUnconfirmed;
        }
      } catch (error) {
        setExportFailure({
          path,
          message:
            typeof error === "string"
              ? error
              : exportUnconfirmed,
        });
      }
    });
  }

  const exportAcceptedCorrection: AcceptedCorrectionExportAction = async (
    path,
    revision,
    isCurrent,
  ) => {
    if (!path || !isCurrent()) return;
    await runExport(async () => {
      setAcceptedExportFailure(undefined);
      try {
        const result = await exportAcceptedTranscriptCorrection(path, revision);
        if (!isCurrent()) return;
        if (result.status === "saved") {
          toast.success(
            `Saved correction revision ${result.revision} exported`,
            { description: result.path },
          );
        } else {
          toast.info("Saved correction export cancelled");
        }
      } catch (cause) {
        if (!isCurrent()) return;
        setAcceptedExportFailure({
          path,
          revision: revision.revision,
          correctedSha256: revision.correctedSha256,
          message:
            typeof cause === "string"
              ? cause
              : cause instanceof Error
                ? cause.message
                : exportUnconfirmed,
        });
      }
    });
  };

  async function copyTranscript(item: RecordingJobView) {
    if (!item.outputPath) return;

    try {
      const text = await loadTranscriptText(item.outputPath);
      await navigator.clipboard.writeText(text);
      toast.success(
        text.trim() ? "Transcript copied" : "Empty transcript copied",
      );
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
    exportTranscript,
    exportBusy,
    exportFailure,
    exportAcceptedCorrection,
    exportTimedSpeakerTranscript,
    speakerExportFailure,
    acceptedExportFailure,
    openAppPath,
    revealPath,
  };
}
