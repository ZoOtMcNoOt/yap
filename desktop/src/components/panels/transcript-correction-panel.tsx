import { Copy } from "@phosphor-icons/react/Copy";
import { FloppyDisk as Save } from "@phosphor-icons/react/FloppyDisk";
import { Sparkle as Sparkles } from "@phosphor-icons/react/Sparkle";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { TranscriptCorrectionPreview } from "@/components/transcript-correction/transcript-correction-preview";
import { useTranscriptCorrection } from "@/components/transcript-correction/use-transcript-correction";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { basename } from "@/lib/media-file";
import type { RecordingJobView } from "@/lib/recording-job";

export function TranscriptCorrectionPanel({
  available,
  item,
  onOpenHelp,
  originalText,
}: {
  available: boolean;
  item?: RecordingJobView;
  onOpenHelp?: () => void;
  originalText?: string;
}) {
  const correction = useTranscriptCorrection({ available, item });
  return (
    <Card className="surface-workspace-inset min-w-0 bg-card py-0">
      <CardHeader className="p-4 sm:p-5">
        <Badge className="w-fit" variant={correction.ready && available ? "default" : "secondary"}>
          <Sparkles data-icon="inline-start" />
          Transcript correction
        </Badge>
        <CardTitle className="mt-3 text-2xl">
          {correction.ready ? "Review source-bound corrections" : "Waiting on a transcript"}
        </CardTitle>
        <CardDescription className="break-words">
          {item
            ? item.name
            : "Select or transcribe a recording. Raw ASR is always preserved."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 sm:p-5">
        {!available ? (
          <Alert>
            <AlertDescription>
              Transcript correction needs your connected organization server. Local recording,
              playback, and raw transcripts remain available.
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {correction.active ? (
            <Button onClick={() => void correction.cancel()} type="button" variant="secondary">
              <XCircle data-icon="inline-start" />
              Cancel
            </Button>
          ) : (
            <Button disabled={!correction.canRun} onClick={() => void correction.run()} type="button">
              <Sparkles data-icon="inline-start" />
              Correct transcript
            </Button>
          )}
          {correction.correctedText ? (
            <ButtonGroup aria-label="Corrected transcript actions">
              <Button onClick={() => void correction.copy()} type="button" variant="secondary">
                <Copy data-icon="inline-start" />
                Copy
              </Button>
              <Button
                disabled={!correction.view?.applied || Boolean(correction.published) || correction.publishing}
                onClick={() => void correction.publish()}
                type="button"
                variant="secondary"
              >
                {correction.publishing ? <Spinner data-icon="inline-start" /> : <Save data-icon="inline-start" />}
                Save revision
              </Button>
            </ButtonGroup>
          ) : null}
        </div>

        <TranscriptCorrectionPreview corrected={correction.correctedText} original={originalText} />

        <div className="text-sm leading-6 text-muted-foreground">
          <p>{correction.statusLine}</p>
          <p>Organization server · immutable raw transcript · manual acceptance</p>
        </div>

        {correction.error ? (
          <Alert variant="destructive">
            <AlertDescription>{correction.error} Raw transcript unchanged.</AlertDescription>
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
          <Button className="h-auto w-fit px-0" onClick={onOpenHelp} type="button" variant="link">
            How transcript correction works
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
