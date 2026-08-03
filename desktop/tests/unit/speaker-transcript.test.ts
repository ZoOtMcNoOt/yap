import { describe, expect, it } from "vitest";

import {
  isSpeakerTranscriptTurn,
  speakerTranscriptPage,
  speakerTranscriptPageSize,
  type SpeakerTranscriptTurn,
} from "@/lib/speaker-transcript";

function turn(index: number, startMs = index * 10): SpeakerTranscriptTurn {
  return {
    turnId: `turn-${String(index + 1).padStart(6, "0")}`,
    speakerId: "speaker-1",
    startMs,
    endMs: startMs + 10,
    text: `Turn ${index + 1}`,
  };
}

describe("speaker transcript projection", () => {
  it("preserves canonical identity even when intervals and speakers are duplicated", () => {
    const first = turn(0, 0);
    const second = { ...turn(1, 0), endMs: first.endMs };

    expect(isSpeakerTranscriptTurn(first)).toBe(true);
    expect(isSpeakerTranscriptTurn(second)).toBe(true);
    expect(first.turnId).not.toBe(second.turnId);
  });

  it("keeps every rendered page within the fixed DOM bound", () => {
    const turns = Array.from({ length: speakerTranscriptPageSize * 3 + 17 }, (_, index) => turn(index));

    const first = speakerTranscriptPage(turns, 0);
    const middle = speakerTranscriptPage(turns, 1);
    const last = speakerTranscriptPage(turns, Number.MAX_SAFE_INTEGER);

    expect(first.turns).toHaveLength(speakerTranscriptPageSize);
    expect(middle.turns).toHaveLength(speakerTranscriptPageSize);
    expect(last.turns).toHaveLength(17);
    expect(last.index).toBe(3);
    expect(last.end).toBe(turns.length);
  });
});
