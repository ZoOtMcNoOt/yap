import { MagnifyingGlass } from "@phosphor-icons/react/MagnifyingGlass";
import {
  useConnectionProposal,
  type ProposalHandoff,
} from "./use-connection-proposal";
import { SourceCitation } from "./source-citation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RequestCancelButton } from "@/components/ui/request-cancel-button";
import { Spinner } from "@/components/ui/spinner";
import type { ServerConnectionSnapshot } from "@/server";

export function ConnectionProposalPanel({
  snapshot,
  handoff,
  onSearchSources,
}: {
  snapshot: ServerConnectionSnapshot;
  handoff?: ProposalHandoff;
  onSearchSources: () => void;
}) {
  const proposal = useConnectionProposal(snapshot, handoff);
  const view = proposal.view;
  const source = view?.sources.find(
    (item) => item.node.conceptId === view.candidate.sourceConceptId,
  );
  const target = view?.sources.find(
    (item) => item.node.conceptId === view.candidate.targetConceptId,
  );
  return (
    <AlertDialog open={proposal.confirming} onOpenChange={proposal.setConfirming}>
      <section
        className="grid min-w-0 grid-cols-1 gap-4 rounded-xl border border-border bg-[var(--surface-transcript)] p-4"
        aria-labelledby="connection-review-title"
      >
        <div>
          <h3 className="text-lg font-semibold" id="connection-review-title">
            Inspect a saved connection
          </h3>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Open a proposal reference to read its exact sources. Inspection does
            not publish knowledge.
          </p>
        </div>
        {!proposal.available ? (
          <Alert>
            <AlertDescription>
              Saved connections need your organization server with knowledge
              browsing enabled. Your draft stays available while offline.
            </AlertDescription>
          </Alert>
        ) : null}
        <form
          className="grid min-w-0 grid-cols-1 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (proposal.canRead) void proposal.run();
          }}
        >
          <label
            className="text-sm font-medium"
            htmlFor="connection-proposal-reference"
          >
            Connection proposal reference
          </label>
          <Input
            id="connection-proposal-reference"
            autoComplete="off"
            spellCheck={false}
            maxLength={64}
            disabled={proposal.pending}
            value={proposal.reference}
            onChange={(event) => proposal.setReference(event.target.value)}
            placeholder="Paste the reference copied after Curator review"
          />
          <p className="text-xs leading-5 text-muted-foreground">
            A 64-character reference belonging to your current account.
          </p>
          <div className="flex flex-wrap gap-2">
            {proposal.pending && !proposal.discarding ? (
              <RequestCancelButton
                onCancel={proposal.cancel}
                requestId={proposal.requestId}
              />
            ) : !proposal.pending ? (
              <Button
                type="submit"
                className="max-w-full whitespace-normal"
                aria-label={
                  proposal.error
                    ? "Try again: Open connection proposal"
                    : "Open connection proposal"
                }
                disabled={!proposal.canRead}
              >
                <MagnifyingGlass data-icon="inline-start" />
                {proposal.error ? "Try again" : "Open connection proposal"}
              </Button>
            ) : null}
            {!proposal.disposition ? (
              <AlertDialogTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  className="max-w-full whitespace-normal"
                  disabled={!proposal.canDiscard}
                >
                  {proposal.discardUnconfirmed
                    ? "Try discard again…"
                    : "Discard proposal…"}
                </Button>
              </AlertDialogTrigger>
            ) : null}
            <Button
              className="max-w-full whitespace-normal"
              type="button"
              variant="outline"
              onClick={onSearchSources}
            >
              Search current sources
            </Button>
          </div>
        </form>
        {proposal.pending ? (
          <p
            className="flex items-center gap-2 text-sm text-muted-foreground"
            role="status"
          >
            <Spinner />
            {proposal.discarding
              ? "Discarding saved proposal…"
              : "Reading saved proposal…"}
          </p>
        ) : null}
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard this connection proposal?</AlertDialogTitle>
            <AlertDialogDescription>
              Remove this suggestion from your pending proposals. Its history and
              sources stay saved. Published knowledge stays unchanged. You can also
              discard an old proposal whose sources are no longer available.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep proposal</AlertDialogCancel>
            <AlertDialogAction
              disabled={!proposal.canDiscard}
              onClick={() => void proposal.discard()}
            >
              Discard proposal
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
        {proposal.disposition ? (
          <Alert role="status">
            <AlertDescription>
              Proposal discarded. Its history and sources remain saved; published
              knowledge is unchanged. Open another reference or search current sources.
            </AlertDescription>
          </Alert>
        ) : null}
        {proposal.error ? (
          <Alert variant="destructive">
            <AlertDescription>{proposal.error}</AlertDescription>
          </Alert>
        ) : null}
        {view && source && target ? (
          <article
            className="grid min-w-0 grid-cols-1 gap-4"
            aria-label="Saved connection proposal"
          >
            <Badge
              className="w-fit max-w-full whitespace-normal"
              variant="secondary"
            >
              Proposed · Requires human review
            </Badge>
            <div className="min-w-0">
              <h4 className="break-words text-lg font-semibold">
                {source.node.title} → {target.node.title}
              </h4>
              <p className="mt-1 break-words text-sm font-medium text-primary">
                {view.candidate.relationshipType}
              </p>
              <p className="mt-2 whitespace-pre-wrap break-words text-[15px] leading-7">
                {view.candidate.rationale}
              </p>
            </div>
            <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
              {[source, target].map((item, index) => (
                <div className="min-w-0" key={item.node.conceptId}>
                  <p className="mb-2 text-xs font-semibold text-muted-foreground">
                    {index ? "To source" : "From source"}
                  </p>
                  <SourceCitation
                    citation={{ ...item.citation, text: item.text }}
                    index={index}
                  >
                    <p className="break-all text-xs leading-5 text-muted-foreground">
                      {item.node.sourcePath}
                    </p>
                  </SourceCitation>
                </div>
              ))}
            </div>
            <p className="text-sm leading-6 text-muted-foreground">
              This suggestion remains outside the published graph. Human
              publication and rebuilding use a separate review process.
            </p>
          </article>
        ) : null}
      </section>
    </AlertDialog>
  );
}
