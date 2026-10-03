import { invoke, isTauri } from "@tauri-apps/api/core";
import { useCallback, useRef, useState } from "react";

import { rememberText } from "@/lib/text-cache";

export function useTranscriptText() {
  const [transcriptText, setTranscriptText] = useState<Record<string, string>>({});
  const [transcriptTextErrors, setTranscriptTextErrors] = useState<Record<string, string>>({});
  const pendingReads = useRef(new Map<string, Promise<string>>());

  const clearTranscriptText = useCallback(() => {
    setTranscriptText({});
    setTranscriptTextErrors({});
    pendingReads.current.clear();
  }, []);

  const forgetTranscriptText = useCallback((path: string) => {
    pendingReads.current.delete(path);
    setTranscriptText((current) => {
      const { [path]: _deleted, ...next } = current;
      return next;
    });
    setTranscriptTextErrors((current) => {
      const { [path]: _deleted, ...next } = current;
      return next;
    });
  }, []);

  const loadTranscriptText = useCallback(async (path: string) => {
    if (Object.prototype.hasOwnProperty.call(transcriptText, path)) return transcriptText[path];
    if (!isTauri()) return "";
    const existing = pendingReads.current.get(path);
    if (existing) return existing;
    setTranscriptTextErrors((current) => {
      if (!current[path]) return current;
      const { [path]: _deleted, ...next } = current;
      return next;
    });
    const pending = invoke<string>("read_text_file", { path }).then((text) => {
      if (pendingReads.current.get(path) === pending) {
        setTranscriptText((current) => rememberText(current, path, text));
      }
      return text;
    }).catch((error: unknown) => {
      if (pendingReads.current.get(path) === pending) {
        setTranscriptTextErrors((current) => ({
          ...current,
          [path]: "This transcript could not be read. Retry or open the saved file.",
        }));
      }
      throw error;
    }).finally(() => {
      if (pendingReads.current.get(path) === pending) pendingReads.current.delete(path);
    });
    pendingReads.current.set(path, pending);
    return pending;
  }, [transcriptText]);

  const loadTranscriptPreviewText = useCallback(async (path: string) => {
    if (!isTauri()) return "";
    return invoke<string>("read_text_preview", { maxChars: 600, path });
  }, []);

  return {
    clearTranscriptText,
    forgetTranscriptText,
    loadTranscriptPreviewText,
    loadTranscriptText,
    transcriptText,
    transcriptTextErrors,
  };
}
