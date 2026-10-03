import { CloudCheck } from "@phosphor-icons/react/CloudCheck";
import { CloudSlash } from "@phosphor-icons/react/CloudSlash";
import { SignIn } from "@phosphor-icons/react/SignIn";
import { WarningCircle } from "@phosphor-icons/react/WarningCircle";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ServerConnectionState } from "@/lib/setup-model";

export type ServerRoute = "unavailable" | "server" | "sign-in" | "blocked" | "checking";

// Server availability never changes an imported recording's route.
export function serverRoute(state: ServerConnectionState): ServerRoute {
  switch (state) {
    case "ready":
      return "server";
    case "sign_in_required":
      return "sign-in";
    case "access_denied":
      return "blocked";
    case "connecting":
    case "retrying":
      return "checking";
    case "not_set":
    case "offline":
    case "disabled":
      return "unavailable";
  }
}

export function serverRouteLabel(route: ServerRoute): string {
  switch (route) {
    case "server":
      return "Org server";
    case "sign-in":
      return "Server sign-in";
    case "blocked":
      return "Server access denied";
    case "checking":
      return "Connecting";
    case "unavailable":
      return "Server unavailable";
  }
}

export function serverRouteAnnouncement(route: ServerRoute): string {
  switch (route) {
    case "server":
      return "Connected to the org server.";
    case "sign-in":
      return "On-device dictation does not require the organization server. Sign in to use server features.";
    case "blocked":
      return "Organization server access is denied. On-device setup remains independent of server access.";
    case "checking":
      return "Connecting to the org server.";
    case "unavailable":
      return "Server unavailable. On-device dictation remains independent; imported recordings keep their organization-server route.";
  }
}

export function ServerRouteStatus({
  onSignIn,
  state,
}: {
  onSignIn?: () => void;
  state: ServerConnectionState;
}) {
  const route = serverRoute(state);
  const label = state === "offline" ? "Server offline"
    : state === "disabled" ? "Server disabled"
      : state === "not_set" ? "Server not configured" : serverRouteLabel(route);

  return (
    <>
      <div aria-atomic="true" aria-live="polite" className="sr-only" data-testid="server-route-announcement">
        {serverRouteAnnouncement(route)}
      </div>
      {route === "sign-in" ? (
        <Button
          className="rounded-full px-3 font-semibold"
          data-testid="server-route-status"
          onClick={onSignIn}
          size="sm"
          type="button"
          variant="default"
        >
          <SignIn data-icon="inline-start" />
          {label}
        </Button>
      ) : (
        <Badge
          className={
            route === "unavailable"
              ? "rounded-full border-primary/20 bg-[var(--primary-soft)] px-3 py-1.5 text-sm font-semibold text-primary"
              : "rounded-full px-3 py-1.5 text-sm font-semibold"
          }
          data-testid="server-route-status"
          variant={route === "blocked" ? "destructive" : route === "unavailable" ? "outline" : "secondary"}
        >
          {route === "checking" ? (
            <Skeleton className="h-4 w-20 rounded-full" />
          ) : (
            <>
              {route === "server" ? <CloudCheck data-icon="inline-start" /> : null}
              {route === "unavailable" ? <CloudSlash data-icon="inline-start" /> : null}
              {route === "blocked" ? <WarningCircle data-icon="inline-start" /> : null}
              {label}
            </>
          )}
        </Badge>
      )}
    </>
  );
}
