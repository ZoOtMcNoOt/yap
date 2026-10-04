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
  const [selection, setSelection] = useState<{
    source: string;
    publication?: string;
    revision: number | null;
  }>();
  const selectedRevision =
    selection?.source === source && selection.publication === publication
      ? selection.revision
      : null;
  const pendingRef = useRef<
    | {
        source: string;
        publication?: string;
        revision: number | null;
        request: Promise<RecoveredTranscriptCorrection>;
      }
    | undefined
  >(undefined);
  const [snapshot, setSnapshot] = useState<{
    source: string;
    selection: number | null;
    publication?: string;
    loading: boolean;
    view?: RecoveredTranscriptCorrection;
    error?: string;
  }>({ source: "", selection: null, loading: false });

  const reload = useCallback(async () => {
    const epoch = ++epochRef.current;
    setSnapshot((prior) => ({
      source,
      selection: selectedRevision,
      publication,
      loading: Boolean(source),
      view:
        prior.source === source && prior.publication === publication
          ? prior.view
          : undefined,
    }));
    if (!source) return;
    let pending = pendingRef.current;
    if (
      !pending ||
      pending.source !== source ||
      pending.publication !== publication ||
      pending.revision !== selectedRevision
    ) {
      pending = {
        source,
        publication,
        revision: selectedRevision,
        request: readAcceptedTranscriptCorrection(source, selectedRevision),
      };
      pendingRef.current = pending;
    }
    try {
      const view = await pending.request;
      if (epochRef.current !== epoch) return;
      setSnapshot({
        source,
        selection: selectedRevision,
        publication,
        view,
        loading: false,
      });
    } catch (cause) {
      if (epochRef.current !== epoch) return;
      setSnapshot((prior) => ({
        source,
        selection: selectedRevision,
        publication,
        loading: false,
        view:
          prior.source === source && prior.publication === publication
            ? prior.view
            : undefined,
        error: cause instanceof Error ? cause.message : String(cause),
      }));
    } finally {
      if (pendingRef.current === pending) pendingRef.current = undefined;
    }
  }, [publication, selectedRevision, source]);

  useEffect(() => {
    void reload();
    return () => {
      epochRef.current += 1;
    };
  }, [publication, reload]);

  const sameSource = Boolean(
    source && snapshot.source === source && snapshot.publication === publication,
  );
  const owned = sameSource && snapshot.selection === selectedRevision;
  const revisionCount = sameSource ? (snapshot.view?.revisionCount ?? 0) : 0;
  const revision =
    owned && !snapshot.loading && !snapshot.error
      ? (snapshot.view?.acceptedRevision ?? undefined)
      : undefined;
  const selectRevision = (revision: number) => {
    if (
      !Number.isSafeInteger(revision) ||
      revision < 1 ||
      revision > revisionCount
    )
      return;
    const nextRevision = revision === revisionCount ? null : revision;
    if (nextRevision === selectedRevision) return;
    epochRef.current += 1;
    setSelection({ source, publication, revision: nextRevision });
  };
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
    revisionCount,
    selectedRevision: selectedRevision ?? revisionCount,
    selectRevision,
    loading: Boolean(source && (!owned || snapshot.loading)),
    error: owned ? (snapshot.error ?? "") : "",
    reload,
    copy,
    exportRevision,
  };
}
