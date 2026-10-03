import { ArrowsLeftRight } from "@phosphor-icons/react/ArrowsLeftRight";
import { Repeat } from "@phosphor-icons/react/Repeat";
import { useState } from "react";

import { CuratorProposalResult } from "@/components/curator/curator-proposal-result";
import { useCuratorProposal } from "@/components/curator/use-curator-proposal";
import { SourceCitation } from "@/components/knowledge/source-citation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { RequestCancelButton } from "@/components/ui/request-cancel-button";
import { Spinner } from "@/components/ui/spinner";
import type { LibrarianEvidencePack } from "@/librarian";

const selectClass =
  "h-10 w-full min-w-0 rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-60";

export function ConnectionProposalComposer({
  available,
  authorityRevision,
  pack,
  queryRequestId,
  onInspect,
}: {
  available: boolean;
  authorityRevision: string;
  pack: LibrarianEvidencePack;
  queryRequestId: string;
  onInspect?: (reference: string) => void;
}) {
  const eligible = pack.items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.charEnd - item.charStart <= 1_024);
  const [sourceIndex, setSourceIndex] = useState(eligible[0]?.index ?? -1);
  const [targetIndex, setTargetIndex] = useState(
    eligible.find(({ item }) => item.conceptId !== eligible[0]?.item.conceptId)
      ?.index ?? -1,
  );
  const [relationshipType, setRelationshipType] = useState("references");
  const source = pack.items[sourceIndex];
  const target = pack.items[targetIndex];
  const pairValid = Boolean(
    source && target && source.conceptId !== target.conceptId,
  );
  const typeValid = /^[!-~]{1,128}$/.test(relationshipType);
  const curator = useCuratorProposal({
    available,
    authorityRevision,
    source: {
      kind: "connection",
      intent: { queryRequestId, sourceIndex, targetIndex, relationshipType },
    },
  });
  const hasPair = eligible.some(
    ({ item }) => item.conceptId !== eligible[0]?.item.conceptId,
  );

  if (!hasPair)
    return (
      <p className="rounded-xl border border-dashed border-border p-4 text-sm leading-6 text-muted-foreground">
        To propose a connection, search for two different reviewed sources with
        excerpts of at most 1,024 characters each.
      </p>
    );

  return (
    <Card className="min-w-0 border-primary/20 bg-[var(--surface-transcript)] py-0 shadow-none">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">Propose a connection</CardTitle>
        <p className="text-sm leading-6 text-muted-foreground">
          Link what the sources support. Every suggestion needs review before it
          appears in Connections.
        </p>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4 p-4 pt-2">
        {!available ? (
          <Alert>
            <AlertDescription>
              Connection review needs your connected organization server with
              Curator enabled.
            </AlertDescription>
          </Alert>
        ) : null}
        <form
          className="grid min-w-0 gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (pairValid && typeValid) void curator.run();
          }}
        >
          <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-end">
            <div className="grid min-w-0 gap-2">
              <label
                className="text-sm font-medium"
                htmlFor="connection-source"
              >
                From source
              </label>
              <select
                className={selectClass}
                disabled={curator.active}
                id="connection-source"
                value={sourceIndex}
                onChange={(event) => setSourceIndex(Number(event.target.value))}
              >
                {eligible.map(({ item, index }) => (
                  <option key={index} value={index}>
                    Source {index + 1} · {item.conceptId}
                  </option>
                ))}
              </select>
            </div>
            <Button
              aria-label="Reverse connection direction"
              className="w-fit"
              disabled={curator.active}
              onClick={() => {
                setSourceIndex(targetIndex);
                setTargetIndex(sourceIndex);
              }}
              type="button"
              variant="outline"
            >
              <ArrowsLeftRight aria-hidden="true" />
            </Button>
            <div className="grid min-w-0 gap-2">
              <label
                className="text-sm font-medium"
                htmlFor="connection-target"
              >
                To source
              </label>
              <select
                className={selectClass}
                disabled={curator.active}
                id="connection-target"
                value={targetIndex}
                onChange={(event) => setTargetIndex(Number(event.target.value))}
              >
                {eligible.map(({ item, index }) => (
                  <option
                    disabled={item.conceptId === source?.conceptId}
                    key={index}
                    value={index}
                  >
                    Source {index + 1} · {item.conceptId}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {!pairValid ? (
            <p role="status" className="text-sm text-muted-foreground">
              Choose two different sources.
            </p>
          ) : null}
          <div className="grid gap-2">
            <label className="text-sm font-medium" htmlFor="connection-type">
              Relationship type
            </label>
            <Input
              aria-describedby="connection-type-help"
              aria-invalid={!typeValid}
              autoComplete="off"
              disabled={curator.active}
              id="connection-type"
              list="connection-types"
              maxLength={128}
              onChange={(event) => setRelationshipType(event.target.value)}
              value={relationshipType}
            />
            <datalist id="connection-types">
              {["references", "supports", "depends_on", "contradicts"].map(
                (type) => (
                  <option key={type} value={type} />
                ),
              )}
            </datalist>
            <p
              className="text-xs leading-5 text-muted-foreground"
              id="connection-type-help"
            >
              Use a short type with no spaces, such as references or depends_on.
            </p>
          </div>
          {source && target ? (
            <details className="min-w-0 rounded-lg border border-border bg-card p-3">
              <summary className="w-fit cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                Check both cited excerpts
              </summary>
              <div className="mt-3 grid min-w-0 gap-4">
                <SourceCitation citation={source} index={sourceIndex} />
                <SourceCitation citation={target} index={targetIndex} />
              </div>
            </details>
          ) : null}
          <label className="text-sm font-medium" htmlFor="connection-rationale">
            Why are these connected?
          </label>
          <textarea
            aria-describedby="connection-rationale-help"
            autoComplete="off"
            className="min-h-[112px] w-full resize-y rounded-lg border border-input bg-card px-4 py-3 text-base outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-60"
            disabled={curator.active}
            id="connection-rationale"
            maxLength={2_000}
            onChange={(event) => curator.setReviewedContent(event.target.value)}
            placeholder="Explain the direction and the connection using both excerpts."
            value={curator.reviewedContent}
          />
          <p
            className="text-xs leading-5 text-muted-foreground"
            id="connection-rationale-help"
          >
            Curator checks this exact suggestion against both sources. Shared
            words alone do not establish a relationship.
          </p>
          <div className="flex flex-wrap gap-2">
            {curator.active ? (
              <RequestCancelButton
                onCancel={curator.cancel}
                requestId={curator.view?.requestId}
              />
            ) : (
              <Button
                disabled={!curator.canRun || !pairValid || !typeValid}
                type="submit"
              >
                Review connection
              </Button>
            )}
            {!curator.active &&
            curator.view &&
            ["failed", "cancelled"].includes(curator.view.status) ? (
              <Button
                disabled={!curator.canRun || !pairValid || !typeValid}
                onClick={() => void curator.retry()}
                type="button"
                variant="secondary"
              >
                <Repeat data-icon="inline-start" />
                Retry connection
              </Button>
            ) : null}
          </div>
        </form>
        <div
          aria-live="polite"
          className="flex items-center gap-2 text-sm leading-6 text-muted-foreground"
        >
          {curator.active ? <Spinner aria-hidden="true" /> : null}
          <p>{curator.statusLine}</p>
        </div>
        {curator.error ? (
          <Alert variant="destructive">
            <AlertDescription>{curator.error}</AlertDescription>
          </Alert>
        ) : null}
        {curator.view?.status === "proposed" ? (
          <CuratorProposalResult view={curator.view} />
        ) : null}
        {onInspect &&
        curator.view?.status === "proposed" &&
        curator.view.proposalId &&
        /^[0-9a-f]{64}$/.test(curator.view.proposalId) ? (
          <Button
            className="w-fit"
            type="button"
            variant="outline"
            onClick={() => onInspect(curator.view!.proposalId!)}
          >
            Inspect saved connection
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
