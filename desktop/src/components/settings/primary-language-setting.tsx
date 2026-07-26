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
import { formatLanguageTag, languageDisplayName } from "@/lib/language-display";

function qualityLabel(option: FixedBatchLanguageOption) {
  if (option.qualityTier === "broadCoverage") return "Broad coverage";
  if (option.qualityTier === "preview") return "Preview";
  return "Transcription ready";
}

function preferenceDetail(status: PrimaryLanguageStatus | null) {
  if (!status) return "Checking the verified language catalog.";
  if (status.preferenceIssue === "incompatibleSchema") {
    return "This setting was written by a newer Yap version and was preserved unchanged.";
  }
  if (status.preferenceIssue === "invalidStoredPreference") {
    return "The saved setting is invalid. Confirm a current language to replace it safely.";
  }
  if (!status.capabilityCatalog) {
    if (status.lastKnownCapabilities) {
      return "The server is unavailable. Its last verified language catalog is retained for explanation only; reconnect before choosing a language.";
    }
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
  const errorId = useId();
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
  const value = confirmed ? languageDisplayName(confirmed) : "Not confirmed";

  return (
    <SettingsRow
      detail={preferenceDetail(status)}
      error={error || undefined}
      errorId={errorId}
      label="Primary language"
      value={value}
    >
      <div className="flex w-full max-w-[520px] flex-wrap justify-start gap-2 md:justify-end">
        <Label className="sr-only" id={labelId}>
          Primary language
        </Label>
        <Select
          disabled={pending || !options.length || status?.preferenceIssue === "incompatibleSchema"}
          onValueChange={setSelection}
          value={selection}
        >
          <SelectTrigger
            aria-describedby={error ? errorId : undefined}
            aria-invalid={Boolean(error)}
            aria-labelledby={labelId}
            className="w-full min-w-0 sm:min-w-[260px] sm:flex-1"
          >
            <SelectValue placeholder="Choose a language" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {options.map((option) => (
                <SelectItem key={option.languageBcp47} value={option.languageBcp47}>
                  {formatLanguageTag(option.languageBcp47)} · {qualityLabel(option)}
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
