import { Warning } from "@phosphor-icons/react/Warning";

import { SourceCitation } from "@/components/knowledge/source-citation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AuditorReport } from "@/auditor";

export function AuditorReportResult({ report }: { report: AuditorReport }) {
  return (
    <Card className="border-primary/20 bg-card py-0 shadow-none">
      <CardHeader className="gap-2 p-4 pb-2">
        <Badge className="w-fit" variant="secondary">
          <Warning data-icon="inline-start" />
          Review required · noncanonical
        </Badge>
        <CardTitle className="text-lg leading-7">Potential knowledge conflicts</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 pt-1">
        {report.findings.map((finding, findingIndex) => (
          <article className="grid gap-3 rounded-lg border border-border/70 p-3" key={finding.findingSha256}>
            <h4 className="text-sm font-semibold">Finding {findingIndex + 1}</h4>
            <p className="text-sm leading-6">{finding.summary}</p>
            <div className="grid gap-2">
              <h5 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Reviewed sources
              </h5>
              {finding.citations.map((citation, citationIndex) => (
                <SourceCitation
                  citation={citation}
                  index={citationIndex}
                  key={`${citation.conceptId}:${citation.sourceRevision}:${citation.charStart}:${citation.charEnd}`}
                />
              ))}
            </div>
          </article>
        ))}
        <p className="text-xs leading-5 text-muted-foreground">
          This report does not publish, activate, schedule, or modify organization knowledge.
        </p>
      </CardContent>
    </Card>
  );
}
