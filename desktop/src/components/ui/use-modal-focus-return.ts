import { useRef } from "react";

// Controlled workspace modals open from several actions, without a Radix Trigger.
export function useModalFocusReturn({
  onOpenAutoFocus,
  onCloseAutoFocus,
}: {
  onOpenAutoFocus?: (event: Event) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const opener = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus(event: Event) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      onOpenAutoFocus?.(event);
    },
    onCloseAutoFocus(event: Event) {
      onCloseAutoFocus?.(event);
      const target = opener.current;
      if (event.defaultPrevented || !target?.isConnected || !target.getClientRects().length) return;
      const otherModal = document.querySelector('[role="dialog"][data-state="open"]');
      if (otherModal && !otherModal.contains(target)) return;
      event.preventDefault();
      target.focus();
    },
  };
}
