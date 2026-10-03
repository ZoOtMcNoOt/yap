import { Copy } from "@phosphor-icons/react/Copy";
import { FileText } from "@phosphor-icons/react/FileText";
import { FolderOpen } from "@phosphor-icons/react/FolderOpen";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { TranscriptHistoryEntry } from "@/history-model";
import { projectTranscriptText } from "@/lib/transcript-text";

export function TranscriptPreviewDialog({
  entry,
  onCopy,
  onOpen,
  onOpenChange,
  onReveal,
  onRetry,
  error,
  text,
}: {
  entry?: TranscriptHistoryEntry;
  onCopy: (entry: TranscriptHistoryEntry) => void;
  onOpen: (entry: TranscriptHistoryEntry) => void;
  onOpenChange: (open: boolean) => void;
  onReveal: (entry: TranscriptHistoryEntry) => void;
  onRetry?: (entry: TranscriptHistoryEntry) => void;
  error?: string;
  text?: string;
}) {
  const transcriptText = projectTranscriptText(text);

  return (
    <Dialog onOpenChange={onOpenChange} open={Boolean(entry)}>
      <DialogContent className="max-h-[86vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{entry?.name ?? "Transcript preview"}</DialogTitle>
          <DialogDescription className="truncate">{entry?.outputPath ?? "Local transcript"}</DialogDescription>
        </DialogHeader>
        <ScrollArea className="max-h-[58vh] rounded-md border bg-muted">
          {error ? (
            <div className="grid gap-3 p-4" role="alert">
              <p className="text-sm">{error}</p>
              {entry && onRetry ? <Button className="w-fit" onClick={() => onRetry(entry)} type="button" variant="outline">Retry preview</Button> : null}
            </div>
          ) : <pre aria-live="polite" className="whitespace-pre-wrap break-words p-4 font-sans text-[15px] leading-7">{transcriptText.text}</pre>}
        </ScrollArea>
        {entry ? (
          <DialogFooter>
            <Button onClick={() => onCopy(entry)} type="button" variant="outline">
              <Copy data-icon="inline-start" />
              Copy
            </Button>
            <Button onClick={() => onOpen(entry)} type="button" variant="outline">
              <FileText data-icon="inline-start" />
              Open
            </Button>
            <Button onClick={() => onReveal(entry)} type="button">
              <FolderOpen data-icon="inline-start" />
              Reveal
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
