import { CheckCircle } from "@phosphor-icons/react/CheckCircle";

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
      <CardContent className="p-4 pt-1 text-sm leading-6 text-muted-foreground">
        This source-cited proposal is noncanonical and has not changed organizational knowledge.
      </CardContent>
    </Card>
  );
}
