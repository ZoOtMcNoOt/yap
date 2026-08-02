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
// A tunnel or local server often comes up after the desktop. Retry one bounded
// loopback-only health probe at a time so discovery does not depend on launch
// order and can never turn into LAN scanning.
const DISCOVERY_RETRY_MS = 3_000;

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
    // This versioned key can only contain the one fixed origin this hook
    // offers. A durable decline is terminal until the user configures the
    // server manually (or a future discovery origin deliberately bumps it).
    if (localStorage.getItem(DISMISSED_KEY)) {
      setOffer(null);
      return;
    }
    let cancelled = false;
    let retryTimer: number | undefined;
    let probing = false;

    const scheduleRetry = () => {
      if (cancelled || retryTimer !== undefined) return;
      retryTimer = window.setTimeout(() => {
        retryTimer = undefined;
        void runProbe();
      }, DISCOVERY_RETRY_MS);
    };

    const runProbe = async () => {
      if (cancelled || probing) return;
      probing = true;
      try {
        // `disabled` alone is ambiguous: it can mean the untouched local-only
        // default or an intentionally retained but disabled server URL. Avoid
        // polling forever when an origin is already configured.
        const current = await serverSettings();
        if (cancelled) return;
        if (current.baseUrl) {
          cancelled = true;
          setOffer(null);
          return;
        }
        const found = await probeLocalServer();
        if (cancelled) return;
        if (!found) {
          scheduleRetry();
          return;
        }
        // A durable decline ends discovery for this fixed origin. The user can
        // still configure it manually in Advanced settings.
        if (localStorage.getItem(DISMISSED_KEY) === found.baseUrl) {
          cancelled = true;
          return;
        }
        // A verified offer is the terminal discovery result for this mount.
        // Do not keep polling behind a visible or subsequently dismissed offer.
        cancelled = true;
        setOffer(found);
      } catch {
        // Discovery is best-effort: an unreachable probe stays local and
        // retries later without surfacing an application error.
        scheduleRetry();
      } finally {
        probing = false;
      }
    };

    const retryNow = () => {
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer);
        retryTimer = undefined;
      }
      void runProbe();
    };

    void runProbe();
    window.addEventListener("focus", retryNow);
    window.addEventListener("online", retryNow);
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      window.removeEventListener("focus", retryNow);
      window.removeEventListener("online", retryNow);
    };
  }, [serverState, unconfigured]);

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
