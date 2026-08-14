import { Repeat } from "@phosphor-icons/react/Repeat";
import { XCircle } from "@phosphor-icons/react/XCircle";

import { CuratorProposalComposer } from "@/components/curator/curator-proposal-composer";
import { StudentQuestionResult } from "@/components/student/student-question-result";
import { useStudentQuestion } from "@/components/student/use-student-question";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { LibrarianEvidenceItem } from "@/librarian";

export function StudentQuestionComposer({
  available,
  curatorAvailable,
  generationSha256,
  item,
  onClose,
}: {
  available: boolean;
  curatorAvailable: boolean;
  generationSha256: string;
  item: LibrarianEvidenceItem;
  onClose: () => void;
}) {
  const student = useStudentQuestion({
    available,
    conversationConceptId: item.conceptId,
    generationSha256,
  });

  return (
    <Card className="border-primary/25 bg-[var(--surface-transcript)] py-0 shadow-none">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">Create a source-cited learning prompt</CardTitle>
        <CardDescription className="break-all leading-5">
          Student will use only the current reviewed meeting source: {item.conceptId}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-2">
        {!available ? (
          <Alert>
            <AlertDescription>
              Learning prompts need your connected organization server with Student enabled.
              Knowledge search and local controls remain available.
            </AlertDescription>
          </Alert>
        ) : null}

        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void student.run();
          }}
        >
          <label className="text-sm font-medium" htmlFor="student-learning-topic">
            What should the prompt help you remember?
          </label>
          <Input
            autoComplete="off"
            disabled={student.active}
            id="student-learning-topic"
            maxLength={128}
            onChange={(event) => student.setTopic(event.target.value)}
            placeholder="Example: crash containment"
            value={student.topic}
          />
          <p className="text-xs leading-5 text-muted-foreground">
            Student returns one question with exact support from this source. Do not include a question mark.
          </p>
          <div className="flex flex-wrap gap-2">
            {student.active ? (
              <Button onClick={() => void student.cancel()} type="button" variant="secondary">
                <XCircle data-icon="inline-start" />
                Cancel
              </Button>
            ) : (
              <Button disabled={!student.canRun} type="submit">
                Create prompt
              </Button>
            )}
            {!student.active && student.view ? (
              <Button onClick={() => void student.retry()} type="button" variant="secondary">
                <Repeat data-icon="inline-start" />
                Retry
              </Button>
            ) : null}
            <Button onClick={onClose} type="button" variant="ghost">
              Close
            </Button>
          </div>
        </form>

        <div aria-live="polite" className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
          {student.active ? <Spinner aria-hidden="true" /> : null}
          <p>{student.statusLine}</p>
        </div>

        {student.error ? (
          <Alert variant="destructive">
            <AlertDescription>{student.error} Knowledge search and local controls are unchanged.</AlertDescription>
          </Alert>
        ) : null}

        {student.view?.status === "complete" ? (
          <>
            <StudentQuestionResult view={student.view} />
            {student.view.questions[0] ? (
              <CuratorProposalComposer
                available={curatorAvailable}
                generationSha256={student.view.generationSha256}
                question={student.view.questions[0]}
              />
            ) : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
