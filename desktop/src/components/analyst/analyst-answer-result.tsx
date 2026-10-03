import { Quotes } from "@phosphor-icons/react/Quotes";

import { SourceCitation } from "@/components/knowledge/source-citation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalystAnswer } from "@/analyst";

export function AnalystAnswerResult({ answer }: { answer: AnalystAnswer }) {
  return (
    <Card className="border-primary/20 bg-card py-0 shadow-none">
      <CardHeader className="gap-2 p-4 pb-2">
        <Badge className="w-fit" variant="secondary">
          <Quotes data-icon="inline-start" />
          Cited answer
        </Badge>
        <CardTitle className="whitespace-pre-wrap text-lg leading-7">{answer.answer}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-1">
        <h4 className="text-sm font-semibold">Sources</h4>
        {answer.citations.map((citation, index) => (
          <SourceCitation
            citation={citation}
            index={index}
            key={`${citation.conceptId}:${citation.sourceRevision}:${citation.charStart}:${citation.charEnd}`}
          />
        ))}
      </CardContent>
    </Card>
  );
}
