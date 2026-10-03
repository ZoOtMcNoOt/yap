import { isTauri } from "@tauri-apps/api/core";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fixedBatchLanguageOptions, type PrimaryLanguageStatus } from "@/language-preference";
import { formatLanguageTag } from "@/lib/language-display";
import { fallbackStatusText } from "@/lib/setup-model-state";
import { type FallbackModelView, serverConnectionLabel } from "@/lib/setup-model";
import type { ServerConnectionSnapshot } from "@/server";

type LanguageControl = {
  confirm: (languageBcp47: string) => Promise<boolean>;
  error: string;
  localLanguages: string[];
  pending: boolean;
  status: PrimaryLanguageStatus | null;
};

// Setup and Settings share the same native language projection. Saving a
// preference confirms a choice; it does not verify a microphone or inference.
export function FirstRunTakeover({
  fallbackModel,
  language,
  onOpenSettings,
  onOpenTranscribe,
  onRetry,
  serverSnapshot,
}: {
  fallbackModel: FallbackModelView | null;
  language: LanguageControl;
  onOpenSettings: () => void;
  onOpenTranscribe: () => void;
  onRetry: () => void;
  serverSnapshot: ServerConnectionSnapshot;
}) {
  const [phase, setPhase] = useState<"language" | "routes">("language");
  const [dismissed, setDismissed] = useState(false);
  const [choice, setChoice] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const languages = useMemo(() => {
    const merged = [...new Set([
      ...language.localLanguages,
      ...fixedBatchLanguageOptions(language.status?.capabilityCatalog).map((option) => option.languageBcp47),
    ])];
    const suggestion = language.status?.suggestedLanguageBcp47;
    return suggestion && merged.includes(suggestion)
      ? [suggestion, ...merged.filter((tag) => tag !== suggestion)]
      : merged;
  }, [language.localLanguages, language.status]);
  const preferred = choice || language.status?.suggestedLanguageBcp47 || "";
  const selectedLanguage = languages.includes(preferred) ? preferred : "";
  const incompatiblePreference = language.status?.preferenceIssue === "incompatibleSchema";
  const open = isTauri() && !dismissed && (phase === "routes"
    || language.status?.requiresConfirmation === true
    || (!language.status && Boolean(language.error)));

  useEffect(() => {
    if (open) heading.current?.focus();
  }, [open, phase]);

  function finish(action?: () => void) {
    setDismissed(true);
    action?.();
  }

  return (
    <Dialog onOpenChange={(next) => { if (!next) finish(); }} open={open}>
      <DialogContent
        className="inset-0 top-0 left-0 flex h-full w-full max-w-none translate-x-0 translate-y-0 items-center justify-center overflow-y-auto rounded-none border-0 shadow-none sm:max-w-none"
        data-testid="first-run-welcome"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          heading.current?.focus();
        }}
        showCloseButton={false}
      >
        <div className="mx-auto flex w-full max-w-xl flex-col gap-6 px-4 py-8">
          <header>
            <DialogTitle asChild>
              <h1 className="text-3xl font-semibold tracking-tight outline-none" ref={heading} tabIndex={-1}>
                {phase === "language" ? "Welcome to Yap" : "Choose how to transcribe"}
              </h1>
            </DialogTitle>
            <DialogDescription className="mt-3 text-base leading-7">
              {phase === "language"
                ? "Turn recordings into readable transcripts on your organization's server, or use local dictation with an installed model."
                : `${formatLanguageTag(language.status?.confirmedLanguageBcp47 ?? selectedLanguage)} is saved as your primary language. You can change it in Settings.`}
            </DialogDescription>
          </header>
          {phase === "language" ? (
            <>
              <div className="grid gap-3">
                <label className="text-sm font-medium" htmlFor="first-run-language">Primary language</label>
                <Select
                  disabled={!languages.length || language.pending || incompatiblePreference}
                  onValueChange={setChoice}
                  value={selectedLanguage}
                >
                  <SelectTrigger aria-label="Primary language" data-testid="first-run-language" id="first-run-language">
                    <SelectValue placeholder="Choose language" />
                  </SelectTrigger>
                  <SelectContent><SelectGroup>
                    {languages.map((tag) => <SelectItem key={tag} value={tag}>{formatLanguageTag(tag)}</SelectItem>)}
                  </SelectGroup></SelectContent>
                </Select>
                <p className="text-sm leading-6 text-muted-foreground">
                  {selectedLanguage
                    ? "Nothing is saved until you confirm this language."
                    : "Choose a supported primary language. Nothing is saved until you confirm."}
                </p>
                {incompatiblePreference ? (
                  <p className="text-sm leading-6 text-destructive" role="alert">
                    Your language setting was saved by a newer version of Yap. Update the app before changing it.
                  </p>
                ) : language.error ? (
                  <div className="grid gap-2" role="alert">
                    <p className="text-sm text-destructive">{language.error}</p>
                    {!language.status ? <Button onClick={onRetry} type="button" variant="outline">Retry setup check</Button> : null}
                  </div>
                ) : !languages.length ? (
                  <p className="text-sm text-muted-foreground" role="status">
                    {language.pending ? "Checking available languages…" : "Languages are unavailable. You can continue and retry in Settings."}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  disabled={!selectedLanguage || !language.status || language.pending || incompatiblePreference}
                  onClick={() => void language.confirm(selectedLanguage).then((saved) => {
                    if (saved) setPhase("routes");
                  })}
                  type="button"
                >
                  {language.pending ? "Saving…" : "Confirm language"}
                </Button>
                <Button onClick={() => finish()} type="button" variant="outline">Skip for now</Button>
              </div>
              <p className="text-sm leading-6 text-muted-foreground">
                No model is downloaded and no server is connected by this step. Local dictation stays on this device; server jobs use the organization server you configure.
              </p>
            </>
          ) : (
            <>
              <section className="grid gap-2 rounded-xl border p-4" aria-label="Recording transcription">
                <h2 className="font-semibold">Transcribe recordings</h2>
                <p className="text-sm text-muted-foreground">
                  {serverSnapshot.state === "ready" && serverSnapshot.capabilities.batchJobs
                    ? "Your organization server is available. Choose a recording language and add files in Transcribe."
                    : "Configure an organization server in Settings → System. Imported recordings wait for their server route; they do not switch to local dictation."}
                </p>
                <p className="text-sm">Server: {serverConnectionLabel(serverSnapshot.state)}</p>
                <Button onClick={() => finish(onOpenTranscribe)} type="button" variant="outline">Open Transcribe</Button>
              </section>
              <section className="grid gap-2 rounded-xl border p-4" aria-label="Local dictation">
                <h2 className="font-semibold">Local dictation</h2>
                <p className="text-sm">
                  {fallbackModel ? fallbackStatusText(fallbackModel, fallbackModel.status !== "disabled") : "Model status unavailable"}
                </p>
                <p className="text-sm text-muted-foreground">
                  {fallbackModel?.status === "ready"
                    ? "Set your microphone and shortcut in Settings, then try your first dictation."
                    : "Install or repair the local model in Settings → System when you are ready. You can browse transcripts and configure the app first."}
                </p>
              </section>
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => finish(onOpenSettings)} type="button">Open Settings</Button>
                <Button onClick={() => finish()} type="button" variant="outline">Explore Yap</Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
