import { LockKey as LockKeyhole } from "@phosphor-icons/react/LockKey";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";

export function LocalSetupStatus({ auth, status }: { auth: string; status: string }) {
  const ready = auth === "Ready";
  const label = ready ? "Local ready" : status === "Preview" ? "Preview"
    : auth === "Checking" ? "Checking setup" : auth;
  const checking = auth === "Checking" || status === "Starting";

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button className="rounded-full px-3 font-semibold" size="sm" type="button" variant="secondary">
          <LockKeyhole data-icon="inline-start" />
          {checking ? <Skeleton className="h-4 w-14 rounded-full" /> : label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end">
        <PopoverHeader>
          <PopoverTitle>{checking ? "Checking setup" : label}</PopoverTitle>
          <PopoverDescription>
            {ready ? "On-device dictation is ready. Imported recordings use your organization server." : status}
          </PopoverDescription>
        </PopoverHeader>
      </PopoverContent>
    </Popover>
  );
}
