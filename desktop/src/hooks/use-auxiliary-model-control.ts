import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import type {
  AuxiliaryModelDownloadProgress,
  AuxiliaryModelView,
} from "@/lib/setup-model";

export type AuxiliaryModelAction = "install" | "verify" | "remove" | null;

export type AuxiliaryModelControl<View extends AuxiliaryModelView = AuxiliaryModelView> = {
  action: AuxiliaryModelAction;
  cancelInstall: () => Promise<void>;
  install: () => Promise<void>;
  progress: AuxiliaryModelDownloadProgress | null;
  remove: () => Promise<void>;
  verify: () => Promise<void>;
  view: View | null;
};

type AuxiliaryModelPort<View extends AuxiliaryModelView> = {
  cancelInstall: () => Promise<View>;
  install: () => Promise<View>;
  listenProgress?: (
    onProgress: (progress: AuxiliaryModelDownloadProgress) => void,
  ) => Promise<() => void>;
  remove: () => Promise<View>;
  status: () => Promise<View>;
  verify: () => Promise<View>;
};

type AuxiliaryModelCopy = {
  installFailure: string;
  installed: string;
  noun: string;
  removeFailure: string;
  removed: string;
  verificationFailure: string;
  verified: string;
};

export function useAuxiliaryModelControl<View extends AuxiliaryModelView>(
  port: AuxiliaryModelPort<View>,
  copy: AuxiliaryModelCopy,
): AuxiliaryModelControl<View> {
  const [action, setAction] = useState<AuxiliaryModelAction>(null);
  const [progress, setProgress] = useState<AuxiliaryModelDownloadProgress | null>(null);
  const [view, setView] = useState<View | null>(null);

  const refresh = useCallback(async () => {
    if (!isTauri()) return;
    setView(await port.status());
  }, [port]);

  useEffect(() => {
    void refresh().catch((error) => {
      toast.error(`${copy.noun} check failed: ${String(error)}`);
    });
  }, [copy, refresh]);

  useEffect(() => {
    if (!isTauri() || !port.listenProgress) return;
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void port.listenProgress((next) => {
      if (!cancelled) setProgress(next);
    }).then((stop) => {
      if (cancelled) {
        stop();
      } else {
        unlisten = stop;
      }
    }).catch((error) => {
      if (!cancelled) {
        toast.error(`${copy.noun} progress listener failed: ${String(error)}`);
      }
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [copy, port]);

  const install = useCallback(async () => {
    if (!isTauri() || action !== null) return;
    setAction("install");
    setProgress(null);
    setView((current) => current ? { ...current, installActive: true } : current);
    try {
      setView(await port.install());
      toast.success(copy.installed);
    } catch (error) {
      toast.error(`${copy.installFailure}: ${String(error)}`);
    } finally {
      setAction(null);
      setProgress(null);
      await refresh().catch(() => undefined);
    }
  }, [action, copy, port, refresh]);

  const cancelInstall = useCallback(async () => {
    if (!isTauri() || action !== "install") return;
    try {
      setView(await port.cancelInstall());
      toast.info(`${copy.noun} cancellation requested`);
    } catch (error) {
      toast.error(`Cancel failed: ${String(error)}`);
    }
  }, [action, copy, port]);

  const verify = useCallback(async () => {
    if (!isTauri() || action !== null) return;
    setAction("verify");
    try {
      setView(await port.verify());
      toast.success(copy.verified);
    } catch (error) {
      toast.error(`${copy.verificationFailure}: ${String(error)}`);
      await refresh().catch(() => undefined);
    } finally {
      setAction(null);
    }
  }, [action, copy, port, refresh]);

  const remove = useCallback(async () => {
    if (!isTauri() || action !== null) return;
    setAction("remove");
    try {
      setView(await port.remove());
      toast.success(copy.removed);
    } catch (error) {
      toast.error(`${copy.removeFailure}: ${String(error)}`);
      await refresh().catch(() => undefined);
    } finally {
      setAction(null);
    }
  }, [action, copy, port, refresh]);

  return { action, cancelInstall, install, progress, remove, verify, view };
}
