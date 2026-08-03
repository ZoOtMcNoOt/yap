import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { QueuePanel } from "@/components/panels/queue-panel";
import { TooltipProvider } from "@/components/ui/tooltip";
import { createInitialPipelineState, type RecordingJobView } from "@/lib/recording-job";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("imported recording queue surface", () => {
  it("renders no local execution action or synthetic queue progress without a connector", () => {
    const item: RecordingJobView = {
      error: "Server unavailable",
      id: "job-meeting",
      name: "meeting.wav",
      sourcePath: "C:/meeting.wav",
      pipeline: createInitialPipelineState(),
      route: "serverBatch",
      sessionMode: "meeting",
      sessionOrigin: "importedFile",
      status: "failed",
    };
    const legacyExecutionProps = {
      completed: 0,
      elapsedSeconds: 0,
      hasRunnable: true,
      onRetry: vi.fn(),
      onRun: vi.fn(),
      queueProgress: 0,
      running: false,
    };

    const html = renderToStaticMarkup(
      <TooltipProvider>
        <QueuePanel
          {...legacyExecutionProps}
          languageOptions={[]}
          onClear={vi.fn()}
          onConfirmLanguage={vi.fn()}
          onRemove={vi.fn()}
          onReveal={vi.fn()}
          onSelect={vi.fn()}
          queue={[item]}
        />
      </TooltipProvider>,
    );

    expect(html).not.toContain("Transcribe</button>");
    expect(html).not.toContain("Queue progress");
  });

  it("contains no local-batch compatibility path in the owned frontend surface", () => {
    expect(source("../../src/App.tsx")).not.toMatch(/startTranscribe|transcribeItems|runQueue/);
    expect(source("../../src/App.tsx")).toContain("useRecordingJobs");
    expect(source("../../src/hooks/use-imported-recording-queue.ts"))
      .not.toMatch(/queued_local_fallback|local_transcribing|migration|legacyDiscard/);
    expect(source("../../src/components/panels/queue-panel.tsx"))
      .not.toMatch(/migration|Discard old queue|Restoring queued recordings/);
  });

  it("keeps cancellation reachable while a remote job is active", () => {
    const item: RecordingJobView = {
      id: "job-uploading",
      name: "meeting.wav",
      sourcePath: "C:/meeting.wav",
      pipeline: createInitialPipelineState(),
      route: "serverBatch",
      sessionMode: "meeting",
      sessionOrigin: "importedFile",
      status: "uploading",
    };

    const html = renderToStaticMarkup(
      <TooltipProvider>
        <QueuePanel
          languageOptions={[]}
          onClear={vi.fn()}
          onConfirmLanguage={vi.fn()}
          onRemove={vi.fn()}
          onReveal={vi.fn()}
          onSelect={vi.fn()}
          queue={[item]}
        />
      </TooltipProvider>,
    );

    expect(html).toContain('aria-label="Cancel recording"');
    expect(html).not.toMatch(/aria-label="Cancel recording"[^>]*disabled/);
  });

  it("renders a bounded language suggestion with current catalog choices", () => {
    const item: RecordingJobView = {
      id: "job-language-review",
      languageDecision: {
        disposition: "primary",
        languageBcp47: "en-US",
        mode: "fixed",
      },
      languageReview: {
        catalogRevision: "a".repeat(64),
        kind: "suggestion",
        reason: "mapped_language_agreement",
        suggestedLanguageBcp47: "fr-FR",
      },
      name: "meeting.wav",
      sourcePath: "C:/meeting.wav",
      pipeline: createInitialPipelineState(),
      route: "serverBatch",
      sessionMode: "meeting",
      sessionOrigin: "importedFile",
      status: "preflighting",
    };

    const html = renderToStaticMarkup(
      <TooltipProvider>
        <QueuePanel
          languageOptions={[
            { languageBcp47: "en-US", qualityTier: "transcriptionReady" },
            { languageBcp47: "fr-FR", qualityTier: "broadCoverage" },
          ]}
          onClear={vi.fn()}
          onConfirmLanguage={vi.fn()}
          onRemove={vi.fn()}
          onReveal={vi.fn()}
          onSelect={vi.fn()}
          queue={[item]}
        />
      </TooltipProvider>,
    );

    expect(html).toContain("Confirm recording language");
    expect(html).toContain("Yap detected");
    expect(html).toContain("fr-FR");
    expect(html).toContain("Use suggestion");
    expect(html).not.toContain("mapped_language_agreement");
  });

  it("explains manual language review reasons without exposing protocol codes", () => {
    const item: RecordingJobView = {
      id: "job-language-review",
      languageReview: {
        catalogRevision: "a".repeat(64),
        kind: "manual",
        reason: "ambiguous_locale",
      },
      name: "meeting.wav",
      sourcePath: "C:/meeting.wav",
      pipeline: createInitialPipelineState(),
      route: "serverBatch",
      sessionMode: "meeting",
      sessionOrigin: "importedFile",
      status: "preflighting",
    };

    const html = renderToStaticMarkup(
      <TooltipProvider>
        <QueuePanel
          languageOptions={[
            { languageBcp47: "pt-BR", qualityTier: "broadCoverage" },
            { languageBcp47: "pt-PT", qualityTier: "broadCoverage" },
          ]}
          onClear={vi.fn()}
          onConfirmLanguage={vi.fn()}
          onRemove={vi.fn()}
          onReveal={vi.fn()}
          onSelect={vi.fn()}
          queue={[item]}
        />
      </TooltipProvider>,
    );

    expect(html).toContain("maps to more than one available locale");
    expect(html).not.toContain("ambiguous_locale");
  });
});
