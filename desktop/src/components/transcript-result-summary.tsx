import { Badge } from "@/components/ui/badge";
import {
  transcriptResultSummaryLabels,
  type TranscriptResultSummary,
} from "@/lib/transcript-result-summary";
import { cn } from "@/lib/utils";

export function TranscriptResultSummaryBadges({
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
      className={cn("flex flex-wrap gap-1.5", className)}
      role="group"
    >
      <Badge variant="outline">{labels.language}</Badge>
      <Badge variant="outline">{labels.timing}</Badge>
      {labels.corrections ? <Badge variant="outline">{labels.corrections}</Badge> : null}
    </span>
  );
}
