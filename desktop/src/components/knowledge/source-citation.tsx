import type { ReactNode } from "react";

import type { LibrarianEvidenceItem } from "@/librarian";

export function SourceCitation({
  citation,
  index,
  children,
}: {
  citation: LibrarianEvidenceItem;
  index: number;
  children?: ReactNode;
}) {
  const name =
    citation.conceptId.split("/").pop()?.replace(/[-_]+/g, " ") ||
    citation.conceptId;
  return (
    <div className="grid min-w-0 gap-2 border-l-2 border-primary/40 pl-3">
      <p className="break-words text-sm font-medium">
        Source {index + 1} · {name}
      </p>
      <blockquote className="whitespace-pre-wrap break-words text-[15px] leading-7">
        {citation.text}
      </blockquote>
      <details className="min-w-0 text-xs leading-5 text-muted-foreground">
        <summary className="w-fit cursor-pointer rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Source {index + 1} details
        </summary>
        <p className="mt-2 break-all">{citation.conceptId}</p>
        <p className="break-all">
          {citation.sourceRevision} · characters {citation.charStart}–
          {citation.charEnd}
        </p>
      </details>
      {children}
    </div>
  );
}
