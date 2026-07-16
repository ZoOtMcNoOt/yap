import { useEffect, useId, useMemo, useState } from "react";

import { SettingsRow } from "@/components/settings/settings-primitives";
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
import {
  fixedBatchLanguageOptions,
  initialPrimaryLanguageSelection,
  type FixedBatchLanguageOption,
  type PrimaryLanguageStatus,
} from "@/language-preference";

function displayLanguage(languageBcp47: string) {
  try {
    return new Intl.DisplayNames([navigator.language], { type: "language" }).of(languageBcp47)
      ?? languageBcp47;
  } catch {
    return languageBcp47;
  }
}

function qualityLabel(option: FixedBatchLanguageOption) {
  if (option.qualityTier === "broadCoverage") return "Broad coverage";
  if (option.qualityTier === "preview") return "Preview";
  return "Transcription ready";
}

function preferenceDetail(status: PrimaryLanguageStatus | null, error: string) {
  if (error) return error;
  if (!status) return "Checking the verified language catalog.";
  if (status.preferenceIssue === "incompatibleSchema") {
    return "This setting was written by a newer Yap version and was preserved unchanged.";
  }
  if (status.preferenceIssue === "invalidStoredPreference") {
    return "The saved setting is invalid. Confirm a current language to replace it safely.";
  }
  if (!status.capabilityCatalog) {
    return "Connect to a ready transcription server to load the current language list.";
  }
  if (status.confirmedLanguageAvailable === false) {
    return "The saved language is unavailable on the current server. Choose a supported replacement.";
  }
  if (status.requiresConfirmation && status.suggestedLanguageBcp47) {
    return "Suggested from this computer's locale. Yap will not save it until you confirm.";
  }
  if (status.requiresConfirmation) {
    return "Choose and confirm the default for short fixed-language recordings.";
  }
  return "Used for short fixed-language recordings. Per-recording choices never rewrite it.";
}

export function PrimaryLanguageSetting({
  error,
  onConfirm,
  pending,
  status,
}: {
  error: string;
  onConfirm: (languageBcp47: string) => void;
  pending: boolean;
  status: PrimaryLanguageStatus | null;
}) {
  const labelId = useId();
  const options = useMemo(
    () => fixedBatchLanguageOptions(status?.capabilityCatalog),
    [status?.capabilityCatalog],
  );
  const optionIds = useMemo(
    () => new Set(options.map((option) => option.languageBcp47)),
    [options],
  );
  const [selection, setSelection] = useState("");

  useEffect(() => {
    const initial = status ? initialPrimaryLanguageSelection(status) : null;
    setSelection(initial && optionIds.has(initial) ? initial : "");
  }, [optionIds, status]);

  const confirmed = status?.confirmedLanguageBcp47;
  const canConfirm = Boolean(
    selection &&
    status?.capabilityCatalog &&
    status.preferenceIssue !== "incompatibleSchema" &&
    (status.requiresConfirmation || selection !== confirmed || status.preferenceIssue),
  );
  const value = confirmed ? displayLanguage(confirmed) : "Not confirmed";

  return (
    <SettingsRow
      detail={preferenceDetail(status, error)}
      error={error || undefined}
      label="Primary language"
      value={value}
    >
      <div className="flex w-full max-w-[520px] flex-wrap justify-end gap-2">
        <Label className="sr-only" id={labelId}>
          Primary language
        </Label>
        <Select
          disabled={pending || !options.length || status?.preferenceIssue === "incompatibleSchema"}
          onValueChange={setSelection}
          value={selection}
        >
          <SelectTrigger aria-labelledby={labelId} className="min-w-[260px] flex-1">
            <SelectValue placeholder="Choose a language" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {options.map((option) => (
                <SelectItem key={option.languageBcp47} value={option.languageBcp47}>
                  {displayLanguage(option.languageBcp47)} · {qualityLabel(option)}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          disabled={pending || !canConfirm}
          onClick={() => onConfirm(selection)}
          type="button"
        >
          {status?.requiresConfirmation ? "Confirm" : "Save"}
        </Button>
      </div>
    </SettingsRow>
  );
}
