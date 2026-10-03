import { SealCheck as BadgeCheck } from "@phosphor-icons/react/SealCheck";
import { FolderSimple as FolderOutput } from "@phosphor-icons/react/FolderSimple";
import { LockKey as LockKeyhole } from "@phosphor-icons/react/LockKey";
import { HardDrives as Server } from "@phosphor-icons/react/HardDrives";

import { StatusRow } from "@/components/app/status-row";
import { SettingsGroup } from "@/components/settings/settings-primitives";

export function AboutSettingsSection({
  auth,
  serverLabel,
  status,
}: {
  auth: string;
  serverLabel: string;
  status: string;
}) {
  return (
    <SettingsGroup>
      <StatusRow icon={BadgeCheck} label="Status" value={status} />
      <StatusRow icon={Server} label="Server" value={serverLabel} />
      <StatusRow icon={LockKeyhole} label="Local setup" value={auth} />
      <StatusRow icon={FolderOutput} label="Output" value="Local Yap storage · use Reveal to find a transcript" />
    </SettingsGroup>
  );
}
