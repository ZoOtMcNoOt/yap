import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { AcceptedCorrectionExportAction } from "@/hooks/use-transcript-file-actions";

import {
  readAcceptedTranscriptCorrection,
  type RecoveredTranscriptCorrection,
} from "@/transcript-correction";

export function useAcceptedTranscriptCorrection({
  outputPath,
  ready,
  publication,
}: {
  outputPath: string;
  ready: boolean;
  publication?: string;
}) {
  const source = ready ? outputPath : "";
  const currentSourceRef = useRef(source);
  currentSourceRef.current = source;
  const epochRef = useRef(0);
  const pendingRef = useRef<
    | {
        source: string;
        publication?: string;
        request: Promise<RecoveredTranscriptCorrection>;
      }
    | undefined
  >(undefined);
  const [snapshot, setSnapshot] = useState<{
    source: string;
    loading: boolean;
    view?: RecoveredTranscriptCorrection;
    error?: string;
  }>({ source: "", loading: false });

  const reload = useCallback(async () => {
    const epoch = ++epochRef.current;
    setSnapshot({ source, loading: Boolean(source) });
    if (!source) return;
    let pending = pendingRef.current;
    if (
      !pending ||
      pending.source !== source ||
      pending.publication !== publication
    ) {
      pending = {
        source,
        publication,
        request: readAcceptedTranscriptCorrection(source),
      };
      pendingRef.current = pending;
    }
    try {
      const view = await pending.request;
      if (epochRef.current !== epoch) return;
      setSnapshot({ source, view, loading: false });
    } catch (cause) {
      if (epochRef.current !== epoch) return;
      setSnapshot({
        source,
        loading: false,
        error: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      if (pendingRef.current === pending) pendingRef.current = undefined;
    }
  }, [publication, source]);

  useEffect(() => {
    void reload();
    return () => {
      epochRef.current += 1;
    };
  }, [publication, reload]);

  const owned = Boolean(source && snapshot.source === source);
  const revision = owned
    ? (snapshot.view?.acceptedRevision ?? undefined)
    : undefined;
  const copy = useCallback(async () => {
    if (!revision) return;
    const epoch = epochRef.current;
    try {
      await navigator.clipboard.writeText(revision.correctedText);
      if (epochRef.current === epoch) toast.success("Saved correction copied");
    } catch {
      if (epochRef.current === epoch)
        toast.error("Could not copy the saved correction");
    }
  }, [revision]);

  const exportRevision = async (action: AcceptedCorrectionExportAction) => {
    if (!revision) return;
    const epoch = epochRef.current;
    await action(
      source,
      revision,
      () => epochRef.current === epoch && currentSourceRef.current === source,
    );
  };

  return {
    revision,
    loading: Boolean(source && (!owned || snapshot.loading)),
    error: owned ? (snapshot.error ?? "") : "",
    reload,
    copy,
    exportRevision,
  };
}
