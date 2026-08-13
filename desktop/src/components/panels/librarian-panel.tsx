import { Books } from "@phosphor-icons/react/Books";
import { MagnifyingGlass } from "@phosphor-icons/react/MagnifyingGlass";
import { Repeat } from "@phosphor-icons/react/Repeat";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { LibrarianEvidenceResults } from "@/components/librarian/librarian-evidence-results";
import { useLibrarianQuery } from "@/components/librarian/use-librarian-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

export function LibrarianPanel({ available }: { available: boolean }) {
  const query = useLibrarianQuery({ available });
  return (
    <Card className="surface-workspace-inset min-w-0 bg-card py-0">
      <CardHeader className="p-4 sm:p-5">
        <Badge className="w-fit" variant={available ? "default" : "secondary"}>
          <Books data-icon="inline-start" />
          Organization knowledge
        </Badge>
        <CardTitle className="mt-3 text-2xl">Find reviewed evidence</CardTitle>
        <CardDescription className="max-w-3xl leading-6">
          Search only the knowledge your organization currently authorizes. Yap returns source
          excerpts, not a generated answer, and does not reveal whether hidden matches exist.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5 p-4 sm:p-5">
        {!available ? (
          <Alert>
            <AlertDescription>
              Knowledge search needs your connected organization server with Librarian enabled.
              Local recording, playback, transcripts, export, and deletion remain available.
            </AlertDescription>
          </Alert>
        ) : null}

        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void query.run();
          }}
        >
          <label className="text-sm font-medium" htmlFor="librarian-search-text">
            What reviewed information are you looking for?
          </label>
          <textarea
            aria-describedby="librarian-search-help"
            autoComplete="off"
            className="min-h-[112px] w-full resize-y rounded-lg border border-input bg-[var(--surface-transcript)] px-4 py-3 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={query.active}
            id="librarian-search-text"
            maxLength={1_024}
            onChange={(event) => query.setSearchText(event.target.value)}
            placeholder="Example: What did the reviewed launch record say about approval?"
            value={query.searchText}
          />
          <p className="text-xs leading-5 text-muted-foreground" id="librarian-search-help">
            Up to three current, permission-safe excerpts are returned for each query.
          </p>
          <div className="flex flex-wrap gap-2">
            {query.active ? (
              <Button onClick={() => void query.cancel()} type="button" variant="secondary">
                <XCircle data-icon="inline-start" />
                Cancel
              </Button>
            ) : (
              <Button disabled={!query.canRun} type="submit">
                <MagnifyingGlass data-icon="inline-start" />
                Search knowledge
              </Button>
            )}
            {!query.active && query.view ? (
              <Button onClick={() => void query.retry()} type="button" variant="secondary">
                <Repeat data-icon="inline-start" />
                Retry
              </Button>
            ) : null}
          </div>
        </form>

        <div aria-live="polite" className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
          {query.active ? <Spinner aria-hidden="true" /> : null}
          <p>{query.statusLine}</p>
        </div>

        {query.error ? (
          <Alert variant="destructive">
            <AlertDescription>{query.error} Local controls are unchanged.</AlertDescription>
          </Alert>
        ) : null}

        {query.evidence ? <LibrarianEvidenceResults pack={query.evidence} /> : null}
      </CardContent>
    </Card>
  );
}
