import { Copy } from "@phosphor-icons/react/Copy";
import type { MouseEvent } from "react";

import { HistoryActionMenu } from "@/components/history/history-action-menu";
import type { HistoryEntryActions } from "@/components/history/history-panel-contract";
import { HistoryEntryPreview } from "@/components/panels/history-entry-preview";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  isAudioOnlySavedRecording,
  isRecoverableTranscriptHistoryEntry,
  isUntrustedNativeLiveTranscriptHistoryEntry,
} from "@/native-history";
import type { TranscriptHistoryEntry } from "@/history-model";
import { formatHistoryTime } from "@/lib/display-format";
import { cn } from "@/lib/utils";

type HistoryGroup = {
  entries: TranscriptHistoryEntry[];
  key: string;
  label: string;
};

function HistoryEntryRow({
  actions,
  entry,
  loadPreviewText,
  onSelect,
  selectedOutputPath,
}: {
  actions: HistoryEntryActions;
  entry: TranscriptHistoryEntry;
  loadPreviewText: (entry: TranscriptHistoryEntry) => Promise<string>;
  onSelect: (entry: TranscriptHistoryEntry, origin?: DOMRect) => void;
  selectedOutputPath?: string;
}) {
  const selected = entry.outputPath === selectedOutputPath;
  const recoverable = isRecoverableTranscriptHistoryEntry(entry);
  const hideOnly = isUntrustedNativeLiveTranscriptHistoryEntry(entry);
  const audioOnly = isAudioOnlySavedRecording(entry);
  const selectable = !recoverable && !hideOnly && !audioOnly;

  function selectEntry(event: MouseEvent<HTMLElement>) {
    if (!selectable) return;
    const row = event.currentTarget.closest("[data-history-entry-row]");
    onSelect(entry, row?.getBoundingClientRect());
  }

  return (
    <TableRow
      aria-current={selected ? "true" : undefined}
      className={cn(
        selected && "border-primary/30 bg-[var(--primary-soft)]/40 hover:bg-[var(--primary-soft)]/40",
      )}
      data-state={selected ? "selected" : undefined}
      data-history-entry-row
    >
      <TableCell
        className={cn(
          "w-24 align-top text-xs tabular-nums text-muted-foreground",
          selectable && "cursor-pointer",
        )}
        onClick={selectable ? selectEntry : undefined}
      >
        {formatHistoryTime(entry.createdAt)}
      </TableCell>
      <TableCell
        className={cn(
          "max-w-0 whitespace-normal align-top",
          selectable && "cursor-pointer",
        )}
        onClick={selectable ? selectEntry : undefined}
      >
        <div className="flex min-w-0 items-start gap-2">
          {audioOnly ? (
            <button aria-label={`Open recording ${entry.name}`} className="min-w-0 text-left" onClick={() => actions.onOpen(entry)} type="button">
              <span className="block truncate font-medium">{entry.name}</span>
              <span className="text-xs text-muted-foreground">Saved audio</span>
            </button>
          ) : recoverable ? (
            <span className="shrink-0 text-xs font-medium text-muted-foreground">Partial</span>
          ) : hideOnly ? (
            <span className="truncate text-sm text-muted-foreground">{entry.name}</span>
          ) : (
            <HistoryEntryPreview
              entry={entry}
              onLoadPreviewText={loadPreviewText}
              onReview={(origin) => onSelect(entry, origin)}
            />
          )}
        </div>
        {audioOnly && entry.warning ? <p className="mt-1 text-xs text-muted-foreground">{entry.warning}</p> : null}
      </TableCell>
      <TableCell className="w-[4.5rem] align-top text-right">
        <div className="flex items-center justify-end gap-0.5">
          {selectable ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  aria-label={`Copy transcript for ${entry.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    actions.onCopy(entry);
                  }}
                  size="icon-xs"
                  title="Copy"
                  type="button"
                  variant="ghost"
                >
                  <Copy />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Copy</TooltipContent>
            </Tooltip>
          ) : null}
          <HistoryActionMenu actions={actions} entry={entry} />
        </div>
      </TableCell>
    </TableRow>
  );
}

export function HistoryResults({
  actions,
  groups,
  hiddenCount,
  indexingBodies,
  loadPreviewText,
  nextLimit,
  onRetrySearch,
  onSelect,
  onShowOlder,
  selectedOutputPath,
  unavailablePreviewPaths,
}: {
  actions: HistoryEntryActions;
  groups: HistoryGroup[];
  hiddenCount: number;
  indexingBodies: boolean;
  loadPreviewText: (entry: TranscriptHistoryEntry) => Promise<string>;
  nextLimit: number;
  onRetrySearch: () => void;
  onSelect: (entry: TranscriptHistoryEntry, origin?: DOMRect) => void;
  onShowOlder: (nextLimit: number) => void;
  selectedOutputPath?: string;
  unavailablePreviewPaths: ReadonlySet<string>;
}) {
  return (
    <div className="flex flex-col gap-6">
      {indexingBodies || unavailablePreviewPaths.size > 0 ? (
        <div
          aria-live="polite"
          className="flex items-center justify-between gap-3 text-xs text-muted-foreground"
          role="status"
        >
          <span>
            {indexingBodies
              ? "Searching more transcript text. Results may be incomplete."
              : "Some transcript text is unavailable. Results may be incomplete."}
          </span>
          {unavailablePreviewPaths.size > 0 ? (
            <Button onClick={onRetrySearch} size="sm" type="button" variant="ghost">
              Retry
            </Button>
          ) : null}
        </div>
      ) : null}
      {groups.map((group) => (
        <section key={group.key}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {group.label}
          </h3>
          <Table>
            <TableBody>
              {group.entries.map((entry) => (
                <HistoryEntryRow
                  actions={actions}
                  entry={entry}
                  key={entry.outputPath}
                  loadPreviewText={loadPreviewText}
                  onSelect={onSelect}
                  selectedOutputPath={selectedOutputPath}
                />
              ))}
            </TableBody>
          </Table>
        </section>
      ))}
      {hiddenCount ? (
        <Button
          className="self-center"
          onClick={() => onShowOlder(nextLimit)}
          size="sm"
          type="button"
          variant="outline"
        >
          Show older
        </Button>
      ) : null}
    </div>
  );
}
