import { invoke } from "@tauri-apps/api/core";

export type Sensitivity = "public" | "internal" | "confidential" | "restricted";
export type TerminologyScope = {
  scopeId: string;
  kind: "personal" | "team" | "organization";
  label: string;
  canManage: boolean;
};
export type Term = {
  scopeId: string;
  recordId: string;
  locale: string;
  canonicalForm: string;
  variants: string[];
  sensitivity: Sensitivity;
  version: number;
  changedAt: string;
};
export type TerminologyPage = {
  scopeId: string;
  records: Term[];
  nextCursor: string | null;
};
type Content = Pick<Term, "canonicalForm" | "variants" | "sensitivity">;
type ScopedRequest =
  | { action: "list"; locale: string; after: string | null }
  | { action: "read"; recordId: string }
  | ({ action: "create"; mutationId: string; locale: string } & Content)
  | ({ action: "edit"; recordId: string; expectedVersion: number } & Content)
  | { action: "delete"; recordId: string; expectedVersion: number };
export type TerminologyRequest =
  | { action: "discover" }
  | (ScopedRequest & { scopeId: string });
export type TerminologyResponse =
  | {
      kind: "scopes";
      value: { scopes: TerminologyScope[]; authorityRevision: string };
    }
  | { kind: "page"; value: TerminologyPage }
  | { kind: "record"; value: Term }
  | {
      kind: "deleted";
      value: {
        scopeId: string;
        recordId: string;
        version: number;
        deleted: true;
      };
    };

export async function terminology(
  request: TerminologyRequest,
  authorityRevision: string | null = null,
): Promise<TerminologyResponse> {
  const receipt = await invoke<{
    authorityRevision: string;
    response: TerminologyResponse;
  }>("terminology", {
    request,
    authorityRevision,
  });
  if (
    typeof receipt.authorityRevision !== "string" ||
    !receipt.authorityRevision
  )
    throw { code: "invalidResponse" };
  if (request.action === "discover") {
    if (receipt.response.kind !== "scopes") throw { code: "invalidResponse" };
    return {
      kind: "scopes",
      value: {
        ...receipt.response.value,
        authorityRevision: receipt.authorityRevision,
      },
    };
  }
  if (receipt.authorityRevision !== authorityRevision)
    throw { code: "identityChanged" };
  return receipt.response;
}

export function terminologyError(error: unknown) {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? error.code
      : "unavailable";
  switch (code) {
    case "conflict":
      return {
        conflict: true,
        message:
          "This term changed elsewhere. Your draft is kept; compare the latest version before saving.",
      };
    case "notFound":
      return {
        conflict: false,
        message:
          "This term was removed or is no longer available. Your draft is kept.",
      };
    case "identityChanged":
      return {
        conflict: false,
        message:
          "Your sign-in or server changed. Check System settings before retrying.",
      };
    case "denied":
      return {
        conflict: false,
        message:
          "Your organization has not granted access to change these terms.",
      };
    case "invalid":
      return {
        conflict: false,
        message:
          "Check the preferred spelling and variants. Each must be unique and no longer than 512 characters.",
      };
    case "invalidResponse":
      return {
        conflict: false,
        message:
          "The server returned an invalid terminology response. Your draft is kept.",
      };
    default:
      return {
        conflict: false,
        message:
          "Could not reach terminology. Your draft is kept; check the connection and retry.",
      };
  }
}
