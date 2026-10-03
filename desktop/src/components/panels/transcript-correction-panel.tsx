import { Copy } from "@phosphor-icons/react/Copy";
import { DownloadSimple } from "@phosphor-icons/react/DownloadSimple";
import { FloppyDisk as Save } from "@phosphor-icons/react/FloppyDisk";
import { Sparkle as Sparkles } from "@phosphor-icons/react/Sparkle";

import { TranscriptCorrectionPreview } from "@/components/transcript-correction/transcript-correction-preview";
import { useAcceptedTranscriptCorrection } from "@/components/transcript-correction/use-accepted-transcript-correction";
import { useTranscriptCorrection } from "@/components/transcript-correction/use-transcript-correction";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RequestCancelButton } from "@/components/ui/request-cancel-button";
import { ButtonGroup } from "@/components/ui/button-group";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { basename } from "@/lib/media-file";
import type { RecordingJobView } from "@/lib/recording-job";
import type {
  AcceptedCorrectionExportAction,
  AcceptedCorrectionExportFailure,
} from "@/hooks/use-transcript-file-actions";

export function TranscriptCorrectionPanel({
  available,
  exportBusy,
  exportFailure,
  onExportAccepted,
  item,
  onOpenHelp,
  onOpenHistory,
  onOpenSettings,
  originalText,
}: {
  available: boolean;
  exportBusy: boolean;
  exportFailure?: AcceptedCorrectionExportFailure;
  onExportAccepted: AcceptedCorrectionExportAction;
  item?: RecordingJobView;
  onOpenHelp?: () => void;
  onOpenHistory?: () => void;
  onOpenSettings?: () => void;
  originalText?: string;
}) {
  const correction = useTranscriptCorrection({ available, item });
  const saved = useAcceptedTranscriptCorrection({
    outputPath: item?.outputPath ?? "",
    ready: correction.ready,
    publication: correction.published?.revisionPath,
  });
  const exportError =
    exportFailure?.path === item?.outputPath &&
    exportFailure?.revision === saved.revision?.revision &&
    exportFailure?.correctedSha256 === saved.revision?.correctedSha256
      ? exportFailure?.message
      : undefined;
  return (
    <Card className="surface-workspace-inset min-w-0 bg-card py-0">
      <CardHeader className="p-4 sm:p-5">
        <Badge
          className="w-fit"
          variant={correction.ready && available ? "default" : "secondary"}
        >
          <Sparkles data-icon="inline-start" />
          Transcript correction
        </Badge>
        <CardTitle aria-level={2} className="mt-3 text-2xl" role="heading">
          {correction.ready
            ? "Review transcript corrections"
            : "Waiting on a transcript"}
        </CardTitle>
        <CardDescription className="break-words">
          {item
            ? item.name
            : "Choose a finished transcript. Your original stays unchanged."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 sm:p-5">
        {!available ? (
          <Alert>
            <AlertDescription>
              New correction suggestions are unavailable on the current server
              connection. Your original and saved accepted revisions remain
              available.
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {onOpenHistory ? (
            <Button onClick={onOpenHistory} type="button" variant="outline">
              Choose a transcript
            </Button>
          ) : null}
          {!available && onOpenSettings ? (
            <Button onClick={onOpenSettings} type="button" variant="outline">
              Check server settings
            </Button>
          ) : null}
          {correction.active ? (
            <RequestCancelButton
              onCancel={correction.cancel}
              requestId={correction.view?.requestId}
            />
          ) : (
            <Button
              disabled={!correction.canRun}
              onClick={() => void correction.run()}
              type="button"
              variant={correction.correctedText ? "secondary" : "default"}
            >
              <Sparkles data-icon="inline-start" />
              {correction.correctedText ? "Run again" : "Correct transcript"}
            </Button>
          )}
          {correction.correctedText ? (
            <ButtonGroup aria-label="Corrected transcript actions">
              <Button
                onClick={() => void correction.copy()}
                type="button"
                variant="secondary"
              >
                <Copy data-icon="inline-start" />
                Copy
              </Button>
              <Button
                disabled={
                  !correction.view?.applied ||
                  Boolean(correction.published) ||
                  correction.publishing
                }
                onClick={() => void correction.publish()}
                type="button"
                variant="default"
              >
                {correction.publishing ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <Save data-icon="inline-start" />
                )}
                Save revision
              </Button>
            </ButtonGroup>
          ) : null}
        </div>

        <div className="text-sm leading-6 text-muted-foreground">
          <p>{correction.statusLine}</p>
          {correction.correctedText ? (
            <p>Saving accepts these suggested edits as a separate revision.</p>
          ) : null}
        </div>

        {correction.ready ? (
          <div className="grid gap-2 border-t border-border/60 pt-4">
            <div
              aria-live="polite"
              className="flex flex-wrap items-center justify-between gap-2 text-sm"
            >
              <p className="font-medium">
                {saved.loading
                  ? "Reading saved corrections…"
                  : saved.revision
                    ? `Saved accepted revision ${saved.revision.revision}`
                    : "Saved corrections"}
              </p>
              {saved.revision ? (
                <div
                  className="flex flex-wrap gap-2"
                  role="group"
                  aria-label="Saved correction actions"
                >
                  <Button
                    onClick={() => void saved.copy()}
                    type="button"
                    variant="outline"
                  >
                    <Copy data-icon="inline-start" />
                    Copy saved correction
                  </Button>
                  <Button
                    aria-label="Export saved correction"
                    aria-disabled={exportBusy || undefined}
                    className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
                    onClick={() => {
                      if (!exportBusy)
                        void saved.exportRevision(onExportAccepted);
                    }}
                    title="Save this accepted revision as UTF-8 text. Choose a new filename; existing files are preserved."
                    type="button"
                    variant="outline"
                  >
                    <DownloadSimple data-icon="inline-start" />
                    {exportBusy ? "Exporting…" : "Export saved correction"}
                  </Button>
                </div>
              ) : null}
            </div>
            {saved.revisionCount > 1 ? (
              <div className="grid min-w-0 gap-2">
                <label className="grid gap-2 text-sm font-medium">
                  Accepted revision
                  <select
                    className="h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    disabled={exportBusy}
                    value={saved.selectedRevision}
                    onChange={(event) =>
                      saved.selectRevision(Number(event.target.value))
                    }
                  >
                    {Array.from({ length: saved.revisionCount }, (_, index) => {
                      const number = saved.revisionCount - index;
                      return (
                        <option key={number} value={number}>
                          Revision {number}
                          {number === saved.revisionCount ? " · Latest" : ""}
                        </option>
                      );
                    })}
                  </select>
                </label>
                <p className="text-sm leading-6 text-muted-foreground">
                  Reading an earlier revision leaves your latest acceptance
                  unchanged.
                </p>
              </div>
            ) : null}
            {exportError ? (
              <Alert variant="destructive">
                <AlertDescription>{exportError}</AlertDescription>
              </Alert>
            ) : null}
            {exportError ? (
              <Button
                className="w-fit"
                disabled={exportBusy || saved.loading}
                onClick={() => void saved.reload()}
                type="button"
                variant="outline"
              >
                Refresh saved corrections
              </Button>
            ) : null}
            {saved.error ? (
              <Alert variant="destructive">
                <AlertDescription>
                  {saved.error} Your original and correction files are
                  unchanged.
                </AlertDescription>
              </Alert>
            ) : null}
            {saved.error ? (
              <Button
                className="w-fit"
                onClick={() => void saved.reload()}
                type="button"
                variant="outline"
              >
                Retry saved corrections
              </Button>
            ) : null}
            {!saved.loading && !saved.error && !saved.revision ? (
              <p className="text-sm leading-6 text-muted-foreground">
                No accepted revision is saved for this transcript.
              </p>
            ) : null}
            {saved.revision && correction.correctedText ? (
              <details className="min-w-0 rounded-lg border border-border p-3">
                <summary className="w-fit cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  Read the previously accepted revision
                </summary>
                <pre className="mt-3 max-h-[260px] overflow-auto whitespace-pre-wrap break-words font-sans text-[15px] leading-7">
                  {saved.revision.correctedText}
                </pre>
              </details>
            ) : null}
          </div>
        ) : null}

        <TranscriptCorrectionPreview
          corrected={correction.correctedText ?? saved.revision?.correctedText}
          correctedTitle={
            correction.correctedText
              ? "Suggested correction"
              : saved.revision
                ? `Saved revision ${saved.revision.revision}`
                : "Suggested correction"
          }
          original={originalText}
        />

        {correction.error ? (
          <Alert variant="destructive">
            <AlertDescription>
              {correction.error} Raw transcript unchanged.
            </AlertDescription>
          </Alert>
        ) : null}
        {correction.published ? (
          <Alert>
            <Save />
            <AlertDescription>
              Saved immutable revision {correction.published.revision} as{" "}
              <span className="font-medium text-foreground">
                {basename(correction.published.revisionPath)}
              </span>
            </AlertDescription>
          </Alert>
        ) : null}
        {!correction.ready && onOpenHelp ? (
          <Button
            className="h-auto w-fit px-0"
            onClick={onOpenHelp}
            type="button"
            variant="link"
          >
            How transcript correction works
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
