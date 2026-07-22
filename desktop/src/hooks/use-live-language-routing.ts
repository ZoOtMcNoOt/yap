import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useRef, useState } from "react";

import {
  liveLanguageRoutingStatus,
  saveLiveLanguageRouting,
  updateAutomaticLanguageSelection,
  type LiveLanguageRoutingStatus,
} from "@/live-language-routing";

export function useLiveLanguageRouting() {
  const [status, setStatus] = useState<LiveLanguageRoutingStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const requestGeneration = useRef(0);

  const load = useCallback(async () => {
    if (!isTauri()) return null;
    const generation = ++requestGeneration.current;
    setPending(true);
    setError("");
    try {
      const next = await liveLanguageRoutingStatus();
      if (requestGeneration.current === generation) setStatus(next);
      return next;
    } catch (reason) {
      if (requestGeneration.current === generation) setError(String(reason));
      throw reason;
    } finally {
      if (requestGeneration.current === generation) setPending(false);
    }
  }, []);

  const save = useCallback(async (enabledAlternateLocales: string[]) => {
    if (!isTauri() || !status) {
      throw new Error("Local language routing is unavailable.");
    }
    const generation = ++requestGeneration.current;
    setPending(true);
    setError("");
    try {
      const next = await saveLiveLanguageRouting(enabledAlternateLocales, status.catalogRevision);
      if (requestGeneration.current === generation) setStatus(next);
      return next;
    } catch (reason) {
      if (requestGeneration.current === generation) setError(String(reason));
      throw reason;
    } finally {
      if (requestGeneration.current === generation) setPending(false);
    }
  }, [status]);

  const update = useCallback(async (languageCode: string, locale: string | null) => {
    if (!status) throw new Error("Local language routing is unavailable.");
    return save(updateAutomaticLanguageSelection(status, languageCode, locale));
  }, [save, status]);

  const reset = useCallback(async () => save([]), [save]);

  return { error, load, pending, reset, status, update };
}

export type LiveLanguageRoutingControl = ReturnType<typeof useLiveLanguageRouting>;
