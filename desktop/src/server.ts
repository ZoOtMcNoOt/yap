import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

import type {
  ServerConnectionState,
} from "@/lib/setup-model";

export const SERVER_SETTINGS_SCHEMA_VERSION = 2 as const;

export type MicrosoftEntraSettings = {
  tenantId: string;
  clientId: string;
  apiScope: string;
};

export type ServerSettings = {
  schemaVersion: typeof SERVER_SETTINGS_SCHEMA_VERSION;
  enabled: boolean;
  baseUrl: string | null;
  authentication: MicrosoftEntraSettings | null;
};

export type ServerIdentityStatus = {
  configured: boolean;
  signedIn: boolean;
};

export type ServerCapabilities = {
  batchJobs: boolean;
  liveStreaming: boolean;
  jobStatus: boolean;
  transcriptCorrection: boolean;
  librarianQueries: boolean;
  archivistIngestions: boolean;
  studentQuestions: boolean;
  curatorProposals: boolean;
};

export type AsrExecutionMode =
  | "localLive"
  | "serverLive"
  | "fixedBatch"
  | "dynamicBatch";

export type AsrQualityTier = "transcriptionReady" | "broadCoverage" | "preview";

export type AsrCapability = {
  languageBcp47: string;
  providerLanguageCode: string;
  mode: AsrExecutionMode;
  qualityTier: AsrQualityTier;
  languageSuggestion: boolean;
  segmentLanguageTags: boolean;
  wordAlignment: boolean;
  promotionEvidenceRevision: string | null;
};

export type AsrProviderCapabilities = {
  providerId: string;
  poolId: string;
  modelId: string;
  modelRevision: string;
  modelLicense: string;
  modelSource: string;
  capabilities: AsrCapability[];
};

export type AsrCapabilityCatalog = {
  schemaVersion: 1;
  catalogRevision: string;
  providers: AsrProviderCapabilities[];
};

export type ServerConnectionSnapshot = {
  state: ServerConnectionState;
  checkedAtMs: number | null;
  retryAtMs: number | null;
  apiVersion: string | null;
  capabilities: ServerCapabilities;
  errorCode: string | null;
};

export function serverCanRouteImportedRecording(
  snapshot: ServerConnectionSnapshot | null | undefined,
) {
  return snapshot?.state === "ready" && snapshot.capabilities?.batchJobs === true;
}

export function serverCanRouteLive(snapshot: ServerConnectionSnapshot | null | undefined) {
  return snapshot?.state === "ready" && snapshot.capabilities?.liveStreaming === true;
}

export function catalogSupportsMode(
  catalog: AsrCapabilityCatalog | null | undefined,
  languageBcp47: string,
  mode: AsrExecutionMode,
) {
  return catalog?.providers.some((provider) =>
    provider.capabilities.some((capability) =>
      capability.languageBcp47 === languageBcp47 && capability.mode === mode)) ?? false;
}

export function serverConnectionStatus(): Promise<ServerConnectionSnapshot> {
  return invoke<ServerConnectionSnapshot>("server_connection_status");
}

export function refreshServerConnection(): Promise<ServerConnectionSnapshot> {
  return invoke<ServerConnectionSnapshot>("refresh_server_connection");
}

export function serverAsrCapabilities(): Promise<AsrCapabilityCatalog | null> {
  return invoke<AsrCapabilityCatalog | null>("server_asr_capabilities");
}

export async function listenServerConnection(
  onUpdate: (snapshot: ServerConnectionSnapshot) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return listen<ServerConnectionSnapshot>("server-connection", (event) => onUpdate(event.payload));
}

export type LocalServerOffer = {
  baseUrl: string;
  authRequired: boolean;
};

export function probeLocalServer(): Promise<LocalServerOffer | null> {
  return invoke<LocalServerOffer | null>("probe_local_server");
}

export function serverSettings(): Promise<ServerSettings> {
  return invoke<ServerSettings>("server_settings");
}

export function saveServerSettings(settings: ServerSettings): Promise<ServerSettings> {
  return invoke<ServerSettings>("set_server_settings", { settings });
}

export function serverIdentityStatus(): Promise<ServerIdentityStatus> {
  return invoke<ServerIdentityStatus>("server_identity_status");
}

export function signInToServer(): Promise<ServerIdentityStatus> {
  return invoke<ServerIdentityStatus>("sign_in_to_server");
}

export function signOutOfServer(): Promise<ServerIdentityStatus> {
  return invoke<ServerIdentityStatus>("sign_out_of_server");
}

export async function testServerConnection(): Promise<ServerConnectionState> {
  return (await refreshServerConnection()).state;
}
