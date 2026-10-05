import { invoke } from "@tauri-apps/api/core";
export type GenerationReceipt = {
  schemaVersion: 1;
  generationSha256: string;
  sourceRevision: string;
  status: "staged" | "active" | "retained";
  activeGenerationSha256: string | null;
  conceptCount: number;
  chunkCount: number;
  relationshipCount: number;
  permissionCount: number;
};
export type SourceReceipt = Omit<GenerationReceipt, "status"> & {
  sourcePath: string;
  status: GenerationReceipt["status"] | "unadmitted";
  changed?: boolean;
};
export type EmbeddingReceipt = {
  schemaVersion: 1;
  generationSha256: string;
  status: "prepared";
  chunkCount: number;
  embeddingModelId: string;
  embeddingModelRevision: string;
  changed: boolean;
};
export type ActivationReceipt = GenerationReceipt & {
  status: "active";
  changed: boolean;
  previousActiveGenerationSha256: string | null;
};
export type ActivationRequest = {
  action: "publish" | "restore";
  generationSha256: string;
  expectedActiveGenerationSha256: string | null;
};
export type RebuildRequest =
  | { action: "source" }
  | { action: "stage" | "embeddings" | "inspect"; generationSha256: string }
  | ActivationRequest;
export type RebuildResponse =
  | { kind: "source"; value: SourceReceipt }
  | { kind: "staged"; value: SourceReceipt }
  | { kind: "prepared"; value: EmbeddingReceipt }
  | { kind: "generation"; value: GenerationReceipt }
  | { kind: "activated"; value: ActivationReceipt };
export const generationReference = (value: string) =>
  /^[a-f0-9]{64}$/.test(value);
export function sameGeneration(
  a: GenerationReceipt | SourceReceipt,
  b: GenerationReceipt | SourceReceipt,
) {
  return (
    [
      "generationSha256",
      "sourceRevision",
      "conceptCount",
      "chunkCount",
      "relationshipCount",
      "permissionCount",
    ] as const
  ).every((key) => a[key] === b[key]);
}
export async function knowledgeRebuild(
  request: RebuildRequest,
  authorityRevision: string,
): Promise<RebuildResponse> {
  const result = await invoke<{
    authorityRevision: string;
    response: RebuildResponse;
  }>("knowledge_rebuild", { request, authorityRevision });
  const expected = {
    source: "source",
    stage: "staged",
    embeddings: "prepared",
    inspect: "generation",
    publish: "activated",
    restore: "activated",
  }[request.action];
  if (
    result?.authorityRevision !== authorityRevision ||
    result.response?.kind !== expected ||
    (request.action !== "source" &&
      result.response.value.generationSha256 !== request.generationSha256)
  )
    throw {
      code: "invalidResponse",
      unconfirmed: request.action !== "source" && request.action !== "inspect",
    };
  return result.response;
}
export function rebuildError(error: unknown) {
  const value =
    typeof error === "object" && error !== null
      ? (error as { code?: string; unconfirmed?: boolean })
      : {};
  const messages: Record<string, string> = {
    denied: "Your organization has not granted this reviewer action.",
    identityChanged:
      "Your server or sign-in changed. Inspect again before continuing.",
    unavailable:
      "The reviewed source or embedding service is unavailable. Check its organization configuration, then inspect again.",
    notFound:
      "This generation is unavailable, pruned or not admitted by you. Inspect another saved reference.",
    knowledgeChanged:
      "Knowledge changed or could not pass the service checks. Inspect again and make a new decision.",
    invalidResponse:
      "The reply could not be verified. Inspect again before continuing.",
    busy: "Another rebuild request is still finishing. Wait before continuing.",
    invalid:
      "The generation reference is invalid. Use the exact saved reference.",
  };
  const code =
    typeof value.code === "string" && Object.prototype.hasOwnProperty.call(messages, value.code)
      ? value.code
      : "unknown";
  return {
    code,
    message:
      messages[code] ??
      "The request did not return a verified result. Inspect again before continuing.",
    unconfirmed: value.unconfirmed !== false,
  };
}
