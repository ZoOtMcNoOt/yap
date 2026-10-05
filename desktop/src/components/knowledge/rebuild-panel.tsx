import { useEffect, useRef, useState } from "react";
import type { ServerConnectionSnapshot } from "@/server";
import {
  knowledgeRebuild,
  sameGeneration,
  generationReference,
  rebuildError,
  type SourceReceipt,
  type GenerationReceipt,
  type EmbeddingReceipt,
  type ActivationReceipt,
  type ActivationRequest,
  type RebuildRequest,
} from "@/knowledge-rebuild";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";

export function RebuildPanel({
  snapshot,
}: {
  snapshot: ServerConnectionSnapshot;
}) {
  const [owner, setOwner] = useState(snapshot.authorityRevision);
  const revision = useRef(snapshot.authorityRevision);
  revision.current = snapshot.authorityRevision;
  const running = useRef(false);
  const [pending, setPending] = useState(false);
  const [source, setSource] = useState<SourceReceipt | null>(null);
  const [generation, setGeneration] = useState<GenerationReceipt | null>(null);
  const [prepared, setPrepared] = useState<EmbeddingReceipt | null>(null);
  const [activation, setActivation] = useState<ActivationReceipt | null>(null);
  const [saved, setSaved] = useState("");
  const [uncertain, setUncertain] = useState<RebuildRequest | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [decision, setDecision] = useState<ActivationRequest | null>(null);
  const [inspectingRestore, setInspectingRestore] = useState(false);
  const available =
    snapshot.state === "ready" && snapshot.capabilities.knowledgeRebuild;
  const owned = owner === snapshot.authorityRevision;
  const enabled = available && owned && !pending;
  useEffect(() => {
    if (owner === snapshot.authorityRevision) return;
    setOwner(snapshot.authorityRevision);
    setSource(null);
    setGeneration(null);
    setPrepared(null);
    setActivation(null);
    setSaved("");
    setUncertain(null);
    setDecision(null);
    setError("");
    setNotice("");
    setInspectingRestore(false);
  }, [owner, snapshot.authorityRevision]);
  async function run(request: RebuildRequest, restoring = false) {
    if (!enabled || running.current) return;
    const started = owner;
    running.current = true;
    setPending(true);
    setDecision(null);
    setError("");
    setNotice("");
    const mutates = request.action !== "source" && request.action !== "inspect";
    try {
      const response = await knowledgeRebuild(request, started);
      if (revision.current !== started) return;
      if (response.kind === "source" || response.kind === "staged") {
        const changed =
          !source ||
          !sameGeneration(source, response.value) ||
          source.activeGenerationSha256 !==
            response.value.activeGenerationSha256;
        if (changed || response.kind === "staged") {
          setGeneration(null);
          setPrepared(null);
          setInspectingRestore(false);
        }
        setSource(response.value);
        if (response.kind === "staged")
          setNotice(
            response.value.changed
              ? "Reviewed source staged. Prepare its embeddings next."
              : "Staging confirmed. Existing reviewed data is preserved.",
          );
        else setNotice("Reviewed source and current knowledge inspected.");
      } else if (response.kind === "prepared") {
        if (
          !source ||
          response.value.generationSha256 !== source.generationSha256 ||
          response.value.chunkCount !== source.chunkCount
        )
          throw { code: "invalidResponse", unconfirmed: true };
        setPrepared(response.value);
        setGeneration(null);
        setInspectingRestore(false);
        setNotice(
          response.value.changed
            ? "Embeddings prepared. Inspect the generation before publishing."
            : "Embedding preparation confirmed without regenerating completed vectors. Inspect before publishing.",
        );
      } else if (response.kind === "generation") {
        if (!restoring && (!source || !sameGeneration(source, response.value)))
          throw { code: "invalidResponse", unconfirmed: false };
        // Any inspection renews current active state and clears a pending decision.
        setGeneration(response.value);
        setInspectingRestore(restoring);
        if (source)
          setSource({
            ...source,
            activeGenerationSha256: response.value.activeGenerationSha256,
            status:
              source.generationSha256 === response.value.activeGenerationSha256
                ? "active"
                : source.status === "active"
                  ? "retained"
                  : source.status,
          });
        setNotice(
          restoring
            ? "Saved generation inspected. Review its current state before restoring."
            : "Generation inspected. The service performs the final completeness checks on publication.",
        );
      } else {
        if (
          generation &&
          generation.generationSha256 === response.value.generationSha256 &&
          !sameGeneration(generation, response.value)
        )
          throw { code: "invalidResponse", unconfirmed: true };
        setActivation(response.value);
        setGeneration(response.value);
        setInspectingRestore(false);
        setPrepared(null);
        setSource((current) =>
          current
            ? {
                ...current,
                activeGenerationSha256: response.value.generationSha256,
                status:
                  current.generationSha256 === response.value.generationSha256
                    ? "active"
                    : current.status === "active"
                      ? "retained"
                      : current.status,
              }
            : null,
        );
        if (
          response.value.previousActiveGenerationSha256 &&
          response.value.previousActiveGenerationSha256 !==
            response.value.generationSha256
        )
          setSaved(response.value.previousActiveGenerationSha256);
        setNotice(
          response.value.changed
            ? request.action === "restore"
              ? "Retained knowledge restored."
              : "Reviewed knowledge published."
            : "Activation confirmed. The generation is already current; history was preserved.",
        );
      }
      if (mutates) setUncertain(null);
    } catch (cause) {
      if (revision.current !== started) return;
      const failure = rebuildError(cause);
      setError(failure.message);
      if (failure.code === "denied" || failure.code === "identityChanged") {
        setSource(null);
        setGeneration(null);
        setPrepared(null);
        setActivation(null);
        setSaved("");
        setDecision(null);
        setUncertain(null);
        setNotice(
          mutates && failure.unconfirmed
            ? "Private inspection was cleared after access changed. The write may have committed. Inspect again after your organization restores access."
            : "Private inspection was cleared after access changed. Inspect again after your organization restores access.",
        );
      } else if (mutates && failure.unconfirmed) {
        setUncertain(request);
        setGeneration(null);
        setPrepared(null);
        setNotice(
          "The write outcome is unconfirmed. The server may have committed it. Inspect current state or explicitly confirm the same request; nothing is retried automatically.",
        );
      } else {
        setGeneration(null);
        setPrepared(null);
        setDecision(null);
      }
    } finally {
      running.current = false;
      setPending(false);
    }
  }
  const shownSource = owned ? source : null;
  const shownGeneration = owned ? generation : null;
  const canPublish =
    enabled &&
    !uncertain &&
    shownSource &&
    shownGeneration &&
    prepared &&
    !inspectingRestore &&
    sameGeneration(shownSource, shownGeneration) &&
    shownGeneration.status === "staged" &&
    prepared.generationSha256 === shownGeneration.generationSha256;
  const canRestore =
    enabled &&
    !uncertain &&
    shownGeneration &&
    inspectingRestore &&
    shownGeneration.status === "retained";
  function decide(action: "publish" | "restore") {
    if (!shownGeneration || !(action === "publish" ? canPublish : canRestore))
      return;
    setDecision({
      action,
      generationSha256: shownGeneration.generationSha256,
      expectedActiveGenerationSha256: shownGeneration.activeGenerationSha256,
    });
  }
  return (
    <section aria-labelledby="rebuild-title" className="grid min-w-0 gap-5">
      <div className="grid gap-2">
        <h2 id="rebuild-title" className="text-xl font-semibold">
          Rebuild reviewed knowledge
        </h2>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          Prepare deployment-reviewed source, then decide when it becomes
          current. Your organization owns source review and deployment approval.
          These controls preserve proposals and do not approve Git changes.
        </p>
      </div>
      {!available && (
        <Alert>
          <AlertDescription>
            Connect to an organization server with reviewed rebuilding
            configured. Your local capture and saved history remain available.
          </AlertDescription>
        </Alert>
      )}
      <div aria-live="polite" role="status" className="text-sm leading-6">
        {pending
          ? "Checking with your organization server…"
          : owned
            ? notice
            : "Your server or sign-in changed. Inspect again to continue."}
      </div>
      {owned && error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {owned && uncertain && (
        <Alert>
          <AlertDescription className="grid gap-3">
            <p>
              Unconfirmed request: {uncertain.action}. Inspect current state
              first, or explicitly confirm the original request. A dropped reply
              does not undo a server write.
            </p>
            {uncertain.action !== "source" && (
              <code className="break-all text-xs">
                {uncertain.generationSha256}
              </code>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={!enabled}
              onClick={() => void run(uncertain)}
            >
              Confirm previous request
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!enabled}
              onClick={() => {
                setUncertain(null);
                setGeneration(null);
                setPrepared(null);
                setNotice(
                  "Previous outcome remains unconfirmed. Inspect again before a new decision.",
                );
              }}
            >
              Start a new inspection
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Reviewed source</CardTitle>
            <CardDescription>
              Selected by your organization deployment.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Button
              type="button"
              variant="outline"
              disabled={!enabled}
              onClick={() => void run({ action: "source" })}
            >
              Inspect reviewed source
            </Button>
            {shownSource ? (
              <>
                <Badge className="w-fit" variant="secondary">
                  {shownSource.status}
                </Badge>
                <dl className="grid gap-2 text-sm">
                  <dt className="text-muted-foreground">Source</dt>
                  <dd className="break-all">{shownSource.sourcePath}</dd>
                  <dt className="text-muted-foreground">Reviewed revision</dt>
                  <dd className="break-all">{shownSource.sourceRevision}</dd>
                  <dt className="text-muted-foreground">
                    Generation reference
                  </dt>
                  <dd>
                    <code className="break-all text-xs">
                      {shownSource.generationSha256}
                    </code>
                  </dd>
                  <dt className="text-muted-foreground">Contents</dt>
                  <dd>
                    {shownSource.conceptCount} concepts ·{" "}
                    {shownSource.chunkCount} chunks ·{" "}
                    {shownSource.relationshipCount} relationships ·{" "}
                    {shownSource.permissionCount} permissions
                  </dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    disabled={
                      !enabled ||
                      !!uncertain ||
                      !["unadmitted", "staged"].includes(shownSource.status)
                    }
                    onClick={() =>
                      void run({
                        action: "stage",
                        generationSha256: shownSource.generationSha256,
                      })
                    }
                  >
                    Stage reviewed source
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={
                      !enabled || !!uncertain || shownSource.status !== "staged"
                    }
                    onClick={() =>
                      void run({
                        action: "embeddings",
                        generationSha256: shownSource.generationSha256,
                      })
                    }
                  >
                    Prepare embeddings
                  </Button>
                </div>
                {owned && prepared && (
                  <p className="break-words text-sm">
                    Prepared with {prepared.embeddingModelId}. Deployment-pinned
                    model revision:{" "}
                    <code className="break-all text-xs">
                      {prepared.embeddingModelRevision}
                    </code>
                    . This does not certify model quality.
                  </p>
                )}
                <Button
                  type="button"
                  variant="outline"
                  disabled={!enabled}
                  onClick={() =>
                    void run({
                      action: "inspect",
                      generationSha256: shownSource.generationSha256,
                    })
                  }
                >
                  Inspect prepared generation
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Inspect to see the exact source, contents and current knowledge.
                No model is started or downloaded.
              </p>
            )}
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Current knowledge</CardTitle>
            <CardDescription>
              Only a confirmed publication or restore changes this state.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <p className="break-all text-sm">
              {shownSource ? (
                <>
                  <span>Last inspected active reference: </span>
                  <code className="text-xs">
                    {shownSource.activeGenerationSha256 ??
                      "No active generation"}
                  </code>
                </>
              ) : (
                "Current state has not been inspected."
              )}
            </p>
            {shownGeneration && (
              <div className="grid gap-2 text-sm">
                <Badge className="w-fit" variant="secondary">
                  {shownGeneration.status}
                </Badge>
                <p>
                  Inspected target:{" "}
                  <code className="break-all text-xs">
                    {shownGeneration.generationSha256}
                  </code>
                </p>
                <p>
                  Revision:{" "}
                  <span className="break-all">
                    {shownGeneration.sourceRevision}
                  </span>
                </p>
                <p>
                  {shownGeneration.conceptCount} concepts ·{" "}
                  {shownGeneration.chunkCount} chunks ·{" "}
                  {shownGeneration.relationshipCount} relationships ·{" "}
                  {shownGeneration.permissionCount} permissions
                </p>
              </div>
            )}
            <Button
              type="button"
              disabled={!canPublish}
              onClick={() => decide("publish")}
            >
              Review publication
            </Button>
            <p className="text-xs leading-5 text-muted-foreground">
              Stage, prepare embeddings and inspect the matching generation
              before publication. Inspection describes metadata; the service
              validates the complete source and vectors.
            </p>
            {owned && activation && (
              <p className="text-sm">
                Last confirmed activation:{" "}
                <code className="break-all text-xs">
                  {activation.generationSha256}
                </code>
              </p>
            )}
          </CardContent>
        </Card>
      </div>
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Restore retained knowledge</CardTitle>
          <CardDescription>
            Use a saved generation reference that you admitted and previously
            published. Pruned or another reviewer's generations remain
            unavailable.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <label className="grid gap-2 text-sm">
            Saved generation reference
            <Input
              aria-label="Saved generation reference"
              value={owned ? saved : ""}
              onChange={(event) => {
                setSaved(event.target.value);
                setGeneration(null);
                setDecision(null);
                setInspectingRestore(false);
              }}
              maxLength={64}
              spellCheck={false}
              className="font-mono text-xs"
              disabled={pending || !owned}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!enabled || !generationReference(saved)}
              onClick={() =>
                void run({ action: "inspect", generationSha256: saved }, true)
              }
            >
              Inspect saved generation
            </Button>
            <Button
              type="button"
              disabled={!canRestore}
              onClick={() => decide("restore")}
            >
              Review restore
            </Button>
          </div>
        </CardContent>
      </Card>
      <AlertDialog
        open={owned && !!decision}
        onOpenChange={(open) => {
          if (!open) setDecision(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {decision?.action === "restore"
                ? "Restore retained knowledge?"
                : "Publish reviewed knowledge?"}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="grid gap-3">
                <p>
                  {decision?.action === "restore"
                    ? "Restore the exact retained projection without regenerating its vectors."
                    : "Make the inspected reviewed generation current for permission-filtered knowledge reads."}{" "}
                  The service will refuse if current knowledge has changed.
                </p>
                <p>
                  Target:{" "}
                  <code className="break-all text-xs">
                    {decision?.generationSha256}
                  </code>
                </p>
                <p>
                  Expected current reference:{" "}
                  <code className="break-all text-xs">
                    {decision?.expectedActiveGenerationSha256 ??
                      "No active generation"}
                  </code>
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep current knowledge</AlertDialogCancel>
            <AlertDialogAction
              disabled={!enabled}
              onClick={() => {
                if (decision) void run(decision);
              }}
            >
              {decision?.action === "restore"
                ? "Restore knowledge"
                : "Publish knowledge"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
