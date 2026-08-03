import { invoke, isTauri } from "@tauri-apps/api/core";

import type { TranscriptHistoryEntry } from "@/history-model";
import {
  isSpeakerTranscriptTurn,
  type SpeakerTranscriptTurn,
} from "@/lib/speaker-transcript";
import type { SavedTranscriptSession } from "@/native-history";

export type HistoryOrigin = "live" | "remote";

export type NativeHistorySession = SavedTranscriptSession & {
  origin: HistoryOrigin;
};

export type NativeHistoryCatalog = {
  maintenanceWarnings: string[];
  sessions: NativeHistorySession[];
};

export type NativeHistoryIdentity = {
  origin: HistoryOrigin;
  outputPath: string;
  sessionId: string;
};

export type PublishedSpeakerTranscript = {
  sessionId: string;
  sourceResultSha256: string;
  turns: SpeakerTranscriptTurn[];
};

export type LanguageLabelReviewSegment = {
  effectiveLanguageBcp47: string | null;
  hasUserCorrection: boolean;
  index: number;
  sourceLanguageBcp47: string | null;
  sourceSpanIndex: number;
  sourceStatus: "detected" | "unknown";
  text: string;
};

export type LanguageLabelReview = {
  activeCorrectionCount: number;
  reviewRequiredCount: number;
  revision: number;
  schemaVersion: 1;
  segments: LanguageLabelReviewSegment[];
  sessionId: string;
  sourceResultSha256: string;
};

export function nativeHistoryIdentity(
  entry: TranscriptHistoryEntry,
): NativeHistoryIdentity | undefined {
  if (!entry.origin || !entry.sessionId || !/^[a-z0-9_-]{1,128}$/i.test(entry.sessionId)) {
    return undefined;
  }
  return {
    origin: entry.origin,
    outputPath: entry.outputPath,
    sessionId: entry.sessionId,
  };
}

export async function loadNativeHistoryCatalog(): Promise<NativeHistoryCatalog> {
  if (!isTauri()) return { maintenanceWarnings: [], sessions: [] };
  return invoke<NativeHistoryCatalog>("history_catalog");
}

export async function loadHistorySpeakerTranscript(
  identity: NativeHistoryIdentity,
): Promise<PublishedSpeakerTranscript> {
  if (!isTauri()) throw new Error("Speaker transcripts are available only in the desktop app.");
  if (
    identity.origin !== "remote"
    || !/^[a-z0-9_-]{1,128}$/i.test(identity.sessionId)
    || !identity.outputPath
  ) {
    throw new Error("Remote transcript identity is unavailable.");
  }
  const detail = await invoke<PublishedSpeakerTranscript>("history_speaker_transcript", {
    identity,
  });
  if (
    detail.sessionId !== identity.sessionId
    || !/^[a-f0-9]{64}$/.test(detail.sourceResultSha256)
    || !Array.isArray(detail.turns)
    || detail.turns.length > 100_000
    || !detail.turns.every(isSpeakerTranscriptTurn)
  ) {
    throw new Error("The native speaker transcript response is invalid.");
  }
  return detail;
}

export async function hideNativeHistoryEntry(entry: TranscriptHistoryEntry) {
  const identity = nativeHistoryIdentity(entry);
  if (!identity) throw new Error("Native history identity is unavailable.");
  if (!isTauri()) throw new Error("Native history is unavailable outside the desktop app.");
  await invoke("history_hide_native", { identity });
}

function remoteHistoryIdentity(entry: TranscriptHistoryEntry): NativeHistoryIdentity {
  const identity = nativeHistoryIdentity(entry);
  if (!identity || identity.origin !== "remote") {
    throw new Error("Remote transcript identity is unavailable.");
  }
  return identity;
}

export async function loadLanguageLabelReview(
  entry: TranscriptHistoryEntry,
): Promise<LanguageLabelReview> {
  if (!isTauri()) throw new Error("Language-label review is available only in the desktop app.");
  return invoke<LanguageLabelReview>("history_language_label_review", {
    identity: remoteHistoryIdentity(entry),
  });
}

export async function saveLanguageLabelCorrection(
  entry: TranscriptHistoryEntry,
  expectedRevision: number,
  segmentIndex: number,
  replacementLanguageBcp47: string | null,
): Promise<LanguageLabelReview> {
  if (!isTauri()) throw new Error("Language-label correction is available only in the desktop app.");
  return invoke<LanguageLabelReview>("history_append_language_label_correction", {
    expectedRevision,
    identity: remoteHistoryIdentity(entry),
    replacementLanguageBcp47,
    segmentIndex,
  });
}
