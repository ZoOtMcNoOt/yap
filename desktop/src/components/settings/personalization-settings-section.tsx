import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalFocusReturn } from "@/components/ui/use-modal-focus-return";
import { SettingsGroup } from "@/components/settings/settings-primitives";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { TerminologyControl } from "@/hooks/use-terminology";
import type { Sensitivity } from "@/terminology";
import type { ServerConnectionSnapshot } from "@/server";

const selectClass =
  "h-10 w-full rounded-md border bg-background px-3 text-sm focus-visible:outline-ring disabled:opacity-50";
function languageName(locale: string) {
  if (locale === "und") return "All languages";
  try {
    return (
      new Intl.DisplayNames(["en"], { type: "language" }).of(locale) ?? locale
    );
  } catch {
    return locale;
  }
}

export function PersonalizationSettingsSection({
  control: c,
  snapshot,
  languages,
  onOpenSystem,
}: {
  control: TerminologyControl;
  snapshot: ServerConnectionSnapshot;
  languages: string[];
  onOpenSystem: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const deleteFocus = useModalFocusReturn({});
  const addButton = useRef<HTMLButtonElement>(null);
  const priorDraft = useRef(false);
  useEffect(() => {
    if (c.draft) {
      if (!priorDraft.current) input.current?.focus();
      priorDraft.current = true;
    } else if (priorDraft.current && !c.pending) {
      addButton.current?.focus();
      priorDraft.current = false;
    }
  }, [c.draft, c.pending]);
  const scopeName =
    c.scopeId === "personal"
      ? "personal"
      : c.scopeId === "organization"
        ? "organization"
        : "team";
  const listName = `${scopeName[0].toUpperCase()}${scopeName.slice(1)} terms`;
  const locales = [...new Set([c.locale, ...languages, "und"])];
  const blockedMessage =
    snapshot.state === "sign_in_required"
      ? "Sign in to your organization in System settings to manage your terms."
      : snapshot.state === "access_denied"
        ? "Your organization has not granted access to terminology."
        : snapshot.state === "ready"
          ? "Terminology is not enabled on this server. Ask your administrator to configure it."
          : "Connect to your private server in System settings to manage your terms. Local recording remains available.";

  return (
    <div className="grid gap-6">
      <div className="text-sm text-muted-foreground">
        <p>
          Add names, acronyms and preferred spellings for new server transcript
          corrections.
        </p>
        {!snapshot.capabilities.transcriptCorrection ? (
          <p className="mt-1">
            Terms can be saved now; transcript correction is not enabled on this
            server yet.
          </p>
        ) : null}
        <p className="mt-1">
          Personal terms apply only to you. Shared terms apply to the people
          granted access by your organization. Existing jobs keep their original
          terminology.
        </p>
      </div>
      {!c.available ? (
        <SettingsGroup>
          <p role="status" className="text-sm">
            {blockedMessage}
          </p>
          {c.draft && !c.accountUnavailable ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Your draft is kept for when the connection returns.
            </p>
          ) : null}
          <Button className="mt-4" onClick={onOpenSystem} variant="outline">
            Open System settings
          </Button>
        </SettingsGroup>
      ) : null}
      {c.available ? (
        <>
          <div className="grid gap-2">
            <label className="grid gap-2 text-sm font-medium">
              Terminology scope
              <select
                aria-label="Terminology scope"
                className={selectClass}
                disabled={
                  c.pending ||
                  c.draft !== null ||
                  c.deleting !== null ||
                  c.scopes.length === 0
                }
                value={c.scopeId}
                onChange={(e) => c.changeScope(e.target.value)}
              >
                {!c.scope ? (
                  <option value={c.scopeId}>Scope unavailable</option>
                ) : null}
                {c.scopes.map((scope) => (
                  <option key={scope.scopeId} value={scope.scopeId}>
                    {scope.kind === "personal"
                      ? scope.label
                      : `${scope.kind === "team" ? "Team" : "Organization"} · ${scope.label}`}
                  </option>
                ))}
              </select>
            </label>
            {c.scope && !c.canManage ? (
              <p className="text-sm text-muted-foreground" role="status">
                You can view these terms. Your organization controls who can
                edit them.
              </p>
            ) : !c.scope && c.scopes.length > 0 ? (
              <p className="text-sm text-muted-foreground" role="status">
                This scope is no longer available. Cancel any draft and choose
                another scope.
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <label className="grid min-w-0 gap-2 text-sm font-medium">
              Term language
              <select
                aria-label="Term language"
                className={selectClass}
                disabled={c.pending || c.draft !== null || c.deleting !== null}
                onChange={(e) => c.changeLocale(e.target.value)}
                value={c.locale}
              >
                {locales.map((locale) => (
                  <option key={locale} value={locale}>
                    {languageName(locale)}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={c.pending}
                onClick={() => void c.refresh()}
                variant="outline"
              >
                Refresh terms
              </Button>
              {c.canManage ? (
                <Button
                  disabled={
                    c.pending || c.draft !== null || c.deleting !== null
                  }
                  onClick={() => c.start()}
                  ref={addButton}
                >
                  Add term
                </Button>
              ) : null}
            </div>
          </div>
          {c.error ? (
            <p className="text-sm text-destructive" role="alert">
              {c.error}
            </p>
          ) : null}
          {c.notice ? (
            <p className="text-sm text-muted-foreground" role="status">
              {c.notice}
            </p>
          ) : null}
          {c.draft ? (
            <SettingsGroup>
              <form
                className="grid gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  void c.save();
                }}
              >
                <h3 className="font-medium">
                  {c.draft.recordId
                    ? `Edit ${scopeName} term`
                    : `New ${scopeName} term`}
                </h3>
                <label className="grid gap-2 text-sm font-medium">
                  Preferred spelling
                  <Input
                    disabled={c.pending || !c.canManage}
                    onChange={(e) =>
                      c.setDraft((d) =>
                        d ? { ...d, canonicalForm: e.target.value } : null,
                      )
                    }
                    placeholder="e.g. Yap"
                    ref={input}
                    value={c.draft.canonicalForm}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  Heard as
                  <textarea
                    aria-describedby="term-variants-help"
                    className="min-h-24 w-full resize-y rounded-md border bg-background p-3 text-sm focus-visible:outline-ring disabled:opacity-50"
                    disabled={c.pending || !c.canManage}
                    onChange={(e) =>
                      c.setDraft((d) =>
                        d ? { ...d, variantsText: e.target.value } : null,
                      )
                    }
                    placeholder={"yapp\nyap app"}
                    value={c.draft.variantsText}
                  />
                </label>
                <p
                  className="-mt-2 text-xs text-muted-foreground"
                  id="term-variants-help"
                >
                  One spelling or phrase per line, up to 64 variants.
                </p>
                <label className="grid gap-2 text-sm font-medium">
                  Sensitivity
                  <select
                    className={selectClass}
                    disabled={c.pending || !c.canManage}
                    onChange={(e) =>
                      c.setDraft((d) =>
                        d
                          ? { ...d, sensitivity: e.target.value as Sensitivity }
                          : null,
                      )
                    }
                    value={c.draft.sensitivity}
                  >
                    <option value="public">Public</option>
                    <option value="internal">Internal</option>
                    <option value="confidential">Confidential</option>
                    <option value="restricted">Restricted</option>
                  </select>
                </label>
                {c.conflict && c.draft.recordId ? (
                  <Button
                    disabled={c.pending}
                    onClick={() => void c.compareLatest()}
                    type="button"
                    variant="outline"
                  >
                    {c.pendingAction === "compare"
                      ? "Comparing…"
                      : "Compare latest version"}
                  </Button>
                ) : null}
                {c.latest ? (
                  <div className="grid gap-2 rounded-lg border p-3 text-sm">
                    <p className="font-medium">
                      Latest saved spelling: {c.latest.canonicalForm}
                    </p>
                    <p className="break-words text-muted-foreground">
                      Heard as: {c.latest.variants.join(", ")}
                    </p>
                    <p className="text-muted-foreground">
                      Sensitivity: {c.latest.sensitivity}
                    </p>
                    <Button
                      disabled={c.pending}
                      onClick={c.applyDraftToLatest}
                      type="button"
                      variant="outline"
                    >
                      Apply my draft to latest version
                    </Button>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={c.pending || c.conflict || !c.canManage}
                    type="submit"
                  >
                    {c.pendingAction === "save"
                      ? "Saving…"
                      : c.draft.recordId
                        ? "Save changes"
                        : "Save term"}
                  </Button>
                  <Button
                    disabled={c.pending}
                    onClick={c.cancel}
                    type="button"
                    variant="ghost"
                  >
                    Cancel edit
                  </Button>
                </div>
              </form>
            </SettingsGroup>
          ) : null}
          {c.pending && !c.loaded ? (
            <p className="text-sm text-muted-foreground" role="status">
              Loading terms…
            </p>
          ) : c.loaded && c.records.length === 0 ? (
            <SettingsGroup>
              <h3 className="font-medium">No {scopeName} terms yet</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {c.canManage
                  ? "Add a preferred spelling and the variants you want corrections to recognize."
                  : "No terms are available for this language. Your administrator can add shared terms."}
              </p>
            </SettingsGroup>
          ) : null}
          {c.records.length > 0 ? (
            <ul
              aria-label={listName}
              className="divide-y rounded-xl border px-4"
            >
              {c.records.map((term) => (
                <li
                  className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-4"
                  key={term.recordId}
                >
                  <div className="min-w-0 flex-1">
                    <p className="break-words font-medium">
                      {term.canonicalForm}
                    </p>
                    <p className="mt-1 break-words text-sm text-muted-foreground">
                      {term.variants.slice(0, 3).join(", ")}
                      {term.variants.length > 3
                        ? ` +${term.variants.length - 3} more`
                        : ""}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {languageName(term.locale)} · {term.sensitivity}
                    </p>
                  </div>
                  {c.canManage ? (
                    <div className="flex gap-1">
                      <Button
                        aria-label={`Edit ${term.canonicalForm}`}
                        disabled={c.pending || c.draft !== null}
                        onClick={() => c.start(term)}
                        size="sm"
                        variant="ghost"
                      >
                        Edit
                      </Button>
                      <Button
                        aria-label={`Delete ${term.canonicalForm}`}
                        disabled={c.pending || c.draft !== null}
                        onClick={() => c.setDeleting(term)}
                        size="sm"
                        variant="ghost"
                      >
                        Delete
                      </Button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {c.nextCursor ? (
            <Button
              disabled={c.pending}
              onClick={() => void c.more()}
              variant="outline"
            >
              Load more terms
            </Button>
          ) : null}
        </>
      ) : null}
      <AlertDialog
        onOpenChange={(open) => {
          if (!open && !c.pending) c.setDeleting(null);
        }}
        open={c.deleting !== null && c.available}
      >
        <AlertDialogContent
          {...deleteFocus}
          onEscapeKeyDown={(event) => {
            if (c.pending) event.preventDefault();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {scopeName} term?</AlertDialogTitle>
            <AlertDialogDescription>
              Remove “{c.deleting?.canonicalForm}” from new jobs. Existing job
              terminology and version history are preserved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {c.error ? (
            <p className="text-sm text-destructive" role="alert">
              {c.conflict
                ? "This term changed. Cancel deletion, refresh the list and review the latest term."
                : c.error}
            </p>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={c.pending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={c.pending || !c.canManage}
              onClick={(event) => {
                event.preventDefault();
                void c.remove();
              }}
            >
              {c.pendingAction === "delete" ? "Deleting…" : "Delete term"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
