import { SealCheck as BadgeCheck } from "@phosphor-icons/react/SealCheck";
import { Microphone as Mic } from "@phosphor-icons/react/Microphone";
import { HardDrives as Server } from "@phosphor-icons/react/HardDrives";
import type { ComponentType } from "react";

import { cn } from "@/lib/utils";

export type SettingsSection = "general" | "system" | "about";

const settingsSections: {
  id: SettingsSection;
  icon: ComponentType<{ className?: string }>;
  label: string;
}[] = [
  { id: "general", icon: Mic, label: "General" },
  { id: "system", icon: Server, label: "System" },
  { id: "about", icon: BadgeCheck, label: "About" },
];

export function settingsSectionTitle(section: SettingsSection) {
  if (section === "general") return "General";
  if (section === "system") return "System";
  return "About";
}

export function SettingsNavigation({
  onSelect,
  section,
}: {
  onSelect: (section: SettingsSection) => void;
  section: SettingsSection;
}) {
  return (
    <aside className="flex min-h-0 flex-col border-b bg-muted/45 p-3 md:border-r md:border-b-0 md:p-5">
      <div className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground md:mb-4">
        Settings
      </div>
      <nav className="grid grid-cols-3 gap-1 md:grid-cols-1">
        {settingsSections.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={cn(
                "flex h-11 items-center justify-center gap-1 rounded-lg px-2 text-left text-sm font-medium transition-[background-color,color,scale] duration-150 ease-out active:scale-[0.96] sm:gap-2 md:justify-start md:gap-3 md:px-3",
                section === item.id
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
              )}
              key={item.id}
              onClick={() => onSelect(item.id)}
              type="button"
            >
              <Icon className="size-5 shrink-0" />
              {item.label}
            </button>
          );
        })}
      </nav>
      <div className="mt-auto hidden text-xs text-muted-foreground md:block">Yap</div>
    </aside>
  );
}
