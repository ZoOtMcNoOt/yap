import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { TranscriptPanel } from "@/components/panels/transcript-panel";
import type { RecordingJobView } from "@/lib/recording-job";
import type { SpeakerTranscriptDetailState } from "@/lib/speaker-transcript";

const item: RecordingJobView = {
  id: "meeting-1",
  name: "Weekly meeting",
  outputPath: "C:/Yap/weekly-meeting.txt",
  pipeline: {
    alignment: "skipped",
    diarization: "done",
    intake: "done",
    postprocessing: "done",
    preprocessing: "done",
    transcription: "done",
  },
  sessionMode: "meeting",
  sessionOrigin: "importedFile",
  status: "complete",
};

function render(speakerTranscript: SpeakerTranscriptDetailState) {
  return renderToStaticMarkup(
    <TranscriptPanel
      elapsedSeconds={0}
      item={item}
      onCopy={vi.fn()}
      onOpen={vi.fn()}
      onRetry={vi.fn()}
      onReveal={vi.fn()}
      running={false}
      speakerTranscript={speakerTranscript}
      text="A clean transcript without repeated speaker labels."
    />,
  );
}

describe("transcript panel speaker projection", () => {
  it("renders one speaker as the ordinary clean transcript", () => {
    const markup = render({
      sourceResultSha256: "a".repeat(64),
      status: "ready",
      turns: [
        {
          endMs: 2_000,
          speakerId: "speaker-1",
          startMs: 0,
          text: "A clean transcript without repeated speaker labels.",
          turnId: "turn-000001",
        },
      ],
    });

    expect(markup).toContain('data-testid="single-speaker-transcript"');
    expect(markup).not.toContain('data-testid="speaker-attributed-transcript"');
    expect(markup).not.toContain("Speaker 1 ·");
  });

  it("retains attribution when the result contains multiple speakers", () => {
    const markup = render({
      sourceResultSha256: "b".repeat(64),
      status: "ready",
      turns: [
        {
          endMs: 1_000,
          speakerId: "speaker-1",
          startMs: 0,
          text: "A clean transcript",
          turnId: "turn-000001",
        },
        {
          endMs: 2_000,
          speakerId: "speaker-2",
          startMs: 1_000,
          text: "without repeated speaker labels.",
          turnId: "turn-000002",
        },
      ],
    });

    expect(markup).toContain('data-testid="speaker-attributed-transcript"');
    expect(markup).not.toContain('data-testid="single-speaker-transcript"');
    expect(markup).toContain("Speaker 1 ·");
    expect(markup).toContain("Speaker 2 ·");
  });

  it("labels an unattributed Tiron turn without inventing a speaker", () => {
    const markup = render({
      sourceResultSha256: "c".repeat(64),
      status: "ready",
      turns: [
        {
          endMs: 1_000,
          speakerId: "speaker-1",
          startMs: 0,
          text: "A clean transcript",
          turnId: "turn-000001",
        },
        {
          endMs: 2_000,
          speakerId: null,
          startMs: 1_000,
          text: "without invented identity.",
          turnId: "turn-000002",
        },
      ],
    });

    expect(markup).toContain("Unknown speaker ·");
    expect(markup).toContain('data-testid="speaker-attributed-transcript"');
  });
});
