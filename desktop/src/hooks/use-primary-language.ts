import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useRef, useState } from "react";

import {
  confirmPrimaryLanguage,
  fixedBatchLanguageOptions,
  localDictationLanguages,
  primaryLanguageStatus,
  type PrimaryLanguageStatus,
} from "@/language-preference";

export function usePrimaryLanguage() {
  const [status, setStatus] = useState<PrimaryLanguageStatus | null>(null);
  const [localLanguages, setLocalLanguages] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const requestGeneration = useRef(0);

  const load = useCallback(async () => {
    if (!isTauri()) return null;
    const generation = ++requestGeneration.current;
    setPending(true);
    setError("");
    try {
      const [next, languages] = await Promise.all([
        primaryLanguageStatus(),
        localDictationLanguages().catch(() => []),
      ]);
      if (requestGeneration.current === generation) {
        setStatus(next ?? null);
        setLocalLanguages(Array.isArray(languages) ? languages : []);
      }
      return next;
    } catch (reason) {
      if (requestGeneration.current === generation) setError(String(reason));
      throw reason;
    } finally {
      if (requestGeneration.current === generation) setPending(false);
    }
  }, []);

  const confirm = useCallback(async (languageBcp47: string) => {
    // A server-supported choice names its current catalog. A local-only
    // choice is validated against the native dictation catalog; it does not
    // grant a batch route or rewrite per-recording choices.
    const serverSupportsLanguage = fixedBatchLanguageOptions(status?.capabilityCatalog)
      .some((option) => option.languageBcp47 === languageBcp47);
    const catalogRevision = serverSupportsLanguage
      ? status?.capabilityCatalog?.catalogRevision ?? null
      : null;
    if (!isTauri()) {
      throw new Error("Language confirmation requires the desktop app.");
    }
    const generation = ++requestGeneration.current;
    setPending(true);
    setError("");
    try {
      const next = await confirmPrimaryLanguage(languageBcp47, catalogRevision);
      if (requestGeneration.current === generation) setStatus(next);
      return next;
    } catch (reason) {
      if (requestGeneration.current === generation) setError(String(reason));
      throw reason;
    } finally {
      if (requestGeneration.current === generation) setPending(false);
    }
  }, [status?.capabilityCatalog?.catalogRevision]);

  return { confirm, error, load, localLanguages, pending, status };
}
