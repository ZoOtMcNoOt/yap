import { FileText } from "@phosphor-icons/react/FileText";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { LibrarianEvidencePack } from "@/librarian";

export function LibrarianEvidenceResults({ pack }: { pack: LibrarianEvidencePack }) {
  return (
    <section aria-label="Permission-safe knowledge evidence" className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Reviewed evidence</h3>
        <Badge variant="secondary">
          {pack.items.length} {pack.items.length === 1 ? "source" : "sources"}
        </Badge>
      </div>
      {pack.items.map((item, index) => (
        <Card
          className="border-border/70 bg-[var(--surface-transcript)] py-0 shadow-none"
          key={`${item.conceptId}:${item.sourceRevision}:${item.charStart}:${item.charEnd}`}
        >
          <CardHeader className="gap-2 p-4 pb-2">
            <CardTitle className="flex items-start gap-2 text-sm font-medium">
              <FileText aria-hidden="true" className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 break-all">Source {index + 1} · {item.conceptId}</span>
            </CardTitle>
            <p className="text-xs leading-5 text-muted-foreground">
              {item.sourceRevision} · characters {item.charStart}–{item.charEnd}
            </p>
          </CardHeader>
          <CardContent className="p-4 pt-1">
            <blockquote className="whitespace-pre-wrap break-words border-l-2 border-primary/40 pl-3 text-sm leading-6">
              {item.text}
            </blockquote>
          </CardContent>
        </Card>
      ))}
      {pack.outputBudgetExhausted ? (
        <p className="text-xs leading-5 text-muted-foreground">
          More authorized evidence may exist. Refine the query to narrow the result.
        </p>
      ) : null}
    </section>
  );
}
