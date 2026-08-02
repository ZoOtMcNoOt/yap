import { isTauri } from "@tauri-apps/api/core";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePrimaryLanguage } from "@/hooks/use-primary-language";
import {
  localDictationLanguages,
  type RecordingImportLanguageOption,
} from "@/language-preference";
import { formatLanguageTag } from "@/lib/language-display";

// The utterance is scripted so the first dictation cannot fail interestingly:
// short, phonetically plain, and the words are the product's privacy promise.
const PRACTICE_SCRIPT = "Yap is running entirely on this computer.";
// Long enough that a stray keypress does not count as a dictation.
const PRACTICE_SUCCESS_CHARS = 8;

type Phase = "language" | "practice" | "celebrate";

// Full-window first-run, one surface with three phases: choose the language,
// perform the hotkey once into a practice field the takeover owns, then a
// success screen whose last words push the user into a real app. Dictation
// types into the focused field, so the practice box IS the proof — no extra
// audio plumbing, and a silent mic cannot fail invisibly because nothing
// arrives in the box.
//
// It renders only in the Tauri shell: the browser preview cannot confirm a
// language or receive dictation, and a takeover that cannot complete would
// just wall off the app.
export function FirstRunTakeover({
  hotkey,
  languageOptions,
}: {
  hotkey: string;
  languageOptions: RecordingImportLanguageOption[];
}) {
  const primary = usePrimaryLanguage();
  const [localLanguages, setLocalLanguages] = useState<string[]>([]);
  const [choice, setChoice] = useState("");
  const [phase, setPhase] = useState<Phase>("language");
  const [dismissed, setDismissed] = useState(false);
  const [practiceText, setPracticeText] = useState("");

  useEffect(() => {
    if (!isTauri()) return;
    void primary.load().catch(() => undefined);
    // A harness that answers nothing must not crash the surface.
    localDictationLanguages()
      .then((languages) => setLocalLanguages(Array.isArray(languages) ? languages : []))
      .catch(() => undefined);
    // Load once on mount; the confirm result updates status directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The server catalog's fixed-batch locales when one exists, the local
  // dictation catalog always; deduplicated, suggestion first.
  const firstRunLanguages = useMemo(() => {
    const fromServer = (primary.status?.capabilityCatalog ? languageOptions : [])
      .flatMap((option) => (option.mode === "fixed" ? [option.languageBcp47] : []));
    const merged = [...new Set([...localLanguages, ...fromServer])];
    const suggested = primary.status?.suggestedLanguageBcp47;
    if (suggested && merged.includes(suggested)) {
      return [suggested, ...merged.filter((language) => language !== suggested)];
    }
    return merged;
  }, [languageOptions, localLanguages, primary.status]);

  const suggestion = primary.status?.suggestedLanguageBcp47 ?? "";
  const selectedLanguage = choice || suggestion;

  // Confirmation is durable after phase one, so the takeover keeps itself
  // alive across the remaining phases and only the initial mount decides
  // whether a first run is happening at all.
  const [active] = useState(() => isTauri());
  const needsFirstRun = primary.status?.requiresConfirmation !== false;
  if (!active || dismissed) return null;
  if (phase === "language" && (primary.status === undefined || !needsFirstRun)) return null;

  return (
    <div
      aria-label="Welcome to Yap"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-background"
      data-testid="first-run-welcome"
      role="dialog"
    >
      <div className="mx-auto flex w-full max-w-xl flex-col gap-8 px-8 py-12 text-center">
        {phase === "language" ? (
          <>
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">Welcome to Yap</h1>
              <p className="mt-3 text-base leading-7 text-muted-foreground">
                Yap types what you say — on this machine, into any app.
              </p>
            </div>
            <div className="flex flex-col items-center gap-4">
              <p className="text-sm font-medium">What language do you speak?</p>
              <Select
                disabled={!firstRunLanguages.length || primary.pending}
                onValueChange={setChoice}
                value={selectedLanguage || undefined}
              >
                <SelectTrigger
                  aria-label="Dictation language"
                  className="min-w-[240px]"
                  data-testid="first-run-language"
                >
                  <SelectValue placeholder="Choose language" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {firstRunLanguages.map((language) => (
                      <SelectItem key={language} value={language}>
                        {formatLanguageTag(language)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button
                disabled={!selectedLanguage || primary.pending}
                onClick={() => {
                  void primary
                    .confirm(selectedLanguage)
                    .then(() => setPhase("practice"))
                    .catch(() => undefined);
                }}
                size="lg"
                type="button"
              >
                {primary.pending ? "Saving…" : "Confirm"}
              </Button>
              {primary.error ? (
                <p className="max-w-md text-xs leading-5 text-destructive" role="alert">
                  {primary.error}
                </p>
              ) : null}
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              No account. No downloads. Everything stays on this computer.
            </p>
          </>
        ) : phase === "practice" ? (
          <>
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">Try it right now</h1>
              <p className="mt-3 text-base leading-7 text-muted-foreground">
                Click into the box, hold{" "}
                <kbd className="rounded border px-1.5 py-0.5 text-sm font-semibold">{hotkey}</kbd>,
                and say:
              </p>
              <p className="mt-3 text-lg font-medium">“{PRACTICE_SCRIPT}”</p>
            </div>
            <textarea
              aria-label="Practice dictation"
              autoFocus
              className="min-h-[96px] w-full resize-none rounded-lg border border-input bg-[var(--surface-transcript)] px-4 py-3 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
              data-testid="first-run-practice"
              onChange={(event) => {
                const text = event.target.value;
                setPracticeText(text);
                if (text.trim().length >= PRACTICE_SUCCESS_CHARS) setPhase("celebrate");
              }}
              placeholder="Your words will appear here"
              value={practiceText}
            />
            <div className="flex flex-col items-center gap-2">
              <p className="text-xs leading-5 text-muted-foreground">
                Nothing appearing? Your microphone may be muted or in use — you can fix it later
                under Settings.
              </p>
              <Button
                className="text-muted-foreground"
                onClick={() => setDismissed(true)}
                size="sm"
                type="button"
                variant="link"
              >
                Skip for now
              </Button>
            </div>
          </>
        ) : (
          <>
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">That's it — you're dictating.</h1>
              <p className="mt-3 text-base leading-7 text-muted-foreground">
                Transcribed on this machine. Nothing left this computer.
              </p>
            </div>
            {practiceText.trim() ? (
              <blockquote className="rounded-xl bg-[var(--primary-soft)] px-5 py-4 text-base text-primary">
                {practiceText.trim()}
              </blockquote>
            ) : null}
            <p className="text-base leading-7">
              Now click into any text box — Notepad, email, Slack — and do it again. The island at
              the top of your screen is always ready for{" "}
              <kbd className="rounded border px-1.5 py-0.5 text-sm font-semibold">{hotkey}</kbd>.
            </p>
            <div>
              <Button onClick={() => setDismissed(true)} size="lg" type="button">
                Start using Yap
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
