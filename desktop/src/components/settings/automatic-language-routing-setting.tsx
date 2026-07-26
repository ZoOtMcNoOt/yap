import { useId } from "react";

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
import type { LiveLanguageRoutingControl } from "@/hooks/use-live-language-routing";
import { formatLanguageTag, languageDisplayName } from "@/lib/language-display";

const OFF_VALUE = "__off__";

function routingDetail(control: LiveLanguageRoutingControl, liveActive: boolean) {
  if (liveActive) return "Stop live before changing automatic languages.";
  const status = control.status;
  if (!status) return "Checking local language routing.";
  if (!status.primaryLanguageBcp47) {
    return "Confirm a primary language before configuring automatic switching.";
  }
  switch (status.preferenceIssue) {
    case "incompatibleSchema":
      return "A newer Yap version wrote this setting. It was preserved unchanged.";
    case "invalidStoredPreference":
      return "The saved choices are invalid. Turn off alternates, then choose again.";
    case "staleCatalog":
      return "Available language support changed. Review and save these choices again.";
    case null:
      return status.automaticLanguages.length
        ? "Preview: initial live text can wait for a 3-second language window, and AmberNet may miss or misclassify natural switches. Only explicitly selected locales receive automatic audio; ambiguous audio stays on your primary language."
        : "No automatic alternate is available for the current primary language.";
  }
}

export function AutomaticLanguageRoutingSetting({
  control,
  liveActive,
}: {
  control: LiveLanguageRoutingControl;
  liveActive: boolean;
}) {
  const labelPrefix = useId();
  const errorId = useId();
  const status = control.status;
  const locked = liveActive
    || control.pending
    || !status?.primaryLanguageBcp47
    || status.preferenceIssue === "incompatibleSchema";
  const selectedCount = status?.automaticLanguages.filter(
    (option) => option.selectedLocaleBcp47,
  ).length ?? 0;
  const availableCount = status?.automaticLanguages.length ?? 0;

  return (
    <SettingsRow
      action={status?.preferenceIssue && status.preferenceIssue !== "incompatibleSchema" ? (
        <Button
          disabled={locked}
          onClick={() => void control.reset().catch(() => undefined)}
          type="button"
          variant="secondary"
        >
          Turn off alternates
        </Button>
      ) : undefined}
      detail={routingDetail(control, liveActive)}
      error={control.error || undefined}
      errorId={errorId}
      label="Automatic alternate languages (Preview)"
      value={status ? `${selectedCount} of ${availableCount} selected` : "Checking"}
    >
      <div className="grid w-full max-w-[520px] gap-2 sm:grid-cols-2">
        {status?.automaticLanguages.map((option) => {
          const labelId = `${labelPrefix}-${option.languageCode}`;
          return (
            <div className="grid gap-1" key={option.languageCode}>
              <Label className="text-xs text-muted-foreground" id={labelId}>
                {languageDisplayName(option.languageCode)}
              </Label>
              <Select
                disabled={locked}
                onValueChange={(value) => {
                  void control
                    .update(option.languageCode, value === OFF_VALUE ? null : value)
                    .catch(() => undefined);
                }}
                value={option.selectedLocaleBcp47 ?? OFF_VALUE}
              >
                <SelectTrigger
                  aria-describedby={control.error ? errorId : undefined}
                  aria-invalid={Boolean(control.error)}
                  aria-labelledby={labelId}
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value={OFF_VALUE}>Off</SelectItem>
                    {option.locales.map((locale) => (
                      <SelectItem key={locale} value={locale}>
                        {formatLanguageTag(locale)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          );
        })}
      </div>
    </SettingsRow>
  );
}
