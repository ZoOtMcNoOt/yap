import {
  transcriptResultSummaryLabels,
  type TranscriptResultSummary,
} from "@/lib/transcript-result-summary";
import { cn } from "@/lib/utils";

export function TranscriptResultSummaryLine({
  className,
  summary,
}: {
  className?: string;
  summary?: TranscriptResultSummary;
}) {
  if (!summary) return null;
  const labels = transcriptResultSummaryLabels(summary);
  return (
    <span
      aria-label="Transcript result details"
      className={cn("block text-xs text-muted-foreground", className)}
    >
      {[labels.language, labels.timing, labels.corrections].filter(Boolean).join(" · ")}
    </span>
  );
}
