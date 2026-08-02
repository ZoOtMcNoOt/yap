import { type DragEvent } from "react";
import { CloudArrowUp as UploadCloud } from "@phosphor-icons/react/CloudArrowUp";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fixedBatchQualityLabel,
  type RecordingImportLanguageOption,
} from "@/language-preference";
import { formatLanguageTag } from "@/lib/language-display";
import { acceptedFormats } from "@/lib/media-file";
import { cn } from "@/lib/utils";

export function DropHero({
  dragging,
  onDragLeave,
  onDragOver,
  onDrop,
  onOpenHelp,
  onOpenLanguageSettings,
  onLanguageChange,
  onPickFiles,
  languageOptions,
  selectedLanguageOptionId,
}: {
  dragging: boolean;
  onDragLeave: () => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onOpenHelp?: () => void;
  onOpenLanguageSettings: () => void;
  onLanguageChange: (optionId: string) => void;
  onPickFiles: () => void;
  languageOptions: RecordingImportLanguageOption[];
  selectedLanguageOptionId: string | null;
}) {
  const languageReady = languageOptions.some(
    (option) => option.id === selectedLanguageOptionId,
  );
  return (
    <section
      className={cn(
        "surface-workspace-inset mt-5 w-full border-2 border-dashed bg-[var(--surface-transcript)] transition-[border-color,background-color,box-shadow] duration-200 motion-reduce:transition-none",
        dragging ? "border-primary bg-[var(--primary-soft)] shadow-sm" : "border-border",
      )}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      {!languageReady ? (
        <div
          className="flex min-h-[168px] flex-col items-center justify-center gap-5 px-6 py-8 text-center"
          data-testid="first-run-welcome"
        >
          <div className="max-w-md">
            <h2 className="text-lg font-semibold tracking-tight">Two steps to your first dictation</h2>
            <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
              Yap types what you say, on this machine, into any app.
            </p>
          </div>
          <ol className="flex max-w-md flex-col gap-3 text-left text-sm leading-6">
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold">1</span>
              <span className="flex flex-wrap items-center gap-2">
                Choose the language you speak.
                <Button onClick={onOpenLanguageSettings} size="sm" type="button">
                  Set my language
                </Button>
              </span>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold">2</span>
              <span>
                Start talking — press <kbd className="rounded border px-1.5 py-0.5 text-xs font-semibold">Ctrl+Shift+Space</kbd>{" "}
                or click the Yap island at the top of your screen.
              </span>
            </li>
          </ol>
          <p className="max-w-md text-xs leading-5 text-muted-foreground">
            On a team? Connect to your organization's server any time from Settings in the sidebar.
          </p>
        </div>
      ) : (
      <div className="flex min-h-[168px] flex-col items-center justify-center gap-4 px-6 py-8 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-secondary">
          <UploadCloud className="text-primary" />
        </div>
        <div className="max-w-md">
          <h2 className="text-lg font-semibold tracking-tight">Drop recordings here</h2>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            Choose a fixed language or verified automatic detection, then add files to your organization's transcription server queue. Dropped files use your primary language. {acceptedFormats}.
          </p>
        </div>
        <div className="flex w-full max-w-md flex-wrap items-center justify-center gap-2">
          <Select
            disabled={!languageOptions.length}
            onValueChange={onLanguageChange}
            value={selectedLanguageOptionId ?? undefined}
          >
            <SelectTrigger aria-label="Recording language" className="min-w-[220px] flex-1">
              <SelectValue placeholder="Choose recording language" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {languageOptions.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.mode === "dynamic"
                      ? `Auto-detect per segment · ${fixedBatchQualityLabel(option.qualityTier)}`
                      : `${formatLanguageTag(option.languageBcp47)} · ${fixedBatchQualityLabel(option.qualityTier)}`}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Button disabled={!languageReady} onClick={onPickFiles} type="button">
            <UploadCloud data-icon="inline-start" />
            Choose files
          </Button>
          <Badge className="border-primary/20 bg-[var(--primary-soft)] text-primary hover:bg-[var(--primary-soft)]" variant="outline">
            <UploadCloud data-icon="inline-start" />
            Organization server queue
          </Badge>
          {onOpenHelp ? (
            <Button
              className="h-auto px-0 text-muted-foreground"
              onClick={onOpenHelp}
              size="sm"
              type="button"
              variant="link"
            >
              How this works
            </Button>
          ) : null}
        </div>
      </div>
      )}
    </section>
  );
}
