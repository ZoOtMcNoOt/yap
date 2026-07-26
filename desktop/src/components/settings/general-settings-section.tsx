import { Microphone as Mic } from "@phosphor-icons/react/Microphone";
import { useId } from "react";

import { ShortcutRecorder } from "@/components/settings/shortcut-recorder";
import { PrimaryLanguageSetting } from "@/components/settings/primary-language-setting";
import { AutomaticLanguageRoutingSetting } from "@/components/settings/automatic-language-routing-setting";
import { SettingsGroup, SettingsRow } from "@/components/settings/settings-primitives";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  liveStatusLabel,
  type LiveCaptureMode,
  type LiveInputDeviceView,
  type LiveSessionView,
} from "@/lib/live-session";
import type { PrimaryLanguageStatus } from "@/language-preference";
import type { LiveLanguageRoutingControl } from "@/hooks/use-live-language-routing";

type LiveOverlayAction = {
  disabled: boolean;
  label: string;
};

export function GeneralSettingsSection({
  liveActive,
  liveBusy,
  liveInputDevices,
  liveLanguageRouting,
  liveOverlayAction,
  liveSettingsError,
  liveView,
  onPreflightLiveInput,
  onConfirmPrimaryLanguage,
  onResetLiveHotkey,
  onResetLivePasteHotkey,
  onSetInputDevice,
  onSetLiveCaptureMode,
  onSetLiveHotkey,
  onSetLiveOverlayEnabled,
  onSetLivePasteHotkey,
  onStartLive,
  onStopLive,
  primaryLanguageError,
  primaryLanguagePending,
  primaryLanguageStatus,
}: {
  liveActive: boolean;
  liveBusy: boolean;
  liveInputDevices: LiveInputDeviceView[];
  liveLanguageRouting: LiveLanguageRoutingControl;
  liveOverlayAction: LiveOverlayAction;
  liveSettingsError: string;
  liveView: LiveSessionView;
  onPreflightLiveInput: () => void;
  onConfirmPrimaryLanguage: (languageBcp47: string) => void;
  onResetLiveHotkey: () => void;
  onResetLivePasteHotkey: () => void;
  onSetInputDevice: (deviceId?: string) => void;
  onSetLiveCaptureMode: (captureMode: LiveCaptureMode) => void;
  onSetLiveHotkey: () => void;
  onSetLiveOverlayEnabled: (enabled: boolean) => void;
  onSetLivePasteHotkey: () => void;
  onStartLive: () => void;
  onStopLive: () => void;
  primaryLanguageError: string;
  primaryLanguagePending: boolean;
  primaryLanguageStatus: PrimaryLanguageStatus | null;
}) {
  const micLabelId = useId();
  const modeLabelId = useId();

  return (
    <SettingsGroup>
      <PrimaryLanguageSetting
        error={primaryLanguageError}
        onConfirm={onConfirmPrimaryLanguage}
        pending={primaryLanguagePending}
        status={primaryLanguageStatus}
      />
      <AutomaticLanguageRoutingSetting
        control={liveLanguageRouting}
        liveActive={liveActive}
      />
      <SettingsRow
        detail={liveActive ? "Stop live first." : "Hold for push-to-talk or double-tap for hands-free."}
        label="Dictation shortcut"
        value={liveView.hotkey || "Off"}
      >
        <ShortcutRecorder
          disabled={liveBusy || liveActive}
          onRecord={onSetLiveHotkey}
          onReset={onResetLiveHotkey}
        />
      </SettingsRow>
      <SettingsRow
        detail={liveActive ? "Stop live first." : "Copies the last transcript after a deliberate shortcut chord."}
        label="Paste-last shortcut"
        value={liveView.pasteHotkey || "Off"}
      >
        <ShortcutRecorder
          disabled={liveBusy || liveActive}
          onRecord={onSetLivePasteHotkey}
          onReset={onResetLivePasteHotkey}
        />
      </SettingsRow>
      <SettingsRow
        detail="Moves keyboard focus into the always-on-top overlay without starting or stopping dictation."
        label="Overlay controls shortcut"
        value={liveView.overlayFocusHotkey || "Unavailable"}
      />
      <SettingsRow
        action={(
          <Button
            disabled={liveBusy || liveActive}
            onClick={onPreflightLiveInput}
            type="button"
            variant="secondary"
          >
            Check
          </Button>
        )}
        detail={liveActive ? "Stop live before changing microphones." : "Auto falls back to the system default."}
        label="Microphone"
        value={liveView.inputDeviceLabel || "System default"}
      >
        <Select
          disabled={liveBusy || liveActive}
          onValueChange={(value) => onSetInputDevice(value === "default" ? undefined : value)}
          value={liveView.inputDeviceId ?? "default"}
        >
          <SelectTrigger aria-labelledby={micLabelId} className="w-full max-w-[340px]">
            <SelectValue placeholder="System default" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="default">System default</SelectItem>
              {liveInputDevices.map((device) => (
                <SelectItem key={device.id} value={device.id}>
                  {device.label}{device.isDefault ? " (default)" : ""}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </SettingsRow>
      <SettingsRow
        detail={liveActive ? "Stop live before changing mode." : "Hold for push-to-talk, toggle for hands-free."}
        label="Mode"
        value={liveView.captureMode === "pushToTalk" ? "Hold" : "Toggle"}
      >
        <Label className="sr-only" id={modeLabelId}>
          Mode
        </Label>
        <ToggleGroup
          aria-labelledby={modeLabelId}
          className="grid max-w-[260px] grid-cols-2"
          disabled={liveBusy || liveActive}
          onValueChange={(value) => {
            if (value) onSetLiveCaptureMode(value as LiveCaptureMode);
          }}
          type="single"
          value={liveView.captureMode}
        >
          <ToggleGroupItem value="pushToTalk">Hold</ToggleGroupItem>
          <ToggleGroupItem value="toggle">Toggle</ToggleGroupItem>
        </ToggleGroup>
      </SettingsRow>
      <SettingsRow
        action={(
          <Button
            disabled={liveOverlayAction.disabled}
            onClick={liveActive ? onStopLive : onStartLive}
            type="button"
          >
            <Mic data-icon="inline-start" />
            {liveOverlayAction.label}
          </Button>
        )}
        detail={liveView.error || liveSettingsError || "Small overlay stays available for live dictation."}
        label="Overlay"
        value={liveStatusLabel(liveView.status)}
      >
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={liveBusy || liveActive}
            onClick={() => onSetLiveOverlayEnabled(liveView.visibility === "hidden")}
            type="button"
            variant="secondary"
          >
            {liveView.visibility === "hidden" ? "Show" : "Hide"}
          </Button>
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}
