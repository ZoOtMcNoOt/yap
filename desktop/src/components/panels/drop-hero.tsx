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
import type { FixedBatchLanguageOption } from "@/language-preference";
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
  selectedLanguage,
}: {
  dragging: boolean;
  onDragLeave: () => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onOpenHelp?: () => void;
  onOpenLanguageSettings: () => void;
  onLanguageChange: (languageBcp47: string) => void;
  onPickFiles: () => void;
  languageOptions: FixedBatchLanguageOption[];
  selectedLanguage: string | null;
}) {
  const languageReady = languageOptions.some(
    (option) => option.languageBcp47 === selectedLanguage,
  );
  return (
    <section
      className={cn(
        "surface-workspace-inset mt-5 w-full border-2 border-dashed bg-[var(--surface-transcript)] transition-[border-color,background-color,box-shadow] duration-200",
        dragging ? "border-primary bg-[var(--primary-soft)] shadow-sm" : "border-border",
      )}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="flex min-h-[168px] flex-col items-center justify-center gap-4 px-6 py-8 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-secondary">
          <UploadCloud className="text-primary" />
        </div>
        <div className="max-w-md">
          <h2 className="text-lg font-semibold tracking-tight">Drop recordings here</h2>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            Choose a language, then add files to your organization's transcription server queue. Dropped files use your primary language. {acceptedFormats}.
          </p>
        </div>
        <div className="flex w-full max-w-md flex-wrap items-center justify-center gap-2">
          <Select
            disabled={!languageOptions.length}
            onValueChange={onLanguageChange}
            value={selectedLanguage ?? undefined}
          >
            <SelectTrigger aria-label="Recording language" className="min-w-[220px] flex-1">
              <SelectValue placeholder="Choose recording language" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {languageOptions.map((option) => (
                  <SelectItem key={option.languageBcp47} value={option.languageBcp47}>
                    {option.languageBcp47} · {qualityLabel(option.qualityTier)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          {!languageReady ? (
            <Button onClick={onOpenLanguageSettings} size="sm" type="button" variant="outline">
              Set primary language
            </Button>
          ) : null}
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
    </section>
  );
}

function qualityLabel(quality: FixedBatchLanguageOption["qualityTier"]) {
  switch (quality) {
    case "transcriptionReady":
      return "Transcription ready";
    case "broadCoverage":
      return "Broad coverage";
    case "preview":
      return "Preview";
  }
}
