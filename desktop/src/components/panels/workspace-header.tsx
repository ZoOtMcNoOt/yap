import { PrivacyStatus } from "@/components/app/privacy-status";
import { ServerRouteStatus } from "@/components/app/server-route-status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ServerConnectionState } from "@/lib/setup-model";

export function WorkspaceHeader({
  auth,
  description,
  historyCount,
  onOpenDetails,
  onOpenHelp,
  serverState,
  status,
  title,
}: {
  auth: string;
  description: string;
  historyCount: number;
  onOpenDetails: () => void;
  onOpenHelp: () => void;
  serverState: ServerConnectionState;
  status: string;
  title: string;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="mt-1.5 max-w-xl text-sm leading-6 text-muted-foreground">{description}</p>
        ) : null}
      </div>

      {/*
        No settings gear here. The sidebar already carries one, permanently, and
        two identical gears opening the same surface is the kind of duplication
        that reads as two different things. `onOpenDetails` stays because
        ServerRouteStatus uses it for sign-in -- that is a contextual jump to fix
        a specific blocked state, not a second front door.
      */}
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <ServerRouteStatus onSignIn={onOpenDetails} state={serverState} />
        <PrivacyStatus auth={auth} status={status} />
        {historyCount ? (
          <Badge className="rounded-full px-3 py-1.5 text-sm font-semibold tabular-nums" variant="secondary">
            {historyCount} saved
          </Badge>
        ) : null}
        <Button
          className="h-auto px-1 text-muted-foreground"
          onClick={onOpenHelp}
          size="sm"
          type="button"
          variant="link"
        >
          Help
        </Button>
      </div>
    </header>
  );
}
