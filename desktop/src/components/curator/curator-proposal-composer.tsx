import { Repeat } from "@phosphor-icons/react/Repeat";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { CuratorProposalResult } from "@/components/curator/curator-proposal-result";
import { useCuratorProposal } from "@/components/curator/use-curator-proposal";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { StudentQuestion } from "@/student";

export function CuratorProposalComposer({
  available,
  generationSha256,
  question,
}: {
  available: boolean;
  generationSha256: string;
  question: StudentQuestion;
}) {
  const curator = useCuratorProposal({ available, generationSha256, studentQuestion: question });

  return (
    <div className="grid gap-3 border-t border-border/60 pt-4">
      <div>
        <h3 className="text-sm font-semibold">Review your answer with Curator</h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          Curator can propose a source-cited knowledge item. It cannot activate or replace source knowledge.
        </p>
      </div>

      {!available ? (
        <Alert>
          <AlertDescription>
            Proposal review needs your connected organization server with Curator enabled.
            The learning prompt and local controls remain available.
          </AlertDescription>
        </Alert>
      ) : null}

      <form
        className="grid gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void curator.run();
        }}
      >
        <label className="text-sm font-medium" htmlFor="curator-reviewed-answer">
          Your reviewed answer
        </label>
        <textarea
          aria-describedby="curator-reviewed-answer-help"
          autoComplete="off"
          className="min-h-[112px] w-full resize-y rounded-lg border border-input bg-[var(--surface-transcript)] px-4 py-3 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={curator.active}
          id="curator-reviewed-answer"
          maxLength={2_048}
          onChange={(event) => curator.setReviewedContent(event.target.value)}
          placeholder="Answer only from the cited source, then review your wording."
          value={curator.reviewedContent}
        />
        <p className="text-xs leading-5 text-muted-foreground" id="curator-reviewed-answer-help">
          Submission creates a noncanonical proposal for later review. It does not update organizational knowledge.
        </p>
        <div className="flex flex-wrap gap-2">
          {curator.active ? (
            <Button onClick={() => void curator.cancel()} type="button" variant="secondary">
              <XCircle data-icon="inline-start" />
              Cancel
            </Button>
          ) : (
            <Button disabled={!curator.canRun} type="submit">
              Propose for review
            </Button>
          )}
          {!curator.active && curator.view ? (
            <Button onClick={() => void curator.retry()} type="button" variant="secondary">
              <Repeat data-icon="inline-start" />
              Retry
            </Button>
          ) : null}
        </div>
      </form>

      <div aria-live="polite" className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
        {curator.active ? <Spinner aria-hidden="true" /> : null}
        <p>{curator.statusLine}</p>
      </div>

      {curator.error ? (
        <Alert variant="destructive">
          <AlertDescription>
            {curator.error} The learning prompt and local controls are unchanged.
          </AlertDescription>
        </Alert>
      ) : null}

      {curator.view?.status === "proposed" ? (
        <CuratorProposalResult view={curator.view} />
      ) : null}
    </div>
  );
}
