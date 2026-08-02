import { Plugs } from "@phosphor-icons/react/Plugs";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { LocalServerOffer } from "@/server";

// Discovery found a yap-server answering on loopback while no server is
// configured. This only ever offers: Connect goes through the normal settings
// save, which shows the native origin-approval dialog before anything changes.
export function LocalServerOfferBanner({
  busy,
  error,
  offer,
  onConnect,
  onDismiss,
}: {
  busy: boolean;
  error: string | null;
  offer: LocalServerOffer | null;
  onConnect: () => void;
  onDismiss: () => void;
}) {
  if (!offer) return null;

  return (
    <Alert className="mt-4" data-testid="local-server-offer">
      <Plugs />
      <AlertDescription>
        <p>
          <span className="font-medium text-foreground">
            A Yap server is running on this computer.
          </span>{" "}
          Connect to route transcription through it{offer.authRequired ? "; it will ask you to sign in" : ""}.
          Nothing connects until you approve.
        </p>
        {error ? <p className="text-destructive">{error}</p> : null}
        <div className="mt-2 flex gap-2">
          <Button disabled={busy} onClick={onConnect} size="sm" type="button">
            Connect
          </Button>
          <Button disabled={busy} onClick={onDismiss} size="sm" type="button" variant="ghost">
            Not now
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
