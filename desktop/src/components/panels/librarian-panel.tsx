import { ConnectionProposalComposer } from "@/components/curator/connection-proposal-composer";
import { ConnectionsPanel } from "@/components/knowledge/connections-panel";
import { ConnectionProposalPanel } from "@/components/knowledge/connection-proposal-panel";
import { RebuildPanel } from "@/components/knowledge/rebuild-panel";
import type { ProposalHandoff } from "@/components/knowledge/use-connection-proposal";
import type { ServerConnectionSnapshot } from "@/server";
import { Books } from "@phosphor-icons/react/Books";
import { MagnifyingGlass } from "@phosphor-icons/react/MagnifyingGlass";
import { Repeat } from "@phosphor-icons/react/Repeat";
import { Tabs } from "radix-ui";
import { useEffect, useState } from "react";

import { AnalystAnswerComposer } from "@/components/analyst/analyst-answer-composer";
import { CoordinatorBundleComposer } from "@/components/coordinator/coordinator-bundle-composer";
import { AuditorReportComposer } from "@/components/auditor/auditor-report-composer";
import { LibrarianEvidenceResults } from "@/components/librarian/librarian-evidence-results";
import { useLibrarianQuery } from "@/components/librarian/use-librarian-query";
import { StudentQuestionComposer } from "@/components/student/student-question-composer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RequestCancelButton } from "@/components/ui/request-cancel-button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import type { LibrarianEvidenceItem } from "@/librarian";

