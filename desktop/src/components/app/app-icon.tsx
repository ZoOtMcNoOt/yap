import { cn } from "@/lib/utils";

export function AppIcon({ className }: { className?: string }) {
  return (
    <img
      alt=""
      className={cn("shrink-0", className)}
      draggable={false}
      src="/yap-mark.svg"
    />
  );
}
