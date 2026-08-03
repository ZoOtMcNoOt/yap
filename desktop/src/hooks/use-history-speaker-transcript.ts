import { useEffect, useState } from "react";

import { loadHistorySpeakerTranscript } from "@/history-catalog";
import type { TranscriptHistoryEntry } from "@/history-model";
import type { SpeakerTranscriptDetailState } from "@/lib/speaker-transcript";

const unavailableSpeakerTranscript: SpeakerTranscriptDetailState = { status: "unavailable" };
const loadingSpeakerTranscript: SpeakerTranscriptDetailState = { status: "loading" };

type IdentityBoundSpeakerTranscript = {
  detail: SpeakerTranscriptDetailState;
  identity?: string;
};

export function useHistorySpeakerTranscript(entry?: TranscriptHistoryEntry) {
  const [loaded, setLoaded] = useState<IdentityBoundSpeakerTranscript>({
    detail: unavailableSpeakerTranscript,
  });
  const sessionId = entry?.speakerTranscriptAvailable ? entry.sessionId : undefined;
  const outputPath = entry?.speakerTranscriptAvailable ? entry.outputPath : undefined;
  const identity = sessionId && outputPath
    ? `${sessionId}\0${outputPath}`
    : undefined;

  useEffect(() => {
    if (!identity || !sessionId || !outputPath) {
      setLoaded({ detail: unavailableSpeakerTranscript });
      return;
    }

    let current = true;
    setLoaded({ detail: loadingSpeakerTranscript, identity });
    void loadHistorySpeakerTranscript({
      origin: "remote",
      outputPath,
      sessionId,
    }).then(
      (loaded) => {
        if (!current) return;
        setLoaded({
          detail: {
            sourceResultSha256: loaded.sourceResultSha256,
            status: "ready",
            turns: loaded.turns,
          },
          identity,
        });
      },
      (error: unknown) => {
        if (!current) return;
        setLoaded({
          detail: {
            message: error instanceof Error ? error.message : "Speaker transcript could not be loaded.",
            status: "error",
          },
          identity,
        });
      },
    );
    return () => {
      current = false;
    };
  }, [identity, outputPath, sessionId]);

  if (!identity) return unavailableSpeakerTranscript;
  return loaded.identity === identity ? loaded.detail : loadingSpeakerTranscript;
}