export function LibrarianPanel({
  analystAvailable = false,
  available,
  coordinatorAvailable = false,
  auditorAvailable = false,
  curatorAvailable = false,
  studentAvailable = false,
  onOpenSettings,
  serverSnapshot,
}: {
  analystAvailable?: boolean;
  available: boolean;
  coordinatorAvailable?: boolean;
  auditorAvailable?: boolean;
  curatorAvailable?: boolean;
  studentAvailable?: boolean;
  onOpenSettings?: () => void;
  serverSnapshot: ServerConnectionSnapshot;
}) {
  const query = useLibrarianQuery({
    available,
    authorityRevision: serverSnapshot.authorityRevision,
  });
  const [task, setTask] = useState("search");
  const detailedTask = task === "connections" || task === "rebuild";
  const [proposalHandoff, setProposalHandoff] = useState<ProposalHandoff>();
  const connectionsAvailable =
    serverSnapshot.state === "ready" &&
    serverSnapshot.capabilities.knowledgeConnections;
  useEffect(
    () => setProposalHandoff(undefined),
    [serverSnapshot.authorityRevision],
  );
  const taskAvailable =
    task === "rebuild"
      ? serverSnapshot.state === "ready" &&
        serverSnapshot.capabilities.knowledgeRebuild
      : task === "connections"
        ? serverSnapshot.state === "ready" &&
          serverSnapshot.capabilities.knowledgeConnections
        : task === "search"
          ? available
          : task === "ask"
            ? analystAvailable
            : task === "proposals"
              ? coordinatorAvailable || connectionsAvailable
              : auditorAvailable;
  const [studentSource, setStudentSource] = useState<LibrarianEvidenceItem>();

  useEffect(() => {
    if (!studentSource) return;
    const remainsCurrent = query.evidence?.items.some(
      (item) =>
        item.conceptId === studentSource.conceptId &&
        item.sourceRevision === studentSource.sourceRevision &&
        item.contentSha256 === studentSource.contentSha256 &&
        item.charStart === studentSource.charStart &&
        item.charEnd === studentSource.charEnd,
    );
    if (!remainsCurrent) setStudentSource(undefined);
  }, [query.evidence, studentSource]);

  return (
    <Card className="surface-workspace-inset min-w-0 bg-card gap-0 py-0">
      {!detailedTask ? (
        <CardHeader className="p-4 sm:p-5">
          <Badge
            className="w-fit"
            variant={available ? "default" : "secondary"}
          >
            <Books data-icon="inline-start" />
            Organization knowledge
          </Badge>
          <CardTitle className="mt-3 text-2xl">
            Ask or find reviewed knowledge
          </CardTitle>
          <CardDescription className="max-w-3xl leading-6">
            Search sources, ask with citations, or review changes.
          </CardDescription>
        </CardHeader>
      ) : null}
      <CardContent
        className={`px-4 pb-4 sm:px-5 sm:pb-5 ${detailedTask ? "pt-4 sm:pt-5" : ""}`}
      >
        <Tabs.Root className="grid gap-5" onValueChange={setTask} value={task}>
          <Tabs.List
            aria-label="Knowledge tasks"
            className="flex w-full min-w-0 max-w-full gap-1 overflow-x-auto rounded-xl border border-border bg-muted p-1"
          >
            {(
              [
                ["search", "Search sources"],
                ["ask", "Ask a question"],
                ["proposals", "Review proposals"],
                ["conflicts", "Review conflicts"],
                ["connections", "Connections"],
                ["rebuild", "Rebuild"],
              ] as const
            ).map(([value, label]) => (
              <Tabs.Trigger
                className="knowledge-task shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:bg-card data-[state=active]:text-primary data-[state=active]:shadow-sm"
                key={value}
                value={value}
              >
                {label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          {!taskAvailable && onOpenSettings ? (
            <Button
              className="w-fit"
              onClick={onOpenSettings}
              type="button"
              variant="outline"
            >
              Check server settings
            </Button>
          ) : null}
          <Tabs.Content
            className="data-[state=inactive]:hidden"
            forceMount
            value="connections"
          >
            <ConnectionsPanel
              active={task === "connections"}
              snapshot={serverSnapshot}
              onReviewProposals={
                coordinatorAvailable || connectionsAvailable
                  ? () => setTask("proposals")
                  : undefined
              }
            />
          </Tabs.Content>
          <Tabs.Content
            className="data-[state=inactive]:hidden"
            forceMount
            value="rebuild"
          >
            <RebuildPanel snapshot={serverSnapshot} />
          </Tabs.Content>
          {/* Keep pending work and drafts mounted when another task is selected. */}
          <Tabs.Content
            className="data-[state=inactive]:hidden"
            forceMount
            value="ask"
          >
            <AnalystAnswerComposer
              available={analystAvailable}
              authorityRevision={serverSnapshot.authorityRevision}
            />
          </Tabs.Content>
          <Tabs.Content
            className="grid gap-5 data-[state=inactive]:hidden"
            forceMount
            value="proposals"
          >
            <ConnectionProposalPanel
              snapshot={serverSnapshot}
              handoff={proposalHandoff}
              onSearchSources={() => setTask("search")}
            />
            <CoordinatorBundleComposer
              available={coordinatorAvailable}
              authorityRevision={serverSnapshot.authorityRevision}
            />
          </Tabs.Content>
          <Tabs.Content
            className="data-[state=inactive]:hidden"
            forceMount
            value="conflicts"
          >
            <AuditorReportComposer
              available={auditorAvailable}
              authorityRevision={serverSnapshot.authorityRevision}
            />
          </Tabs.Content>
          <Tabs.Content
            className="grid gap-5 data-[state=inactive]:hidden"
            forceMount
            value="search"
          >
            {!available ? (
              <Alert>
                <AlertDescription>
                  Knowledge search is unavailable on the current server
                  connection. Local recording, playback, and saved transcripts
                  remain available.
                </AlertDescription>
              </Alert>
            ) : null}

            <div className="border-t border-border/60 pt-5">
              <h3 className="text-base font-semibold">
                Search reviewed sources
              </h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Results contain source text and citations to information you can
                access.
              </p>
            </div>

            <form
              className="grid gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                void query.run();
              }}
            >
              <label
                className="text-sm font-medium"
                htmlFor="librarian-search-text"
              >
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
              <p
                className="text-xs leading-5 text-muted-foreground"
                id="librarian-search-help"
              >
                Up to three current, permission-safe excerpts are returned for
                each query.
              </p>
              <div className="flex flex-wrap gap-2">
                {query.active ? (
                  <RequestCancelButton
                    onCancel={query.cancel}
                    requestId={query.view?.requestId}
                  />
                ) : (
                  <Button disabled={!query.canRun} type="submit">
                    <MagnifyingGlass data-icon="inline-start" />
                    Search knowledge
                  </Button>
                )}
                {!query.active && query.view ? (
                  <Button
                    onClick={() => void query.retry()}
                    type="button"
                    variant="secondary"
                  >
                    <Repeat data-icon="inline-start" />
                    Retry
                  </Button>
                ) : null}
              </div>
            </form>

            <div
              aria-live="polite"
              className="flex items-center gap-2 text-sm leading-6 text-muted-foreground"
            >
              {query.active ? <Spinner aria-hidden="true" /> : null}
              <p>{query.statusLine}</p>
            </div>

            {query.error ? (
              <Alert variant="destructive">
                <AlertDescription>
                  {query.error} Local controls are unchanged.
                </AlertDescription>
              </Alert>
            ) : null}

            {query.evidence ? (
              <LibrarianEvidenceResults
                onCreateLearningPrompt={setStudentSource}
                pack={query.evidence}
                studentAvailable={studentAvailable}
              />
            ) : null}

            {query.evidence && query.view?.status === "complete" ? (
              <ConnectionProposalComposer
                onInspect={
                  connectionsAvailable
                    ? (reference) => {
                        setProposalHandoff({
                          reference,
                          authorityRevision: serverSnapshot.authorityRevision,
                          nonce: Date.now(),
                        });
                        setTask("proposals");
                      }
                    : undefined
                }
                available={curatorAvailable}
                authorityRevision={serverSnapshot.authorityRevision}
                pack={query.evidence}
                queryRequestId={query.view.requestId}
                key={`${serverSnapshot.authorityRevision}:${query.view.requestId}:${query.evidence.evidenceSha256}`}
              />
            ) : null}

            {query.evidence && studentSource ? (
              <StudentQuestionComposer
                available={studentAvailable}
                curatorAvailable={curatorAvailable}
                authorityRevision={serverSnapshot.authorityRevision}
                generationSha256={query.evidence.generationSha256}
                item={studentSource}
                key={`${query.evidence.evidenceSha256}:${studentSource.conceptId}`}
                onClose={() => setStudentSource(undefined)}
              />
            ) : null}
          </Tabs.Content>
        </Tabs.Root>
      </CardContent>
    </Card>
  );
}
