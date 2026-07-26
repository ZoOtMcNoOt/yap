import {
  type AuxiliaryModelControl,
  useAuxiliaryModelControl,
} from "@/hooks/use-auxiliary-model-control";
import type { AcousticLanguageDetectorView } from "@/lib/setup-model";
import {
  acousticLanguageDetectorStatus,
  cancelAcousticLanguageDetectorImport,
  importAcousticLanguageDetector,
  removeAcousticLanguageDetector,
  verifyAcousticLanguageDetector,
} from "@/settings";

type BaseControl = AuxiliaryModelControl<AcousticLanguageDetectorView>;

export type AcousticLanguageDetectorControl = Omit<BaseControl, "install"> & {
  importModel: BaseControl["install"];
};

const acousticLanguageDetectorPort = {
  cancelInstall: cancelAcousticLanguageDetectorImport,
  install: importAcousticLanguageDetector,
  remove: removeAcousticLanguageDetector,
  status: acousticLanguageDetectorStatus,
  verify: verifyAcousticLanguageDetector,
};

const acousticLanguageDetectorCopy = {
  installFailure: "Language detector import failed",
  installed: "Offline language detector imported",
  noun: "Language detector",
  removeFailure: "Language detector removal failed",
  removed: "Offline language detector removed",
  verificationFailure: "Language detector verification failed",
  verified: "Offline language detector verified",
};

export function useAcousticLanguageDetectorControl(): AcousticLanguageDetectorControl {
  const { install, ...control } = useAuxiliaryModelControl(
    acousticLanguageDetectorPort,
    acousticLanguageDetectorCopy,
  );
  return { ...control, importModel: install };
}
