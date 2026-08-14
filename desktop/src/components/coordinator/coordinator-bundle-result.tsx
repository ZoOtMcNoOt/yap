import { FileText } from "@phosphor-icons/react/FileText";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CoordinatorProposalBundle } from "@/coordinator";

export function CoordinatorBundleResult({ bundle }: { bundle: CoordinatorProposalBundle }) {
  return (
    <Card className="border-primary/20 bg-card py-0 shadow-none">
      <CardHeader className="gap-2 p-4 pb-2">
        <Badge className="w-fit" variant="secondary">
          <FileText data-icon="inline-start" />
          Review required · noncanonical
        </Badge>
        <CardTitle className="text-lg leading-7">Selected proposal bundle</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 pt-1">
        {bundle.items.map((item, itemIndex) => (
          <article className="grid gap-3 rounded-lg border border-border/70 p-3" key={item.proposalId}>
            <h4 className="text-sm font-semibold">Proposal {itemIndex + 1}</h4>
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {item.proposedContent}
            </p>
            <div className="grid gap-2">
              <h5 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Reviewed sources
              </h5>
              {item.citations.map((citation, citationIndex) => (
                <div
                  className="grid gap-1 border-l-2 border-primary/40 pl-3"
                  key={`${citation.conceptId}:${citation.sourceRevision}:${citation.charStart}:${citation.charEnd}`}
                >
                  <p className="break-all text-xs leading-5 text-muted-foreground">
                    Source {citationIndex + 1} · {citation.conceptId} · characters {citation.charStart}–{citation.charEnd}
                  </p>
                  <blockquote className="whitespace-pre-wrap break-words text-sm leading-6">
                    {citation.text}
                  </blockquote>
                </div>
              ))}
            </div>
          </article>
        ))}
        <p className="text-xs leading-5 text-muted-foreground">
          This bundle does not publish, activate, schedule, or modify organization knowledge.
        </p>
      </CardContent>
    </Card>
  );
}
