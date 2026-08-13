import { invoke } from "@tauri-apps/api/core";

export type LibrarianQueryStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "complete"
  | "evidence-unavailable"
  | "cancelled"
  | "failed";

export type LibrarianEvidenceItem = Readonly<{
  conceptId: string;
  sourceRevision: string;
  contentSha256: string;
  charStart: number;
  charEnd: number;
  text: string;
}>;

export type LibrarianEvidencePack = Readonly<{
  operation: "search";
  generationSha256: string;
  permissionHash: string;
  authorizationHash: string;
  evidenceSha256: string;
  items: readonly LibrarianEvidenceItem[];
  outputBudgetExhausted: boolean;
}>;

export type LibrarianQueryJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: LibrarianQueryStatus;
  evidencePack?: LibrarianEvidencePack | null;
  reason?: string | null;
}>;

export function startLibrarianQuery(
  searchText: string,
  maximumResults: number,
  expectedGenerationSha256: string | null,
) {
  return invoke<LibrarianQueryJobView>("start_librarian_query", {
    searchText,
    maximumResults,
    expectedGenerationSha256,
  });
}

export function librarianQueryStatus(requestId: string) {
  return invoke<LibrarianQueryJobView>("librarian_query_status", { requestId });
}

export function cancelLibrarianQuery(requestId: string) {
  return invoke<LibrarianQueryJobView>("cancel_librarian_query", { requestId });
}

export function librarianQueryIsActive(status: LibrarianQueryStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
