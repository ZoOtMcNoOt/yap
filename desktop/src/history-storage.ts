import {
  filterHiddenTranscriptHistory,
  isPreReleaseLiveHistoryEntry,
  normalizeHiddenTranscriptHistory,
  normalizeTranscriptHistory,
  type TranscriptHistoryEntry,
} from "@/history-model";

const transcriptHistoryKey = "yap.transcriptHistory.v1";
const hiddenTranscriptHistoryKey = "yap.hiddenTranscriptHistory.v1";

export type HistoryStorage = Pick<Storage, "getItem" | "setItem">;

function withoutNativeHistoryOrigin(entry: TranscriptHistoryEntry): TranscriptHistoryEntry {
  const { origin: _origin, ...storedEntry } = entry;
  return storedEntry;
}

export function readTranscriptHistory(storage: HistoryStorage | undefined = globalThis.localStorage) {
  if (!storage) return [];

  try {
    return normalizeTranscriptHistory(JSON.parse(storage.getItem(transcriptHistoryKey) ?? "[]"))
      .map(withoutNativeHistoryOrigin);
  } catch {
    return [];
  }
}

export function readHiddenTranscriptHistory(storage: HistoryStorage | undefined = globalThis.localStorage) {
  if (!storage) return [];

  try {
    return normalizeHiddenTranscriptHistory(JSON.parse(storage.getItem(hiddenTranscriptHistoryKey) ?? "[]"));
  } catch {
    return [];
  }
}

export function readVisibleTranscriptHistory(storage: HistoryStorage | undefined = globalThis.localStorage) {
  if (!storage) return [];
  const history = readTranscriptHistory(storage);
  return filterHiddenTranscriptHistory(
    history.filter((entry) => !isPreReleaseLiveHistoryEntry(entry)),
    readHiddenTranscriptHistory(storage),
  );
}

export function writeTranscriptHistory(
  entries: TranscriptHistoryEntry[],
  storage: HistoryStorage = globalThis.localStorage,
) {
  const browserEntries = entries
    .filter((entry) => entry.origin === undefined)
    .map(withoutNativeHistoryOrigin);
  storage.setItem(transcriptHistoryKey, JSON.stringify(normalizeTranscriptHistory(browserEntries)));
}

export function writeHiddenTranscriptHistory(
  outputPaths: string[],
  storage: HistoryStorage = globalThis.localStorage,
) {
  storage.setItem(hiddenTranscriptHistoryKey, JSON.stringify(normalizeHiddenTranscriptHistory(outputPaths)));
}
