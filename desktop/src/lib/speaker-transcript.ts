export type SpeakerTranscriptTurn = {
  speakerId: string;
  startMs: number;
  endMs: number;
  text: string;
  overlapGroupId?: string;
};

export function isSpeakerTranscriptTurn(value: unknown): value is SpeakerTranscriptTurn {
  if (!value || typeof value !== "object") return false;
  const turn = value as Record<string, unknown>;
  return typeof turn.speakerId === "string"
    && /^speaker-[1-8]$/.test(turn.speakerId)
    && Number.isSafeInteger(turn.startMs)
    && Number.isSafeInteger(turn.endMs)
    && Number(turn.startMs) >= 0
    && Number(turn.endMs) > Number(turn.startMs)
    && typeof turn.text === "string"
    && turn.text.length > 0
    && (turn.overlapGroupId === undefined || typeof turn.overlapGroupId === "string");
}
