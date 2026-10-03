import { ScrollArea } from "@/components/ui/scroll-area";

type VisibleChange = {
  before: string;
  original: string;
  corrected: string;
  after: string;
};

export function visibleTranscriptChange(
  original: string,
  corrected: string,
): VisibleChange {
  const left = [...original];
  const right = [...corrected];
  let prefix = 0;
  while (
    prefix < left.length &&
    prefix < right.length &&
    left[prefix] === right[prefix]
  )
    prefix += 1;
  let suffix = 0;
  while (
    suffix < left.length - prefix &&
    suffix < right.length - prefix &&
    left[left.length - suffix - 1] === right[right.length - suffix - 1]
  )
    suffix += 1;
  return {
    before: left.slice(0, prefix).join(""),
    original: left.slice(prefix, left.length - suffix).join(""),
    corrected: right.slice(prefix, right.length - suffix).join(""),
    after: suffix ? left.slice(left.length - suffix).join("") : "",
  };
}

export function TranscriptCorrectionPreview({
  corrected,
  original,
  correctedTitle = "Corrected",
}: {
  corrected?: string;
  original?: string;
  correctedTitle?: string;
}) {
  const change =
    original !== undefined && corrected !== undefined
      ? visibleTranscriptChange(original, corrected)
      : undefined;
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border bg-[var(--surface-transcript)] lg:grid lg:grid-cols-2 lg:divide-x">
      <PreviewColumn empty="No transcript selected." title="Original">
        {change ? (
          <>
            {change.before}
            {change.original ? (
              <del
                className="rounded bg-destructive/15 text-foreground"
                title="Removed text"
              >
                {change.original}
              </del>
            ) : null}
            {change.after}
          </>
        ) : (
          original
        )}
      </PreviewColumn>
      <PreviewColumn
        empty="Run correction to create a source-bound revision."
        title={correctedTitle}
      >
        {change ? (
          <>
            {change.before}
            {change.corrected ? (
              <ins
                className="rounded bg-accent text-accent-foreground underline decoration-2 underline-offset-4"
                title="Added text"
              >
                {change.corrected}
              </ins>
            ) : null}
            {change.after}
          </>
        ) : (
          corrected
        )}
      </PreviewColumn>
    </div>
  );
}

function PreviewColumn({
  children,
  empty,
  title,
}: {
  children?: React.ReactNode;
  empty: string;
  title: string;
}) {
  return (
    <div className="min-w-0">
      <div className="border-b p-3">
        <p className="text-xs font-semibold text-muted-foreground">{title}</p>
      </div>
      <ScrollArea className="max-h-[260px] lg:h-[260px] [&>[data-slot=scroll-area-viewport]]:max-h-[260px]">
        <div className="p-4">
          {children ? (
            <pre className="whitespace-pre-wrap break-words font-sans text-[15px] leading-7 text-foreground">
              {children}
            </pre>
          ) : (
            <p className="text-sm leading-6 text-muted-foreground">{empty}</p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
