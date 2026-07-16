import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useRef, useState } from "react";

import {
  confirmPrimaryLanguage,
  primaryLanguageStatus,
  type PrimaryLanguageStatus,
} from "@/language-preference";

export function usePrimaryLanguage() {
  const [status, setStatus] = useState<PrimaryLanguageStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const requestGeneration = useRef(0);

  const load = useCallback(async () => {
    if (!isTauri()) return null;
    const generation = ++requestGeneration.current;
    setPending(true);
    setError("");
    try {
      const next = await primaryLanguageStatus();
      if (requestGeneration.current === generation) setStatus(next);
      return next;
    } catch (reason) {
      if (requestGeneration.current === generation) setError(String(reason));
      throw reason;
    } finally {
      if (requestGeneration.current === generation) setPending(false);
    }
  }, []);

  const confirm = useCallback(async (languageBcp47: string) => {
    const catalogRevision = status?.capabilityCatalog?.catalogRevision;
    if (!isTauri() || !catalogRevision) {
      throw new Error("Current ASR language capabilities are unavailable.");
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

  return { confirm, error, load, pending, status };
}
