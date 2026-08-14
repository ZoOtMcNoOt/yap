import { Repeat } from "@phosphor-icons/react/Repeat";
import { ShieldWarning } from "@phosphor-icons/react/ShieldWarning";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { AuditorReportResult } from "@/components/auditor/auditor-report-result";
import { useAuditorReport } from "@/components/auditor/use-auditor-report";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

export function AuditorReportComposer({ available }: { available: boolean }) {
  const auditor = useAuditorReport({ available });
  return (
    <Card className="border-primary/25 bg-[var(--surface-transcript)] py-0 shadow-none">
      <CardHeader className="p-4 pb-2">
        <Badge className="w-fit" variant={available ? "default" : "secondary"}>
          <ShieldWarning data-icon="inline-start" />
          Auditor
        </Badge>
        <CardTitle className="mt-2 text-lg">Review current knowledge for conflicts</CardTitle>
        <CardDescription className="leading-5">
          Auditor identifies potential contradictions in current permission-safe knowledge and preserves both exact source citations for human review.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-2">
        {!available ? (
          <Alert><AlertDescription>
            Audit reports need your connected organization server with Auditor enabled. Knowledge search and local controls remain available.
          </AlertDescription></Alert>
        ) : null}
        <form className="grid gap-2" onSubmit={(event) => { event.preventDefault(); void auditor.run(); }}>
          <label className="text-sm font-medium" htmlFor="auditor-focus">What should Auditor review?</label>
          <textarea
            aria-describedby="auditor-focus-help"
            autoComplete="off"
            className="min-h-[112px] w-full resize-y rounded-lg border border-input bg-card px-4 py-3 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={auditor.active}
            id="auditor-focus"
            maxLength={1_024}
            onChange={(event) => auditor.setFocus(event.target.value)}
            placeholder="Example: Helios release limit"
            value={auditor.focus}
          />
          <p className="text-xs leading-5 text-muted-foreground" id="auditor-focus-help">
            Up to three potential conflicts may be returned. Every finding is noncanonical and requires review.
          </p>
          <div className="flex flex-wrap gap-2">
            {auditor.active ? (
              <Button onClick={() => void auditor.cancel()} type="button" variant="secondary">
                <XCircle data-icon="inline-start" /> Cancel
              </Button>
            ) : (
              <Button disabled={!auditor.canRun} type="submit">Review knowledge</Button>
            )}
            {!auditor.active && auditor.view ? (
              <Button onClick={() => void auditor.retry()} type="button" variant="secondary">
                <Repeat data-icon="inline-start" /> Retry
              </Button>
            ) : null}
          </div>
        </form>
        <div aria-live="polite" className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
          {auditor.active ? <Spinner aria-hidden="true" /> : null}<p>{auditor.statusLine}</p>
        </div>
        {auditor.error ? (
          <Alert variant="destructive"><AlertDescription>
            {auditor.error} Knowledge search and local controls are unchanged.
          </AlertDescription></Alert>
        ) : null}
        {auditor.report ? <AuditorReportResult report={auditor.report} /> : null}
      </CardContent>
    </Card>
  );
}
