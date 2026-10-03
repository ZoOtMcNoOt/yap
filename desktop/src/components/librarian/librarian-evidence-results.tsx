import { Question } from "@phosphor-icons/react/Question";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SourceCitation } from "@/components/knowledge/source-citation";
import { Card, CardContent } from "@/components/ui/card";
import type { LibrarianEvidenceItem, LibrarianEvidencePack } from "@/librarian";

export function LibrarianEvidenceResults({
  onCreateLearningPrompt,
  pack,
  studentAvailable = false,
}: {
  onCreateLearningPrompt?: (item: LibrarianEvidenceItem) => void;
  pack: LibrarianEvidencePack;
  studentAvailable?: boolean;
}) {
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
          <CardContent className="p-4">
            <SourceCitation citation={item} index={index}>
              {item.conceptId.startsWith("meetings/") && onCreateLearningPrompt ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    aria-label={`Create learning prompt from Source ${index + 1}`}
                    disabled={!studentAvailable}
                    onClick={() => onCreateLearningPrompt(item)}
                    size="sm"
                    type="button"
                    variant="secondary"
                  >
                    <Question data-icon="inline-start" />
                    Create learning prompt
                  </Button>
                  {!studentAvailable ? (
                    <span className="text-xs leading-5 text-muted-foreground">
                      Student is unavailable on the connected server.
                    </span>
                  ) : null}
                </div>
              ) : null}
            </SourceCitation>
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
