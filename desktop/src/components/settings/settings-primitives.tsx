import { CaretDown } from "@phosphor-icons/react/CaretDown";
import type { ReactNode } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

// Progressive disclosure for a settings section: the rows a new user needs
// stay in view, everything expert-only collapses behind one Advanced toggle.
// defaultOpen exists so a lifecycle that needs attention (broken model,
// pending install) is never hidden behind a closed disclosure.
export function AdvancedSettings({
  children,
  defaultOpen = false,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <CollapsibleTrigger
        className="group flex w-full items-center gap-2 pt-5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        type="button"
      >
        <CaretDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
        Advanced
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2">{children}</CollapsibleContent>
    </Collapsible>
  );
}

export function SettingsGroup({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl bg-muted/35 p-4 shadow-[0_0_0_1px_rgba(0,0,0,0.04)] sm:p-6">
      {children}
    </div>
  );
}

export function SettingsRow({
  action,
  children,
  detail,
  error,
  errorId,
  label,
  liveStatus = false,
  value,
}: {
  action?: ReactNode;
  children?: ReactNode;
  detail?: string;
  error?: string;
  errorId?: string;
  label: string;
  liveStatus?: boolean;
  value: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 border-b py-5 first:pt-0 last:border-b-0 last:pb-0 md:grid-cols-[minmax(0,1fr)_minmax(260px,360px)]">
      <div className="min-w-0 text-pretty">
        <div className="font-medium">{label}</div>
        <div
          aria-atomic={liveStatus || undefined}
          aria-live={liveStatus ? "polite" : undefined}
          role={liveStatus ? "status" : undefined}
        >
          <div className="mt-1 break-words text-sm text-foreground/80">{value}</div>
          {detail
            ? <div className="mt-1 break-words text-xs text-muted-foreground">{detail}</div>
            : null}
        </div>
        {error ? (
          <div
            aria-atomic="true"
            aria-live="polite"
            className="mt-1 break-words text-xs text-destructive"
            id={errorId}
            role="alert"
          >
            {error}
          </div>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-start gap-2 md:justify-end">
        {children}
        {action}
      </div>
    </div>
  );
}
