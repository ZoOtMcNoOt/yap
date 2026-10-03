import { type ElementType } from "react";
import { UserCircle as CircleUserRound } from "@phosphor-icons/react/UserCircle";
import { SquaresFour as Grid2X2 } from "@phosphor-icons/react/SquaresFour";
import { Question as HelpCircle } from "@phosphor-icons/react/Question";
import { Microphone as Mic } from "@phosphor-icons/react/Microphone";
import { GearSix as Settings2 } from "@phosphor-icons/react/GearSix";
import { Sparkle as Sparkles } from "@phosphor-icons/react/Sparkle";
import { Books } from "@phosphor-icons/react/Books";

import { AppIcon } from "@/components/app/app-icon";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import type { RailAction } from "@/lib/workspace";

const mainNav: { action: RailAction; icon: ElementType; label: string }[] = [
  { action: "home", icon: Grid2X2, label: "Home" },
  { action: "transcribe", icon: Mic, label: "Transcribe" },
  { action: "correct", icon: Sparkles, label: "Correct" },
  { action: "knowledge", icon: Books, label: "Knowledge" },
];

const footerNav: { action: RailAction; icon: ElementType; label: string }[] = [
  { action: "details", icon: Settings2, label: "Settings" },
  { action: "help", icon: HelpCircle, label: "Help" },
];

export function AppSidebar({
  active,
  onAction,
}: {
  active: RailAction;
  onAction: (action: RailAction) => void;
}) {
  const { state } = useSidebar();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-0 px-3 pb-0 pt-4">
        <div className="flex flex-col">
          <div className="flex h-7 items-center gap-2 px-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
            <SidebarTrigger
              aria-label="Toggle sidebar"
              className="bg-secondary"
              size="icon-xs"
            />
            <Button
              aria-label="Account"
              className="text-muted-foreground group-data-[collapsible=icon]:hidden"
              onClick={() => onAction("details")}
              size="icon-xs"
              type="button"
              variant="ghost"
            >
              <CircleUserRound data-icon="inline-start" />
            </Button>
          </div>

          <div className="flex h-[3.75rem] items-center gap-2 overflow-hidden px-1">
            <div className="size-7 shrink-0">
              <AppIcon className="size-7" />
            </div>
            <span
              className="brand-wordmark min-w-0 truncate text-xl font-semibold tracking-tight"
              style={{
                opacity: state === "collapsed" ? 0 : 1,
                transform:
                  state === "collapsed" ? "translateX(-6px)" : "translateX(0)",
              }}
            >
              Yap
            </span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="px-2">
        <SidebarMenu>
          {mainNav.map(({ action, icon: Icon, label }) => (
            <SidebarMenuItem key={action}>
              <SidebarMenuButton
                isActive={active === action}
                onClick={() => onAction(action)}
                tooltip={label}
                type="button"
              >
                <Icon data-icon="inline-start" />
                <span>{label}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarContent>

      <SidebarFooter className="px-2 pb-3">
        <SidebarSeparator className="mb-2" />
        <SidebarMenu>
          {footerNav.map(({ action, icon: Icon, label }) => (
            <SidebarMenuItem key={action}>
              <SidebarMenuButton
                isActive={active === action}
                onClick={() => onAction(action)}
                tooltip={label}
                type="button"
              >
                <Icon data-icon="inline-start" />
                <span>{label}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
