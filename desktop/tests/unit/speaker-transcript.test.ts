import { describe, expect, it } from "vitest";

import {
  isSpeakerTranscriptTurn,
  projectSpeakerTranscript,
  speakerTranscriptSpeakerLabel,
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

  it("collapses a one-speaker result to the canonical plain transcript", () => {
    expect(projectSpeakerTranscript([turn(0), turn(1)], 0)).toEqual({
      mode: "plain",
    });
  });

  it("keeps speaker attribution when more than one speaker is present", () => {
    const secondSpeaker = { ...turn(1), speakerId: "speaker-2" };

    const projection = projectSpeakerTranscript([turn(0), secondSpeaker], 0);

    expect(projection.mode).toBe("attributed");
    if (projection.mode !== "attributed") throw new Error("Expected attributed projection");
    expect(projection.turns).toEqual([turn(0), secondSpeaker]);
  });

  it("accepts the session ceiling and preserves unknown attribution", () => {
    expect(isSpeakerTranscriptTurn({ ...turn(0), speakerId: "speaker-64" })).toBe(true);
    expect(isSpeakerTranscriptTurn({ ...turn(0), speakerId: null })).toBe(true);
    expect(isSpeakerTranscriptTurn({ ...turn(0), speakerId: "speaker-65" })).toBe(false);
    expect(speakerTranscriptSpeakerLabel("speaker-64")).toBe("Speaker 64");
    expect(speakerTranscriptSpeakerLabel(null)).toBe("Unknown speaker");
  });

  it("does not hide attribution when any turn is unknown", () => {
    const projection = projectSpeakerTranscript(
      [turn(0), { ...turn(1), speakerId: null }],
      0,
    );

    expect(projection.mode).toBe("attributed");
  });

  it("keeps every attributed page within the fixed DOM bound", () => {
    const turns = Array.from({ length: speakerTranscriptPageSize * 3 + 17 }, (_, index) => turn(index));
    turns[1] = { ...turns[1], speakerId: "speaker-2" };

    const first = projectSpeakerTranscript(turns, 0);
    const middle = projectSpeakerTranscript(turns, 1);
    const last = projectSpeakerTranscript(turns, Number.MAX_SAFE_INTEGER);

    expect(first.mode).toBe("attributed");
    expect(middle.mode).toBe("attributed");
    expect(last.mode).toBe("attributed");
    if (first.mode !== "attributed" || middle.mode !== "attributed" || last.mode !== "attributed") {
      throw new Error("Expected attributed projections");
    }
    expect(first.turns).toHaveLength(speakerTranscriptPageSize);
    expect(middle.turns).toHaveLength(speakerTranscriptPageSize);
    expect(last.turns).toHaveLength(17);
    expect(last.index).toBe(3);
    expect(last.end).toBe(turns.length);
  });
});
