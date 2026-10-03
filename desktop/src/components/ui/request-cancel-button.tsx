import { XCircle } from "@phosphor-icons/react/XCircle";

import { Button } from "@/components/ui/button";

export function RequestCancelButton({
  onCancel,
  requestId,
}: {
  onCancel: () => Promise<void>;
  requestId?: string;
}) {
  return (
    <Button
      disabled={!requestId}
      onClick={(event) => {
        // A fast acknowledgement can replace this button with a form submit.
        event.preventDefault();
        void onCancel();
      }}
      title={!requestId ? "Waiting for the server to accept this request." : undefined}
      type="button"
      variant="secondary"
    >
      <XCircle data-icon="inline-start" />
      Cancel
    </Button>
  );
}
