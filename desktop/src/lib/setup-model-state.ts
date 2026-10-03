import {
  deriveSetupStateFromFallbackModel,
  type FallbackModelView,
} from "@/lib/setup-model";

export function fallbackStatusText(view: FallbackModelView, enabled: boolean) {
  switch (view.status) {
    case "downloading":
      return view.message ?? "Installing local fallback";
    case "verifying":
      return view.message ?? "Verifying local fallback";
    case "ready":
      return "Transcription engine ready";
    case "disabled":
      return "Local fallback disabled";
    case "error":
      return view.message ?? "Local fallback needs attention";
    case "missing":
    case "corrupted":
      return enabled ? "Local fallback model missing" : "Local fallback disabled";
  }
}

export type FallbackModelStateOverrides = {
  authText?: string;
  engineReady?: boolean;
  fallbackEnabled?: boolean;
  modelInstalled?: boolean;
  statusText?: string;
};

export function projectFallbackModelState({
  currentFallbackEnabled,
  currentModelInstalled,
  overrides = {},
  view,
}: {
  currentFallbackEnabled: boolean;
  currentModelInstalled: boolean;
  overrides?: FallbackModelStateOverrides;
  view: FallbackModelView;
}) {
  const fallbackEnabled = overrides.fallbackEnabled
    ?? (view.status === "ready" ? true : view.status === "disabled" ? false : currentFallbackEnabled);
  const modelInstalled = overrides.modelInstalled
    ?? (
      view.status === "ready" || view.status === "disabled" || view.status === "corrupted"
        ? true
        : view.status === "missing"
          ? false
          : currentModelInstalled
    );
  const engineReady = overrides.engineReady ?? view.status === "ready";
  const setupState = deriveSetupStateFromFallbackModel(view.status, fallbackEnabled);
  return {
    auth: overrides.authText ?? (engineReady ? "Ready" : "Setup"),
    engineReady,
    fallbackEnabled,
    modelInstalled,
    setupState,
    status: overrides.statusText ?? fallbackStatusText(view, fallbackEnabled),
  };
}
