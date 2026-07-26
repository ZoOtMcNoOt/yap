import { useEffect, useState } from "react";

import {
  projectServerConnectionTestMessage,
  saveServerSettings,
  serverIdentityStatus,
  serverSettings,
  signInToServer,
  signOutOfServer,
  testServerConnection,
  type ServerIdentityStatus,
  type ServerSettings,
} from "@/settings";

export type ServerSettingsDraftController = {
  apiScope: string;
  clientId: string;
  enabled: boolean;
  error: string;
  identity: ServerIdentityStatus;
  notice: string;
  pending: boolean;
  save: () => Promise<ServerSettings | null>;
  setApiScope: (scope: string) => void;
  setClientId: (clientId: string) => void;
  setTenantId: (tenantId: string) => void;
  setUrl: (url: string) => void;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  tenantId: string;
  testConnection: () => Promise<void>;
  toggleEnabled: () => void;
  url: string;
};

function terseSettingsError(error: unknown, fallback: string) {
  const message = typeof error === "string"
    ? error
    : error instanceof Error
      ? error.message
      : "";
  return message.trim().split(/\r?\n/, 1)[0]?.slice(0, 160) || fallback;
}

export function useServerSettingsDraft(open: boolean): ServerSettingsDraftController {
  const [url, setUrl] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [apiScope, setApiScope] = useState("");
  const [identity, setIdentity] = useState<ServerIdentityStatus>({
    configured: false,
    signedIn: false,
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!open) return;
    let active = true;
    setPending(true);
    setError("");
    setNotice("");
    void Promise.all([serverSettings(), serverIdentityStatus()])
      .then(([settings, identityStatus]) => {
        if (!active) return;
        setUrl(settings.baseUrl ?? "");
        setEnabled(settings.enabled);
        setTenantId(settings.authentication?.tenantId ?? "");
        setClientId(settings.authentication?.clientId ?? "");
        setApiScope(settings.authentication?.apiScope ?? "");
        setIdentity(identityStatus);
      })
      .catch((loadError: unknown) => {
        if (active) setError(terseSettingsError(loadError, "Could not load server settings."));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  async function save() {
    setPending(true);
    setError("");
    setNotice("");
    try {
      const hasAuthenticationInput = [tenantId, clientId, apiScope]
        .some((value) => value.trim().length > 0);
      const saved = await saveServerSettings({
        schemaVersion: 2,
        enabled,
        baseUrl: url.trim() || null,
        authentication: hasAuthenticationInput
          ? {
            tenantId: tenantId.trim(),
            clientId: clientId.trim(),
            apiScope: apiScope.trim(),
          }
          : null,
      });
      setUrl(saved.baseUrl ?? "");
      setEnabled(saved.enabled);
      setTenantId(saved.authentication?.tenantId ?? "");
      setClientId(saved.authentication?.clientId ?? "");
      setApiScope(saved.authentication?.apiScope ?? "");
      setIdentity((current) => ({
        configured: saved.authentication !== null,
        signedIn: saved.authentication === null ? false : current.signedIn,
      }));
      setNotice("Saved.");
      return saved;
    } catch (saveError) {
      setError(terseSettingsError(saveError, "Could not save server settings."));
      return null;
    } finally {
      setPending(false);
    }
  }

  async function testConnection() {
    const saved = await save();
    if (!saved || !saved.enabled) return;
    setPending(true);
    setNotice("Checking connection.");
    try {
      setNotice(projectServerConnectionTestMessage(await testServerConnection()));
    } catch (connectionError) {
      setError(terseSettingsError(connectionError, "Connection check failed."));
      setNotice("");
    } finally {
      setPending(false);
    }
  }

  async function signIn() {
    const saved = await save();
    if (!saved?.authentication) return;
    setPending(true);
    setError("");
    setNotice("Opening Microsoft sign-in.");
    try {
      const status = await signInToServer();
      setIdentity(status);
      setNotice(status.signedIn ? "Signed in." : "Sign-in did not complete.");
    } catch (signInError) {
      setError(terseSettingsError(signInError, "Could not sign in."));
      setNotice("");
    } finally {
      setPending(false);
    }
  }

  async function signOut() {
    setPending(true);
    setError("");
    setNotice("");
    try {
      const status = await signOutOfServer();
      setIdentity(status);
      setNotice("Signed out.");
    } catch (signOutError) {
      setError(terseSettingsError(signOutError, "Could not sign out."));
    } finally {
      setPending(false);
    }
  }

  return {
    apiScope,
    clientId,
    enabled,
    error,
    identity,
    notice,
    pending,
    save,
    setApiScope,
    setClientId,
    setTenantId,
    setUrl,
    signIn,
    signOut,
    tenantId,
    testConnection,
    toggleEnabled: () => setEnabled((current) => !current),
    url,
  };
}
