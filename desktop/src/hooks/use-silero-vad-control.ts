import {
  type AuxiliaryModelControl,
  useAuxiliaryModelControl,
} from "@/hooks/use-auxiliary-model-control";
import type { SileroVadView } from "@/lib/setup-model";
import {
  cancelSileroVadInstall,
  installSileroVad,
  listenSileroVadProgress,
  removeSileroVad,
  sileroVadStatus,
  verifySileroVad,
} from "@/settings";

export type SileroVadControl = AuxiliaryModelControl<SileroVadView>;

const sileroVadPort = {
  cancelInstall: cancelSileroVadInstall,
  install: installSileroVad,
  listenProgress: listenSileroVadProgress,
  remove: removeSileroVad,
  status: sileroVadStatus,
  verify: verifySileroVad,
};

const sileroVadCopy = {
  installFailure: "Speech detection install failed",
  installed: "Speech detection model installed",
  noun: "Speech detection",
  removeFailure: "Speech detection removal failed",
  removed: "Speech detection model removed",
  verificationFailure: "Speech detection verification failed",
  verified: "Speech detection model verified",
};

export function useSileroVadControl(): SileroVadControl {
  return useAuxiliaryModelControl(sileroVadPort, sileroVadCopy);
}
