import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useEffect, useState } from "react";

import type { ServerConnectionState } from "@/lib/setup-model";
import {
  probeLocalServer,
  refreshServerConnection,
  saveServerSettings,
  serverSettings,
  type LocalServerOffer,
} from "@/server";

// Dismissal is per-origin and durable: declining an offer once must not turn
// into a nag on every launch. The settings sheet remains the way back in.
const DISMISSED_KEY = "yap.localServerOffer.dismissed.v1";

export function useLocalServerOffer({ serverState }: { serverState: ServerConnectionState }) {
  const [offer, setOffer] = useState<LocalServerOffer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The probe command itself refuses to offer while a base URL is configured;
  // these two states are just the cheap client-side gate that avoids probing
  // on every connection transition.
  const unconfigured = serverState === "not_set" || serverState === "disabled";

  useEffect(() => {
    if (!isTauri() || !unconfigured) {
      setOffer(null);
      return;
    }
    let cancelled = false;
    void probeLocalServer()
      .then((found) => {
        if (cancelled || !found) return;
        if (localStorage.getItem(DISMISSED_KEY) === found.baseUrl) return;
        setOffer(found);
      })
      .catch(() => {
        // Discovery is best-effort: an unreachable probe is simply no offer.
      });
    return () => {
      cancelled = true;
    };
  }, [unconfigured]);

  const connect = useCallback(async () => {
    if (!offer || busy) return;
    setBusy(true);
    setError(null);
    try {
      const current = await serverSettings();
      // save runs the native origin-approval dialog; declining it rejects and
      // leaves the offer standing, which is the honest outcome of "Cancel".
      await saveServerSettings({ ...current, baseUrl: offer.baseUrl, enabled: true });
      setOffer(null);
      await refreshServerConnection();
    } catch (saveError) {
      setError(String(saveError));
    } finally {
      setBusy(false);
    }
  }, [busy, offer]);

  const dismiss = useCallback(() => {
    if (offer) localStorage.setItem(DISMISSED_KEY, offer.baseUrl);
    setOffer(null);
  }, [offer]);

  return { busy, connect, dismiss, error, offer };
}
