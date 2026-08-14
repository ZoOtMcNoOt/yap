import { Question } from "@phosphor-icons/react/Question";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { StudentQuestionJobView } from "@/student";

export function StudentQuestionResult({ view }: { view: StudentQuestionJobView }) {
  const question = view.status === "complete" ? view.questions[0] : undefined;
  const support = question?.sourceSupports[0];
  if (!question || !support) return null;

  return (
    <Card className="border-primary/20 bg-card py-0 shadow-none">
      <CardHeader className="gap-2 p-4 pb-2">
        <Badge className="w-fit" variant="secondary">
          <Question data-icon="inline-start" />
          Learning prompt
        </Badge>
        <CardTitle className="text-lg leading-7">{question.question}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 p-4 pt-1">
        <blockquote className="whitespace-pre-wrap break-words border-l-2 border-primary/40 pl-3 text-sm leading-6">
          {support.supportQuote}
        </blockquote>
        <p className="break-all text-xs leading-5 text-muted-foreground">
          {support.sourceCitation.conceptId} · characters {support.supportCharStart}–{support.supportCharEnd}
        </p>
        {view.outputBudgetExhausted ? (
          <p className="text-xs leading-5 text-muted-foreground">
            The source budget was exhausted; this prompt remains bound to the citation shown.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
