import { useEffect, useId, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  loadLanguageLabelReview,
  saveLanguageLabelCorrection,
  type LanguageLabelReview,
  type LanguageLabelReviewSegment,
} from "@/history-catalog";
import type { TranscriptHistoryEntry } from "@/history-model";
import type { FixedBatchLanguageOption } from "@/language-preference";
import { formatLanguageTag } from "@/lib/language-display";

const UNKNOWN_LANGUAGE_VALUE = "__unknown__";
const INITIAL_VISIBLE_SEGMENTS = 50;

function errorMessage(error: unknown) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return String(error);
}

function segmentStatus(segment: LanguageLabelReviewSegment) {
  if (segment.hasUserCorrection) return "User-corrected label";
  if (!segment.effectiveLanguageBcp47) return "Language needs review";
  return "Server-detected label";
}

function availableLanguageTags(
  segment: LanguageLabelReviewSegment,
  options: FixedBatchLanguageOption[],
) {
  return [...new Set([
    ...options.map((option) => option.languageBcp47),
    ...(segment.sourceLanguageBcp47 ? [segment.sourceLanguageBcp47] : []),
    ...(segment.effectiveLanguageBcp47 ? [segment.effectiveLanguageBcp47] : []),
  ])].sort((left, right) => left.localeCompare(right));
}

export function LanguageLabelCorrectionRow({
  disabled,
  languageOptions,
  onSave,
  segment,
}: {
  disabled: boolean;
  languageOptions: FixedBatchLanguageOption[];
  onSave: (segmentIndex: number, replacement: string | null) => Promise<void>;
  segment: LanguageLabelReviewSegment;
}) {
  const labelId = useId();
  const statusId = useId();
  const effectiveValue = segment.effectiveLanguageBcp47 ?? UNKNOWN_LANGUAGE_VALUE;
  const [selection, setSelection] = useState(effectiveValue);
  const tags = useMemo(
    () => availableLanguageTags(segment, languageOptions),
    [languageOptions, segment],
  );

  useEffect(() => {
    setSelection(effectiveValue);
  }, [effectiveValue]);

  const replacement = selection === UNKNOWN_LANGUAGE_VALUE ? null : selection;
  const changed = replacement !== segment.effectiveLanguageBcp47;

  return (
    <li className="grid gap-3 border-t py-3 first:border-t-0 sm:grid-cols-[minmax(0,1fr)_minmax(250px,auto)] sm:items-center">
      <div className="min-w-0">
        <p className="line-clamp-2 text-sm leading-6 text-foreground">
          {segment.text || "Silent or empty transcript segment"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground" id={statusId}>
          Segment {segment.index + 1} · {segmentStatus(segment)}
        </p>
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
        <Label className="sr-only" id={labelId}>
          Language for transcript segment {segment.index + 1}
        </Label>
        <Select disabled={disabled} onValueChange={setSelection} value={selection}>
          <SelectTrigger
            aria-describedby={statusId}
            aria-labelledby={labelId}
            className="min-w-[210px] flex-1 sm:flex-none"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value={UNKNOWN_LANGUAGE_VALUE}>Unknown · needs review</SelectItem>
              {tags.map((tag) => (
                <SelectItem key={tag} value={tag}>
                  {formatLanguageTag(tag)}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          disabled={disabled || !changed}
          onClick={() => void onSave(segment.index, replacement)}
          size="sm"
          type="button"
        >
          Save label
        </Button>
        {segment.hasUserCorrection ? (
          <Button
            disabled={disabled}
            onClick={() => void onSave(segment.index, segment.sourceLanguageBcp47)}
            size="sm"
            type="button"
            variant="ghost"
          >
            Restore server label
          </Button>
        ) : null}
      </div>
    </li>
  );
}

export function LanguageLabelCorrections({
  entry,
  languageOptions,
}: {
  entry: TranscriptHistoryEntry;
  languageOptions: FixedBatchLanguageOption[];
}) {
  const headingId = useId();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [review, setReview] = useState<LanguageLabelReview>();
  const [savingSegment, setSavingSegment] = useState<number>();
  const [showAll, setShowAll] = useState(false);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_SEGMENTS);

  useEffect(() => {
    let current = true;
    setError("");
    setLoading(true);
    setReview(undefined);
    setSavingSegment(undefined);
    setShowAll(false);
    setVisibleCount(INITIAL_VISIBLE_SEGMENTS);
    void loadLanguageLabelReview(entry)
      .then((loaded) => {
        if (current) setReview(loaded);
      })
      .catch((loadError) => {
        if (current) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [entry.origin, entry.outputPath, entry.sessionId]);

  async function save(segmentIndex: number, replacement: string | null) {
    if (!review) return;
    setError("");
    setSavingSegment(segmentIndex);
    try {
      const updated = await saveLanguageLabelCorrection(
        entry,
        review.revision,
        segmentIndex,
        replacement,
      );
      setReview(updated);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSavingSegment(undefined);
    }
  }

  const prioritySegments = review?.segments.filter((segment) => (
    segment.hasUserCorrection || !segment.effectiveLanguageBcp47
  )) ?? [];
  const displayedSegments = (showAll ? review?.segments ?? [] : prioritySegments)
    .slice(0, visibleCount);
  const totalDisplayedSet = showAll ? review?.segments.length ?? 0 : prioritySegments.length;

  return (
    <section
      aria-labelledby={headingId}
      className="max-h-[min(320px,40vh)] overflow-y-auto border-b bg-muted/20 px-5 py-4 sm:px-8"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium" id={headingId}>Language labels</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Corrections are saved separately. The retained audio, transcript, and server result stay unchanged.
          </p>
        </div>
        {review ? (
          <p className="text-xs text-muted-foreground" role="status">
            {review.reviewRequiredCount} need review · {review.activeCorrectionCount} corrected
          </p>
        ) : null}
      </div>
      {error ? (
        <Alert className="mt-3" role="alert" variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {loading ? (
        <p className="mt-3 text-sm text-muted-foreground" role="status">Loading language labels…</p>
      ) : review ? (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              onClick={() => {
                setShowAll((current) => !current);
                setVisibleCount(INITIAL_VISIBLE_SEGMENTS);
              }}
              size="sm"
              type="button"
              variant="secondary"
            >
              {showAll ? "Show labels needing attention" : "Show all transcript labels"}
            </Button>
          </div>
          {!displayedSegments.length ? (
            <p className="mt-3 text-sm text-muted-foreground">
              No labels currently need attention. Show all transcript labels to correct a detected language.
            </p>
          ) : (
            <ul className="mt-3">
              {displayedSegments.map((segment) => (
                <LanguageLabelCorrectionRow
                  disabled={savingSegment !== undefined}
                  key={segment.index}
                  languageOptions={languageOptions}
                  onSave={save}
                  segment={segment}
                />
              ))}
            </ul>
          )}
          {visibleCount < totalDisplayedSet ? (
            <Button
              className="mt-2"
              onClick={() => setVisibleCount((count) => count + INITIAL_VISIBLE_SEGMENTS)}
              size="sm"
              type="button"
              variant="ghost"
            >
              Show 50 more labels
            </Button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
