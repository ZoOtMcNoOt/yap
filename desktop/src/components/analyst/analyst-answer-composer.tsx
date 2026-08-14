import { Repeat } from "@phosphor-icons/react/Repeat";
import { Sparkle } from "@phosphor-icons/react/Sparkle";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { AnalystAnswerResult } from "@/components/analyst/analyst-answer-result";
import { useAnalystAnswer } from "@/components/analyst/use-analyst-answer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

export function AnalystAnswerComposer({ available }: { available: boolean }) {
  const analyst = useAnalystAnswer({ available });

  return (
    <Card className="border-primary/25 bg-[var(--surface-transcript)] py-0 shadow-none">
      <CardHeader className="p-4 pb-2">
        <Badge className="w-fit" variant={available ? "default" : "secondary"}>
          <Sparkle data-icon="inline-start" />
          Analyst
        </Badge>
        <CardTitle className="mt-2 text-lg">Ask for a cited answer</CardTitle>
        <CardDescription className="leading-5">
          Analyst answers only with exact text from current, permission-safe organization evidence.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-2">
        {!available ? (
          <Alert>
            <AlertDescription>
              Cited answers need your connected organization server with Analyst enabled.
              Knowledge search and local controls remain available.
            </AlertDescription>
          </Alert>
        ) : null}

        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void analyst.run();
          }}
        >
          <label className="text-sm font-medium" htmlFor="analyst-question">
            What do you want to know?
          </label>
          <textarea
            aria-describedby="analyst-question-help"
            autoComplete="off"
            className="min-h-[112px] w-full resize-y rounded-lg border border-input bg-card px-4 py-3 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={analyst.active}
            id="analyst-question"
            maxLength={1_024}
            onChange={(event) => analyst.setQuestion(event.target.value)}
            placeholder="Example: Why was the reviewed launch approved?"
            value={analyst.question}
          />
          <p className="text-xs leading-5 text-muted-foreground" id="analyst-question-help">
            Up to three exact supporting excerpts may be used. Hidden matches are never revealed.
          </p>
          <div className="flex flex-wrap gap-2">
            {analyst.active ? (
              <Button onClick={() => void analyst.cancel()} type="button" variant="secondary">
                <XCircle data-icon="inline-start" />
                Cancel
              </Button>
            ) : (
              <Button disabled={!analyst.canRun} type="submit">
                Ask Analyst
              </Button>
            )}
            {!analyst.active && analyst.view ? (
              <Button onClick={() => void analyst.retry()} type="button" variant="secondary">
                <Repeat data-icon="inline-start" />
                Retry
              </Button>
            ) : null}
          </div>
        </form>

        <div aria-live="polite" className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
          {analyst.active ? <Spinner aria-hidden="true" /> : null}
          <p>{analyst.statusLine}</p>
        </div>

        {analyst.error ? (
          <Alert variant="destructive">
            <AlertDescription>
              {analyst.error} Knowledge search and local controls are unchanged.
            </AlertDescription>
          </Alert>
        ) : null}

        {analyst.answer ? <AnalystAnswerResult answer={analyst.answer} /> : null}
      </CardContent>
    </Card>
  );
}
