import { Repeat } from "@phosphor-icons/react/Repeat";
import { Sparkle } from "@phosphor-icons/react/Sparkle";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { CoordinatorBundleResult } from "@/components/coordinator/coordinator-bundle-result";
import { useCoordinatorBundle } from "@/components/coordinator/use-coordinator-bundle";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

export function CoordinatorBundleComposer({ available }: { available: boolean }) {
  const coordinator = useCoordinatorBundle({ available });

  return (
    <Card className="border-primary/25 bg-[var(--surface-transcript)] py-0 shadow-none">
      <CardHeader className="p-4 pb-2">
        <Badge className="w-fit" variant={available ? "default" : "secondary"}>
          <Sparkle data-icon="inline-start" />
          Coordinator
        </Badge>
        <CardTitle className="mt-2 text-lg">Build a reviewed proposal bundle</CardTitle>
        <CardDescription className="leading-5">
          Coordinator selects current, permission-safe Curator proposals and preserves their exact
          source citations for human review.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-2">
        {!available ? (
          <Alert>
            <AlertDescription>
              Proposal bundles need your connected organization server with Coordinator enabled.
              Knowledge search and local controls remain available.
            </AlertDescription>
          </Alert>
        ) : null}

        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void coordinator.run();
          }}
        >
          <label className="text-sm font-medium" htmlFor="coordinator-objective">
            What should the reviewed proposals help coordinate?
          </label>
          <textarea
            aria-describedby="coordinator-objective-help"
            autoComplete="off"
            className="min-h-[112px] w-full resize-y rounded-lg border border-input bg-card px-4 py-3 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={coordinator.active}
            id="coordinator-objective"
            maxLength={1_024}
            onChange={(event) => coordinator.setObjective(event.target.value)}
            placeholder="Example: Coordinate the reviewed launch-readiness proposals."
            value={coordinator.objective}
          />
          <p className="text-xs leading-5 text-muted-foreground" id="coordinator-objective-help">
            Up to three proposals may be selected. The result is noncanonical and always requires
            review.
          </p>
          <div className="flex flex-wrap gap-2">
            {coordinator.active ? (
              <Button onClick={() => void coordinator.cancel()} type="button" variant="secondary">
                <XCircle data-icon="inline-start" />
                Cancel
              </Button>
            ) : (
              <Button disabled={!coordinator.canRun} type="submit">
                Build proposal bundle
              </Button>
            )}
            {!coordinator.active && coordinator.view ? (
              <Button onClick={() => void coordinator.retry()} type="button" variant="secondary">
                <Repeat data-icon="inline-start" />
                Retry
              </Button>
            ) : null}
          </div>
        </form>

        <div aria-live="polite" className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
          {coordinator.active ? <Spinner aria-hidden="true" /> : null}
          <p>{coordinator.statusLine}</p>
        </div>

        {coordinator.error ? (
          <Alert variant="destructive">
            <AlertDescription>
              {coordinator.error} Knowledge search and local controls are unchanged.
            </AlertDescription>
          </Alert>
        ) : null}

        {coordinator.bundle ? <CoordinatorBundleResult bundle={coordinator.bundle} /> : null}
      </CardContent>
    </Card>
  );
}
