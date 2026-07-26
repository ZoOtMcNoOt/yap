import { useEffect, useState } from "react";
import { toast } from "sonner";

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
  type FixedBatchLanguageOption,
} from "@/language-preference";
import { formatLanguageTag } from "@/lib/language-display";
import type { RecordingJobView, RecordingLanguageReview } from "@/lib/recording-job";

export function languageReviewExplanation(review: RecordingLanguageReview) {
  if (review.kind === "suggestion" && review.suggestedLanguageBcp47) {
    return `Yap detected ${formatLanguageTag(review.suggestedLanguageBcp47)} in independent speech samples. Confirm it or choose another language.`;
  }
  switch (review.reason) {
    case "invalid_model_label":
      return "The language detector returned a label Yap could not safely interpret. Choose the recording language.";
    case "language_disagreement":
      return "Independent speech samples pointed to different languages. Choose the language that should guide transcription.";
    case "unsupported_language":
      return "The detected language is not available in the current server catalog. Choose an available recording language.";
    case "ambiguous_locale":
      return "The detected language maps to more than one available locale. Choose the intended locale.";
    case "short_recording":
      return "There was not enough speech to identify the language safely. Choose the recording language.";
    default:
      return "Yap could not make a safe language suggestion. Confirm the language before transcription.";
  }
}

export function LanguageReviewActions({
  item,
  languageOptions,
  onConfirm,
}: {
  item: RecordingJobView;
  languageOptions: FixedBatchLanguageOption[];
  onConfirm: (jobId: string, languageBcp47: string) => Promise<void>;
}) {
  const review = item.languageReview;
  const supportedLanguages = new Set(languageOptions.map((option) => option.languageBcp47));
  const initialSelection = [
    review?.suggestedLanguageBcp47,
    item.languageDecision?.languageBcp47,
  ].find((language): language is string => Boolean(language && supportedLanguages.has(language))) ?? "";
  const [selection, setSelection] = useState(initialSelection);
  const [saving, setSaving] = useState(false);

  useEffect(() => setSelection(initialSelection), [initialSelection, item.id]);
  if (!review) return null;

  const suggested = review.kind === "suggestion" && review.suggestedLanguageBcp47;
  const explanation = languageReviewExplanation(review);

  return (
    <div
      className="mt-2 rounded-lg border border-border/70 bg-muted/35 p-3"
      onClick={(event) => event.stopPropagation()}
    >
      <p className="text-sm font-medium">Confirm recording language</p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{explanation}</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <Select disabled={saving || !languageOptions.length} onValueChange={setSelection} value={selection}>
          <SelectTrigger aria-label={`Language for ${item.name}`} className="min-w-0 flex-1">
            <SelectValue placeholder="Choose a language" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {languageOptions.map((language) => (
                <SelectItem key={language.languageBcp47} value={language.languageBcp47}>
                  {formatLanguageTag(language.languageBcp47)} · {fixedBatchQualityLabel(language.qualityTier)}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          disabled={saving || !selection || !supportedLanguages.has(selection)}
          onClick={async () => {
            setSaving(true);
            try {
              await onConfirm(item.id, selection);
            } catch {
              toast.error("Language could not be confirmed. Refresh server capabilities and try again.");
            } finally {
              setSaving(false);
            }
          }}
          size="sm"
          type="button"
        >
          {saving ? "Confirming…" : suggested === selection ? "Use suggestion" : "Confirm language"}
        </Button>
      </div>
      {!languageOptions.length ? (
        <p className="mt-2 text-xs text-destructive">
          Current server language capabilities are unavailable.
        </p>
      ) : null}
    </div>
  );
}
