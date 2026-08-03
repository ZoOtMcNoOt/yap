export type SpeakerTranscriptTurn = {
  turnId: string;
  speakerId: string;
  startMs: number;
  endMs: number;
  text: string;
  overlapGroupId?: string;
};

export function isSpeakerTranscriptTurn(value: unknown): value is SpeakerTranscriptTurn {
  if (!value || typeof value !== "object") return false;
  const turn = value as Record<string, unknown>;
  return typeof turn.turnId === "string"
    && /^turn-\d{6}$/.test(turn.turnId)
    && typeof turn.speakerId === "string"
    && /^speaker-[1-8]$/.test(turn.speakerId)
    && Number.isSafeInteger(turn.startMs)
    && Number.isSafeInteger(turn.endMs)
    && Number(turn.startMs) >= 0
    && Number(turn.endMs) > Number(turn.startMs)
    && typeof turn.text === "string"
    && turn.text.length > 0
    && (turn.overlapGroupId === undefined || typeof turn.overlapGroupId === "string");
}

export const speakerTranscriptPageSize = 200;

export type SpeakerTranscriptPage = {
  end: number;
  index: number;
  pageCount: number;
  start: number;
  turns: SpeakerTranscriptTurn[];
};

export function speakerTranscriptPage(
  turns: SpeakerTranscriptTurn[],
  requestedIndex: number,
): SpeakerTranscriptPage {
  const pageCount = Math.max(1, Math.ceil(turns.length / speakerTranscriptPageSize));
  const index = Math.min(Math.max(0, requestedIndex), pageCount - 1);
  const start = index * speakerTranscriptPageSize;
  const end = Math.min(turns.length, start + speakerTranscriptPageSize);
  return {
    end,
    index,
    pageCount,
    start,
    turns: turns.slice(start, end),
  };
}

export type SpeakerTranscriptDetailState =
  | { status: "unavailable" }
  | { status: "loading" }
  | { message: string; status: "error" }
  | {
      sourceResultSha256: string;
      status: "ready";
      turns: SpeakerTranscriptTurn[];
    };
