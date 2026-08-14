import { invoke } from "@tauri-apps/api/core";

import type { LibrarianEvidenceItem } from "@/librarian";

export type CoordinatorBundleStatus =
  | "queued"
  | "running"
  | "cancellation-requested"
  | "complete"
  | "evidence-unavailable"
  | "cancelled"
  | "failed";

export type CoordinatorProposalBundleItem = Readonly<{
  proposalId: string;
  proposalType: "summary";
  proposedContent: string;
  citations: readonly LibrarianEvidenceItem[];
  citationSha256: string;
  candidateSha256: string;
}>;

export type CoordinatorProposalBundle = Readonly<{
  schemaVersion: 1;
  generationSha256: string;
  evidenceSha256: string;
  items: readonly CoordinatorProposalBundleItem[];
  bundleSha256: string;
  citationSha256: string;
  canonical: false;
  requiresReview: true;
}>;

export type CoordinatorBundleJobView = Readonly<{
  schemaVersion: 1;
  requestId: string;
  status: CoordinatorBundleStatus;
  proposalBundle?: CoordinatorProposalBundle | null;
  reason?: string | null;
}>;

export function startCoordinatorBundle(
  objective: string,
  maximumItems: number,
  expectedGenerationSha256: string | null,
) {
  return invoke<CoordinatorBundleJobView>("start_coordinator_bundle", {
    objective,
    maximumItems,
    expectedGenerationSha256,
  });
}

export function coordinatorBundleStatus(requestId: string) {
  return invoke<CoordinatorBundleJobView>("coordinator_bundle_status", { requestId });
}

export function cancelCoordinatorBundle(requestId: string) {
  return invoke<CoordinatorBundleJobView>("cancel_coordinator_bundle", { requestId });
}

export function coordinatorBundleIsActive(status: CoordinatorBundleStatus) {
  return status === "queued" || status === "running" || status === "cancellation-requested";
}
