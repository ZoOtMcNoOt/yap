import { useId } from "react";

import { AdvancedSettings, SettingsGroup, SettingsRow } from "@/components/settings/settings-primitives";
import { ServerSettingsRows } from "@/components/settings/server-settings-rows";
import type { FallbackLifecycleActionId, FallbackLifecycleProjection } from "@/components/settings/settings-lifecycle";
import type { ServerSettingsDraftController } from "@/components/settings/use-server-settings-draft";
import type { AcousticLanguageDetectorControl } from "@/hooks/use-acoustic-language-detector-control";
import type { SileroVadControl } from "@/hooks/use-silero-vad-control";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { LocalComputeTargetView } from "@/lib/setup-model";

export function SystemSettingsSection({
  advancedDefaultOpen = false,
  busy,
  fallbackLifecycle,
  fallbackLocked,
  liveActive,
  localComputeTargets,
  onFallbackAction,
  onSetLocalComputeTarget,
  server,
  sileroVad,
  languageDetector,
}: {
  advancedDefaultOpen?: boolean;
  busy: boolean;
  fallbackLifecycle: FallbackLifecycleProjection;
  fallbackLocked: boolean;
  liveActive: boolean;
  localComputeTargets: LocalComputeTargetView[];
  onFallbackAction: (actionId: FallbackLifecycleActionId) => void;
  onSetLocalComputeTarget: (targetId: string) => void;
  server: ServerSettingsDraftController;
  sileroVad: SileroVadControl;
  languageDetector: AcousticLanguageDetectorControl;
}) {
  const computeLabelId = useId();
  const selectedComputeTarget = localComputeTargets.find((target) => target.selected);
  const primaryFallbackAction = fallbackLifecycle.primaryAction;
  const vadInstalling = sileroVad.action === "install" || sileroVad.view?.installActive === true;
  const vadPercent = sileroVad.progress?.totalBytes
    ? Math.round((sileroVad.progress.downloadedBytes / sileroVad.progress.totalBytes) * 100)
    : null;
  const vadValue = vadInstalling
    ? vadPercent === null ? "Installing" : `Installing ${vadPercent}%`
    : sileroVad.action === "verify"
      ? "Verifying"
      : sileroVad.action === "remove"
        ? "Removing"
        : sileroVad.view?.status === "ready"
          ? "Ready"
          : sileroVad.view?.status === "corrupted"
            ? "Needs repair"
            : sileroVad.view?.status === "missing"
              ? "Not installed"
              : "Checking";
  const vadDetail = sileroVad.view?.status === "ready"
    ? "Pinned Silero v4 marks advisory speech intervals. Yap always retains the complete source audio."
    : sileroVad.view?.status === "corrupted"
      ? "The optional model failed size or hash verification. Repair it before preprocessing can use VAD."
      : "Optional advisory speech detection. Yap never downloads it during startup, preprocessing, retry, or reconnect.";
  const lidImporting = languageDetector.action === "install" ||
    languageDetector.view?.installActive === true;
  const lidPercent = languageDetector.progress?.totalBytes
    ? Math.round(
      (languageDetector.progress.downloadedBytes / languageDetector.progress.totalBytes) * 100,
    )
    : null;
  const lidReady = languageDetector.view?.status === "ready";
  const vadReady = sileroVad.view?.status === "ready";
  const lidValue = lidImporting
    ? lidPercent === null ? "Importing" : `Importing ${lidPercent}%`
    : languageDetector.action === "verify"
      ? "Verifying"
      : languageDetector.action === "remove"
        ? "Removing"
        : lidReady && vadReady
          ? "Ready"
          : lidReady
            ? "Needs speech detection"
            : languageDetector.view?.status === "corrupted"
              ? "Needs repair"
              : languageDetector.view?.status === "missing"
                ? "Not installed"
                : "Checking";
  const lidDetail = lidReady && vadReady
    ? "Offline switching is an opt-in Preview for explicitly selected alternate locales. It can delay initial live text while gathering a 3-second language window, and the language detector may miss or misclassify natural switches; ambiguous audio stays on the primary language."
    : lidReady
      ? "The classifier is installed, but automatic switching also requires the Speech detection model below."
      : languageDetector.view?.status === "corrupted"
        ? "The language detector failed size or hash verification. Repair it before automatic switching can run."
        : "Optional language detector: import the verified detector model file explicitly. Yap never downloads it during startup or capture.";

  // A lifecycle that needs attention must never hide behind a closed
  // disclosure: broken models are exactly what the user opened Settings for.
  const advancedNeedsAttention =
    advancedDefaultOpen ||
    languageDetector.view?.status === "corrupted" ||
    sileroVad.view?.status === "corrupted";

  return (
    <SettingsGroup>
      <ServerSettingsRows server={server} />
      <AdvancedSettings defaultOpen={advancedNeedsAttention}>
      <SettingsRow
        detail={liveActive ? "Stop live before changing compute." : "Local live uses the CPU runtime. Server owns GPU routing."}
        label="Compute"
        value={selectedComputeTarget?.label ?? "Auto"}
      >
        <Label className="sr-only" id={computeLabelId}>
          Compute
        </Label>
        <Select
          disabled={busy || fallbackLocked}
          onValueChange={onSetLocalComputeTarget}
          value={selectedComputeTarget?.id ?? "auto"}
        >
          <SelectTrigger aria-labelledby={computeLabelId} className="w-full max-w-[360px]">
            <SelectValue placeholder="Auto" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {localComputeTargets.map((target) => (
                <SelectItem key={target.id} value={target.id}>
                  {target.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </SettingsRow>
      <SettingsRow
        detail={fallbackLifecycle.detail}
        label="Local fallback"
        value={fallbackLifecycle.value}
      >
        <div className="flex flex-wrap justify-end gap-2">
          {primaryFallbackAction ? (
            <Button
              disabled={primaryFallbackAction.disabled}
              onClick={() => onFallbackAction(primaryFallbackAction.id)}
              type="button"
            >
              {primaryFallbackAction.label}
            </Button>
          ) : null}
          {fallbackLifecycle.secondaryActions.map((action) => (
            <Button
              disabled={action.disabled}
              key={action.id}
              onClick={() => onFallbackAction(action.id)}
              type="button"
              variant={action.id === "open-folder" ? "ghost" : "secondary"}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </SettingsRow>
      <SettingsRow
        detail={liveActive ? "Stop live before changing language support." : lidDetail}
        label="Automatic language switching"
        value={lidValue}
      >
        <div className="flex flex-wrap justify-end gap-2">
          {lidImporting ? (
            <Button
              onClick={() => void languageDetector.cancelInstall()}
              type="button"
              variant="secondary"
            >
              Cancel
            </Button>
          ) : languageDetector.view?.status === "ready" ? (
            <>
              <Button
                disabled={liveActive || languageDetector.action !== null}
                onClick={() => void languageDetector.verify()}
                type="button"
                variant="secondary"
              >
                Verify
              </Button>
              <Button
                disabled={liveActive || languageDetector.action !== null}
                onClick={() => void languageDetector.remove()}
                type="button"
                variant="secondary"
              >
                Remove
              </Button>
            </>
          ) : (
            <>
              <Button
                disabled={
                  liveActive || languageDetector.action !== null ||
                    languageDetector.view === null
                }
                onClick={() => void languageDetector.importModel()}
                type="button"
              >
                {languageDetector.view?.status === "corrupted" ? "Re-import" : "Import"}
              </Button>
              {languageDetector.view?.status === "corrupted" ? (
                <Button
                  disabled={liveActive || languageDetector.action !== null}
                  onClick={() => void languageDetector.remove()}
                  type="button"
                  variant="secondary"
                >
                  Remove
                </Button>
              ) : null}
            </>
          )}
        </div>
      </SettingsRow>
      <SettingsRow detail={vadDetail} label="Speech detection" value={vadValue}>
        <div className="flex flex-wrap justify-end gap-2">
          {vadInstalling ? (
            <Button onClick={() => void sileroVad.cancelInstall()} type="button" variant="secondary">
              Cancel
            </Button>
          ) : sileroVad.view?.status === "ready" ? (
            <>
              <Button
                disabled={liveActive || sileroVad.action !== null}
                onClick={() => void sileroVad.verify()}
                type="button"
                variant="secondary"
              >
                Verify
              </Button>
              <Button
                disabled={liveActive || sileroVad.action !== null}
                onClick={() => void sileroVad.remove()}
                type="button"
                variant="secondary"
              >
                Remove
              </Button>
            </>
          ) : (
            <>
              <Button
                disabled={liveActive || sileroVad.action !== null || sileroVad.view === null}
                onClick={() => void sileroVad.install()}
                type="button"
              >
                {sileroVad.view?.status === "corrupted" ? "Repair" : "Install"}
              </Button>
              {sileroVad.view?.status === "corrupted" ? (
                <Button
                  disabled={liveActive || sileroVad.action !== null}
                  onClick={() => void sileroVad.remove()}
                  type="button"
                  variant="secondary"
                >
                  Remove
                </Button>
              ) : null}
            </>
          )}
        </div>
      </SettingsRow>
      </AdvancedSettings>
    </SettingsGroup>
  );
}
