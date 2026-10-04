import { invoke } from "@tauri-apps/api/core";
import type { LibrarianEvidenceItem } from "@/librarian";

export type ConnectionProposal = {
  schemaVersion: 1;
  generationSha256: string;
  permissionHash: string;
  authorizationHash: string;
  proposalId: string;
  status: "proposed";
  candidate: {
    schemaVersion: 1;
    sourceConceptId: string;
    targetConceptId: string;
    relationshipType: string;
    rationale: string;
  };
  sources: {
    node: ConnectionNode;
    citation: Omit<LibrarianEvidenceItem, "text">;
    text: string;
  }[];
};

export type ConnectionProposalDisposition = {
  schemaVersion: 1;
  generationSha256: string;
  proposalId: string;
  status: "discarded";
};

export type PendingConnectionProposals = {
  schemaVersion: 1;
  proposals: { proposalId: string; createdAtUtc: string }[];
};

export type ConnectionNode = {
  conceptId: string;
  type: string;
  title: string;
  sourcePath: string;
  sourceRevision: string;
  contentSha256: string;
};
export type ConnectionRelationship = {
  relationshipId: string;
  sourceConceptId: string;
  targetConceptId: string;
  type: string;
  authority: "asserted" | "human_confirmed" | "derived";
  citation: {
    sourcePath: string;
    sourceRevision: string;
    contentSha256: string;
    charStart: number | null;
    charEnd: number | null;
  };
};
export type ConceptPage = {
  schemaVersion: 1;
  generationSha256: string;
  permissionHash: string;
  authorizationHash: string;
  nodes: ConnectionNode[];
  hasMore: boolean;
};
export type KnowledgeNeighborhood = ConceptPage & {
  conceptId: string;
  relationships: ConnectionRelationship[];
};
export type ConnectionsRequest =
  | { action: "pending" }
  | { action: "proposal"; proposalId: string }
  | { action: "discard"; proposalId: string }
  | { action: "browse"; search: string }
  | { action: "read"; conceptId: string; generationSha256: string };
export type ConnectionsResponse =
  | { kind: "pending"; value: PendingConnectionProposals }
  | { kind: "proposal"; value: ConnectionProposal }
  | { kind: "discarded"; value: ConnectionProposalDisposition }
  | { kind: "topics"; value: ConceptPage }
  | { kind: "neighborhood"; value: KnowledgeNeighborhood };
export type ConnectionsReceipt = {
  authorityRevision: string;
  response: ConnectionsResponse;
};
export async function knowledgeConnections(
  requestId: string,
  request: ConnectionsRequest,
  authorityRevision: string,
): Promise<ConnectionsReceipt> {
  const receipt = await invoke<ConnectionsReceipt>("knowledge_connections", {
    requestId,
    request,
    authorityRevision,
  });
  if (
    typeof receipt.authorityRevision !== "string" ||
    !receipt.authorityRevision ||
    authorityRevision !== receipt.authorityRevision
  )
    throw { code: "identityChanged" };
  if (
    receipt.response.kind !==
    (request.action === "pending"
      ? "pending"
      : request.action === "browse"
        ? "topics"
        : request.action === "proposal"
          ? "proposal"
          : request.action === "discard"
            ? "discarded"
            : "neighborhood") ||
    (request.action === "proposal" &&
      receipt.response.kind === "proposal" &&
      receipt.response.value.proposalId !== request.proposalId) ||
    (request.action === "discard" &&
      receipt.response.kind === "discarded" &&
      (receipt.response.value.proposalId !== request.proposalId ||
        receipt.response.value.schemaVersion !== 1 ||
        receipt.response.value.status !== "discarded" ||
        !/^[0-9a-f]{64}$/.test(receipt.response.value.generationSha256))) ||
    (request.action === "read" &&
      receipt.response.kind === "neighborhood" &&
      receipt.response.value.generationSha256 !== request.generationSha256)
  )
    throw { code: "invalidResponse" };
  if (receipt.response.kind === "pending") {
    const page = receipt.response.value;
    if (
      page.schemaVersion !== 1 ||
      !Array.isArray(page.proposals) ||
      page.proposals.length > 64 ||
      new Set(page.proposals.map((entry) => entry.proposalId)).size !== page.proposals.length ||
      page.proposals.some((entry) =>
        typeof entry.proposalId !== "string" || !/^[0-9a-f]{64}$/.test(entry.proposalId) ||
        typeof entry.createdAtUtc !== "string" || entry.createdAtUtc.length > 64 ||
        !entry.createdAtUtc.endsWith("Z") || !Number.isFinite(Date.parse(entry.createdAtUtc)),
      )
    ) throw { code: "invalidResponse" };
  }
  return receipt;
}
export function cancelKnowledgeConnections(requestId: string) {
  return invoke<void>("cancel_knowledge_connections", { requestId });
}
export type ConnectionReviewExport =
  | { status: "cancelled" }
  | { status: "saved"; path: string };
export async function exportConnectionReviewPackage(
  proposalId: string,
  generationSha256: string,
  authorityRevision: string,
): Promise<ConnectionReviewExport> {
  const receipt = await invoke<{
    authorityRevision: string;
    proposalId: string;
    generationSha256: string;
    result: ConnectionReviewExport;
  }>("export_connection_review_package", { proposalId, generationSha256, authorityRevision });
  if (!receipt || receipt.authorityRevision !== authorityRevision)
    throw { code: "identityChanged" };
  if (receipt.proposalId !== proposalId || receipt.generationSha256 !== generationSha256 ||
    !receipt.result ||
    (receipt.result.status !== "cancelled" && receipt.result.status !== "saved") ||
    (receipt.result.status === "saved" && (typeof receipt.result.path !== "string" ||
      !receipt.result.path.trim() || receipt.result.path.length > 32_768 || receipt.result.path.includes("\0"))))
    throw { code: "exportUnconfirmed" };
  return receipt.result;
}
export function connectionsError(error: unknown) {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? error.code
      : "unavailable";
  switch (code) {
    case "knowledgeChanged":
      return {
        clear: true,
        message:
          "Knowledge changed. Refresh topics to explore the current version.",
      };
    case "identityChanged":
      return {
        clear: true,
        message:
          "Your server or sign-in changed. Refresh topics after checking your connection.",
      };
    case "denied":
      return {
        clear: true,
        message:
          "Your organization has not granted access to these connections.",
      };
    case "notFound":
      return {
        clear: true,
        message:
          "This topic is no longer available. Refresh topics to continue.",
      };
    case "cancelled":
      return {
        clear: false,
        message: "Exploration cancelled. You can try again.",
      };
    case "invalidResponse":
      return {
        clear: true,
        message:
          "The server returned an inconsistent knowledge view. Refresh topics or check your server.",
      };
    case "invalid":
      return {
        clear: false,
        message: "Enter a topic search of up to 128 characters.",
      };
    default:
      return {
        clear: false,
        message:
          "Connections could not be loaded. Check your connection and try again.",
      };
  }
}
