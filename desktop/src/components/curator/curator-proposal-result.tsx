import { CheckCircle } from "@phosphor-icons/react/CheckCircle";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CuratorProposalJobView } from "@/curator";

export function CuratorProposalResult({ view }: { view: CuratorProposalJobView }) {
  if (view.status !== "proposed" || !view.proposalId) return null;

  return (
    <Card className="border-primary/20 bg-card py-0 shadow-none">
      <CardHeader className="gap-2 p-4 pb-2">
        <Badge className="w-fit" variant="secondary">
          <CheckCircle data-icon="inline-start" />
          Proposal created
        </Badge>
        <CardTitle className="text-lg leading-7">Requires review</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-1 text-sm leading-6 text-muted-foreground">
        <p>This source-cited proposal has not changed organizational knowledge. Use its reference in your organization's review process.</p>
        <Button
          className="w-fit"
          onClick={() => void navigator.clipboard.writeText(view.proposalId!).then(
            () => toast.success("Proposal reference copied"),
            () => toast.error("Could not copy the proposal reference"),
          )}
          type="button"
          variant="outline"
        >Copy proposal reference</Button>
      </CardContent>
    </Card>
  );
}
