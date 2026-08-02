import { SettingsRow } from "@/components/settings/settings-primitives";
import type { ServerSettingsDraftController } from "@/components/settings/use-server-settings-draft";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ServerSettingsRows({
  server,
}: {
  server: ServerSettingsDraftController;
}) {
  return (
    <>
      <SettingsRow
        detail={server.notice || "Optional organization connection. On-device dictation can be set up and used when this is empty, disabled, offline, or awaiting sign-in."}
        error={server.error}
        label="Organization server"
        liveStatus
        value={server.pending ? "Checking" : server.enabled ? "Enabled" : "Disabled"}
      >
        <div className="flex w-full max-w-[520px] flex-wrap justify-end gap-2">
          <Input
            aria-label="Server URL"
            className="min-w-[240px] flex-1"
            disabled={server.pending}
            onChange={(event) => server.setUrl(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void server.save();
            }}
            placeholder="https://server.example"
            value={server.url}
          />
          <Button
            aria-checked={server.enabled}
            disabled={server.pending}
            onClick={server.toggleEnabled}
            role="switch"
            type="button"
            variant={server.enabled ? "default" : "secondary"}
          >
            {server.enabled ? "Enabled" : "Disabled"}
          </Button>
          <Button
            disabled={server.pending}
            onClick={() => void server.save()}
            type="button"
            variant="secondary"
          >
            Save
          </Button>
          <Button
            disabled={server.pending || !server.enabled || !server.url.trim()}
            onClick={() => void server.testConnection()}
            type="button"
          >
            Test Connection
          </Button>
        </div>
      </SettingsRow>
      <SettingsRow
        detail="Optional. Enterprise SSO requires organization-provided Entra registration and an approved native sign-in provider; local dictation never requires these values."
        label="Organization sign-in"
        liveStatus
        value={server.identity.signedIn
          ? "Signed in"
          : server.identity.configured
            ? "Ready"
            : "Not configured"}
      >
        <div className="grid w-full max-w-[520px] gap-2">
          <Input
            aria-label="Microsoft Entra tenant ID"
            disabled={server.pending}
            onChange={(event) => server.setTenantId(event.currentTarget.value)}
            placeholder="Tenant ID"
            value={server.tenantId}
          />
          <Input
            aria-label="Microsoft Entra native client ID"
            disabled={server.pending}
            onChange={(event) => server.setClientId(event.currentTarget.value)}
            placeholder="Native client ID"
            value={server.clientId}
          />
          <Input
            aria-label="Yap API access scope"
            disabled={server.pending}
            onChange={(event) => server.setApiScope(event.currentTarget.value)}
            placeholder="api://…/access_as_user"
            value={server.apiScope}
          />
          <div className="flex justify-end gap-2">
            <Button
              disabled={
                server.pending || server.identity.signedIn ||
                !server.tenantId.trim() || !server.clientId.trim() || !server.apiScope.trim()
              }
              onClick={() => void server.signIn()}
              type="button"
            >
              Sign in
            </Button>
            <Button
              disabled={server.pending || !server.identity.signedIn}
              onClick={() => void server.signOut()}
              type="button"
              variant="secondary"
            >
              Sign out
            </Button>
          </div>
        </div>
      </SettingsRow>
    </>
  );
}
