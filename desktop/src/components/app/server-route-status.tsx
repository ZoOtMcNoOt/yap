import { CloudCheck } from "@phosphor-icons/react/CloudCheck";
import { CloudSlash } from "@phosphor-icons/react/CloudSlash";
import { SignIn } from "@phosphor-icons/react/SignIn";
import { WarningCircle } from "@phosphor-icons/react/WarningCircle";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ServerConnectionState } from "@/lib/setup-model";

export type ServerRoute = "local" | "server" | "sign-in" | "blocked" | "checking";

// Which route the next recording actually takes. The local label deliberately
// avoids the phrase "Private on this device": the Transcribe surface is about
// the organization server queue, and app.spec asserts that phrase never
// appears there, so a header badge carrying it would contradict the surface.
// Everything that is not a
// working server connection is the local route, because that is what the user
// gets, and saying so is more useful than naming the failure.
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
      return "local";
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
    case "local":
      return "On this device";
  }
}

// Spoken when the route changes. Autoconnect moves this without the user doing
// anything, so the change has to be announced rather than only drawn.
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
    case "local":
      return "Working privately on this device.";
  }
}

// Where the recording goes, kept in the header rather than behind the settings
// sheet. Connection state used to be reachable only by opening settings, which
// left "why is nothing uploading" as something the user had to go hunting for.
export function ServerRouteStatus({
  onSignIn,
  state,
}: {
  onSignIn?: () => void;
  state: ServerConnectionState;
}) {
  const route = serverRoute(state);
  const label = serverRouteLabel(route);

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
            // Working privately on this device is Yap's identity, so the local
            // route wears the brand tint rather than the neutral chip.
            route === "local"
              ? "rounded-full border-primary/20 bg-[var(--primary-soft)] px-3 py-1.5 text-sm font-semibold text-primary"
              : "rounded-full px-3 py-1.5 text-sm font-semibold"
          }
          data-testid="server-route-status"
          variant={route === "blocked" ? "destructive" : route === "local" ? "outline" : "secondary"}
        >
          {route === "checking" ? (
            <Skeleton className="h-4 w-20 rounded-full" />
          ) : (
            <>
              {route === "server" ? <CloudCheck data-icon="inline-start" /> : null}
              {route === "local" ? <CloudSlash data-icon="inline-start" /> : null}
              {route === "blocked" ? <WarningCircle data-icon="inline-start" /> : null}
              {label}
            </>
          )}
        </Badge>
      )}
    </>
  );
}
