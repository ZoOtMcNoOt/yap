import type { ReactNode } from "react";

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
