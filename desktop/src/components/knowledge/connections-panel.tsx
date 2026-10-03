import { ArrowRight } from "@phosphor-icons/react/ArrowRight";
import { ArrowUUpLeft } from "@phosphor-icons/react/ArrowUUpLeft";
import { Graph } from "@phosphor-icons/react/Graph";
import { ListBullets } from "@phosphor-icons/react/ListBullets";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import type { KnowledgeNeighborhood } from "@/knowledge-connections";
import type { ServerConnectionSnapshot } from "@/server";
import { useKnowledgeConnections } from "./use-knowledge-connections";

const authorityLabels = {
  asserted: "Source assertion",
  human_confirmed: "Confirmed by a person",
  derived: "Derived from source",
};
function readable(value: string) {
  return value.replace(/[_-]/g, " ");
}

function TopicGraph({
  graph,
  select,
  selected,
}: {
  graph: KnowledgeNeighborhood;
  select: (id: string) => void;
  selected: string | null;
}) {
  const root = graph.nodes.find((node) => node.conceptId === graph.conceptId)!;
  const neighbors = graph.nodes.filter(
    (node) => node.conceptId !== graph.conceptId,
  );
  const height = Math.max(224, neighbors.length * 72 + 24);
  return (
    <div
      className="relative grid min-w-0 grid-cols-2 gap-8 rounded-xl border bg-background p-3"
      style={{ minHeight: height }}
      data-testid="knowledge-topic-graph"
    >
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full"
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
      >
        {graph.relationships.map((edge) => {
          const peer =
            edge.sourceConceptId === root.conceptId
              ? edge.targetConceptId
              : edge.sourceConceptId;
          const index = neighbors.findIndex((node) => node.conceptId === peer);
          if (index < 0) return null;
          const endY = 12 + ((height - 24) * (index + 0.5)) / neighbors.length;
          return (
            <g
              key={edge.relationshipId}
              className={
                selected === edge.relationshipId ? "text-primary" : "text-input"
              }
            >
              <path
                d={`M 47 ${height / 2} C 51 ${height / 2}, 49 ${endY}, 53 ${endY}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
              />
              <path
                fill="currentColor"
                d={
                  edge.sourceConceptId === root.conceptId
                    ? `M 53 ${endY} L 51.6 ${endY - 3.5} L 51.6 ${endY + 3.5} Z`
                    : `M 47 ${height / 2} L 48.4 ${height / 2 - 3.5} L 48.4 ${height / 2 + 3.5} Z`
                }
              />
            </g>
          );
        })}
      </svg>
      <div className="z-10 flex min-w-0 items-center">
        <div className="w-full min-w-0 rounded-lg border border-primary bg-card p-3 shadow-sm">
          <Graph className="mb-2 size-5 text-primary" aria-hidden="true" />
          <p className="line-clamp-3 break-words text-sm font-semibold">
            {root.title}
          </p>
          <p className="mt-1 break-words text-xs text-muted-foreground">
            {readable(root.type)} · Current topic
          </p>
        </div>
      </div>
      <div className="z-10 grid min-w-0 content-around gap-2">
        {neighbors.map((node) => {
          const edges = graph.relationships.filter(
            (edge) =>
              edge.sourceConceptId === node.conceptId ||
              edge.targetConceptId === node.conceptId,
          );
          const chosen = edges.some((edge) => selected === edge.relationshipId);
          return (
            <button
              type="button"
              key={node.conceptId}
              aria-label={`Inspect connections with ${node.title}`}
              aria-pressed={chosen}
              onClick={() => select(edges[0].relationshipId)}
              className="h-16 min-w-0 overflow-hidden rounded-lg border bg-card px-3 py-2 text-left shadow-xs outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-pressed:border-primary aria-pressed:bg-accent"
            >
              <span className="line-clamp-2 break-words text-sm font-medium leading-4">
                {node.title}
              </span>
              <span className="block text-xs leading-4 text-muted-foreground">
                {edges.length}{" "}
                {edges.length === 1 ? "connection" : "connections"}
              </span>
            </button>
          );
        })}
        {!neighbors.length ? (
          <p className="text-sm text-muted-foreground">
            No neighboring topics in this view.
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function ConnectionsPanel({
  active,
  snapshot,
  onReviewProposals,
}: {
  active: boolean;
  snapshot: ServerConnectionSnapshot;
  onReviewProposals?: () => void;
}) {
  const control = useKnowledgeConnections(active, snapshot);
  const [view, setView] = useState<"graph" | "list">("graph");
  const [copyNotice, setCopyNotice] = useState("");
  const detailsHeading = useRef<HTMLHeadingElement>(null);
  const graph = control.graph;
  const root = graph?.nodes.find((node) => node.conceptId === graph.conceptId);
  const selected = control.selected;
  const source = graph?.nodes.find(
    (node) => node.conceptId === selected?.sourceConceptId,
  );
  const target = graph?.nodes.find(
    (node) => node.conceptId === selected?.targetConceptId,
  );
  const peer =
    selected && graph
      ? graph.nodes.find(
          (node) =>
            node.conceptId ===
            (selected.sourceConceptId === graph.conceptId
              ? selected.targetConceptId
              : selected.sourceConceptId),
        )
      : null;
  const disabled =
    !control.available || control.pending || control.checkingAuthority;
  const resultsVisible = control.available && !control.checkingAuthority;
  function select(id: string) {
    control.setSelectedEdge(id);
    setCopyNotice("");
    // Move focus to the inspected source without requiring pointer scrolling.
    requestAnimationFrame(() => detailsHeading.current?.focus());
  }
  async function copyCitation() {
    if (!selected || !source || !target) return;
    const citation = selected.citation;
    try {
      await navigator.clipboard.writeText(
        `${source.title} → ${target.title}: ${readable(selected.type)} (${authorityLabels[selected.authority]})\n${citation.sourcePath}\nRevision: ${citation.sourceRevision}\nSHA-256: ${citation.contentSha256}${citation.charStart === null ? "" : `\nCharacters: ${citation.charStart}–${citation.charEnd}`}`,
      );
      setCopyNotice("Source citation copied.");
    } catch {
      setCopyNotice(
        "Citation could not be copied. You can select the source details below.",
      );
    }
  }
  return (
    <section className="grid min-w-0 gap-5" aria-label="Knowledge connections">
      <div>
        <h3 className="text-xl font-semibold tracking-tight">
          Follow an idea.
        </h3>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
          See how reviewed topics connect, and the source behind every link.
        </p>
      </div>
      {!control.available ? (
        <p
          role="status"
          className="rounded-lg border bg-background p-4 text-sm"
        >
          Connections are unavailable on this server. Local recording and saved
          transcripts are still available.
        </p>
      ) : null}
      <form
        className="flex min-w-0 flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void control.browse();
        }}
      >
        <div className="grid min-w-0 flex-1 basis-48 gap-2">
          <label
            className="text-sm font-medium"
            htmlFor="connections-topic-search"
          >
            Find a topic
          </label>
          <Input
            id="connections-topic-search"
            value={control.search}
            maxLength={128}
            placeholder="A project, decision, or conversation…"
            disabled={disabled || !control.topics}
            onChange={(event) => control.setSearch(event.target.value)}
          />
        </div>
        {control.topics ? (
          <Button disabled={disabled} type="submit">
            Find topics
          </Button>
        ) : (
          <Button
            disabled={disabled}
            type="button"
            onClick={(event) => {
              // The response can replace this control with a form submit before
              // the click default runs. Admit exactly one native read.
              event.preventDefault();
              void control.browse(true);
            }}
          >
            Browse topics
          </Button>
        )}
        {control.topics ? (
          <Button
            disabled={disabled}
            type="button"
            variant="outline"
            onClick={(event) => {
              // The response can replace this control with a form submit before
              // the click default runs. Admit exactly one native read.
              event.preventDefault();
              void control.browse(true);
            }}
          >
            Refresh topics
          </Button>
        ) : null}
      </form>
      {control.pending ? (
        <div role="status" className="flex items-center gap-3 text-sm">
          <Spinner className="size-4" /> Loading connections…
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void control.cancel()}
          >
            Cancel exploration
          </Button>
        </div>
      ) : null}
      {control.checkingAuthority ? (
        <p role="status" className="text-sm text-muted-foreground">
          Checking your connection…
        </p>
      ) : null}
      {control.error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm"
        >
          <p className="min-w-0 flex-1 basis-48">{control.error}</p>
          <Button
            type="button"
            disabled={disabled}
            variant="outline"
            size="sm"
            onClick={() => void control.retry()}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {resultsVisible && control.topics && !graph && !control.pending ? (
        <div className="grid gap-3">
          <h4 className="text-sm font-semibold">Reviewed topics</h4>
          {control.topics.nodes.length ? (
            <ul className="grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {control.topics.nodes.map((node) => (
                <li key={node.conceptId} className="min-w-0">
                  <button
                    type="button"
                    className="flex h-full w-full min-w-0 items-center justify-between gap-3 rounded-xl border bg-background p-4 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                    disabled={disabled}
                    onClick={() => void control.explore(node, [])}
                  >
                    <span className="min-w-0">
                      <span className="block break-words text-sm font-semibold">
                        {node.title}
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {readable(node.type)}
                      </span>
                    </span>
                    <ArrowRight
                      className="size-4 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p
              role="status"
              className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground"
            >
              No reviewed topics are available for this search. Try another
              title or check your organization’s knowledge access.
            </p>
          )}
          {control.topics.hasMore ? (
            <p className="text-xs text-muted-foreground">
              Showing 12 topics you can access. Refine your search to find
              others.
            </p>
          ) : null}
        </div>
      ) : null}
      {resultsVisible && graph && root ? (
        <div className="grid min-w-0 gap-4">
          <nav
            aria-label="Exploration path"
            className="flex min-w-0 flex-wrap items-center gap-1 text-sm"
          >
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled}
              onClick={(event) => {
              // The response can replace this control with a form submit before
              // the click default runs. Admit exactly one native read.
              event.preventDefault();
              void control.browse(true);
            }}
            >
              <ArrowUUpLeft /> Topics
            </Button>
            {control.trail.map((node, index) => (
              <span
                key={`${node.conceptId}-${index}`}
                className="flex min-w-0 items-center gap-1"
              >
                <span aria-hidden="true" className="text-muted-foreground">
                  /
                </span>
                <button
                  type="button"
                  className="max-w-full break-words rounded px-2 py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  disabled={disabled}
                  aria-current={
                    index === control.trail.length - 1 ? "page" : undefined
                  }
                  onClick={() => void control.back(index)}
                >
                  {node.title}
                </button>
              </span>
            ))}
          </nav>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="min-w-0 break-words text-lg font-semibold">
              {root.title}
            </h4>
            <div
              role="group"
              aria-label="Connection view"
              className="flex rounded-lg border bg-muted p-1"
            >
              <Button
                type="button"
                size="sm"
                variant={view === "graph" ? "secondary" : "ghost"}
                aria-pressed={view === "graph"}
                onClick={() => setView("graph")}
              >
                <Graph />
                Graph
              </Button>
              <Button
                type="button"
                size="sm"
                variant={view === "list" ? "secondary" : "ghost"}
                aria-pressed={view === "list"}
                onClick={() => setView("list")}
              >
                <ListBullets />
                List
              </Button>
            </div>
          </div>
          {graph.hasMore ? (
            <p className="text-sm text-muted-foreground">
              Showing 16 reviewed connections. Explore a neighboring topic for
              its own connections.
            </p>
          ) : null}
          {!graph.relationships.length ? (
            <p
              role="status"
              className="rounded-lg border border-dashed p-5 text-sm"
            >
              This reviewed topic has no connections in your current view.
            </p>
          ) : null}
          <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.8fr)]">
            <div className="grid min-w-0 gap-2">
              {view === "graph" ? (
                <>
                  <TopicGraph
                    graph={graph}
                    select={select}
                    selected={selected?.relationshipId ?? null}
                  />
                  <p className="text-xs leading-5 text-muted-foreground">
                    Arrows follow the source relationship. Select a topic to
                    inspect its links; List shows every relationship.
                  </p>
                </>
              ) : (
                <ul
                  aria-label="Reviewed connections"
                  className="grid min-w-0 gap-2"
                >
                  {graph.relationships.map((edge) => {
                    const from = graph.nodes.find(
                      (node) => node.conceptId === edge.sourceConceptId,
                    )!;
                    const to = graph.nodes.find(
                      (node) => node.conceptId === edge.targetConceptId,
                    )!;
                    return (
                      <li className="min-w-0" key={edge.relationshipId}>
                        <button
                          type="button"
                          aria-pressed={
                            selected?.relationshipId === edge.relationshipId
                          }
                          className="w-full min-w-0 rounded-xl border bg-background p-4 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-pressed:border-primary aria-pressed:bg-accent"
                          onClick={() => select(edge.relationshipId)}
                        >
                          <span className="block break-words text-sm font-semibold">
                            {from.title} → {to.title}
                          </span>
                          <span className="mt-1 block break-words text-sm">
                            {readable(edge.type)}
                          </span>
                          <span className="mt-2 block text-xs text-muted-foreground">
                            {authorityLabels[edge.authority]}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <aside
              className="grid min-w-0 gap-3 rounded-xl border bg-background p-4 lg:sticky lg:top-4"
              aria-label="Connection source details"
            >
              <h5
                ref={detailsHeading}
                tabIndex={-1}
                className="rounded text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {selected ? "Why these topics connect" : "Inspect a connection"}
              </h5>
              {selected && source && target ? (
                <>
                  <p className="break-words text-sm leading-6">
                    <strong>{source.title}</strong> {readable(selected.type)}{" "}
                    <strong>{target.title}</strong>.
                  </p>
                  <Badge
                    variant="secondary"
                    className="w-fit whitespace-normal"
                  >
                    {authorityLabels[selected.authority]}
                  </Badge>
                  <p className="break-words text-sm text-muted-foreground">
                    {selected.citation.charStart === null
                      ? "Declared in reviewed source metadata."
                      : `Linked in source text, characters ${selected.citation.charStart}–${selected.citation.charEnd}.`}
                  </p>
                  <p className="break-all text-sm font-medium">
                    {selected.citation.sourcePath}
                  </p>
                  <details className="min-w-0 text-xs text-muted-foreground">
                    <summary className="cursor-pointer rounded py-1 focus-visible:ring-2 focus-visible:ring-ring">
                      Source revision and fingerprint
                    </summary>
                    <dl className="mt-2 grid gap-2">
                      <dt>Revision</dt>
                      <dd className="break-all">
                        {selected.citation.sourceRevision}
                      </dd>
                      <dt>SHA-256</dt>
                      <dd className="break-all">
                        {selected.citation.contentSha256}
                      </dd>
                    </dl>
                  </details>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => void copyCitation()}
                    >
                      Copy source citation
                    </Button>
                    {peer && peer.conceptId !== graph.conceptId ? (
                      <Button
                        type="button"
                        size="sm"
                        className="h-auto min-h-8 max-w-full whitespace-normal text-left"
                        disabled={disabled}
                        onClick={() => void control.explore(peer)}
                      >
                        Explore {peer.title}
                        <ArrowRight />
                      </Button>
                    ) : null}
                  </div>
                  {copyNotice ? (
                    <p role="status" className="text-xs">
                      {copyNotice}
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="text-sm leading-6 text-muted-foreground">
                  Choose a neighboring topic or a relationship in List to see
                  its evidence and continue exploring.
                </p>
              )}
            </aside>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            Only reviewed relationships are shown here. Connection suggestions require
            human review before publication.
          </p>
          {onReviewProposals ? (
            <Button
              className="w-fit"
              type="button"
              variant="outline"
              size="sm"
              onClick={onReviewProposals}
            >
              Review proposed changes
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
