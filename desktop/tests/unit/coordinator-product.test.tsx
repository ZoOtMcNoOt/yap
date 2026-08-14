import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { CoordinatorBundleResult } from "@/components/coordinator/coordinator-bundle-result";
import { coordinatorStatusLine } from "@/components/coordinator/use-coordinator-bundle";
import {
  cancelCoordinatorBundle,
  coordinatorBundleIsActive,
  coordinatorBundleStatus,
  startCoordinatorBundle,
  type CoordinatorBundleJobView,
} from "@/coordinator";

const completeView: CoordinatorBundleJobView = {
  schemaVersion: 1,
  requestId: `coordinator-bundle-${"1".repeat(32)}`,
  status: "complete",
  proposalBundle: {
    schemaVersion: 1,
    generationSha256: "a".repeat(64),
    evidenceSha256: "b".repeat(64),
    items: [{
      proposalId: "c".repeat(64),
      proposalType: "summary",
      proposedContent: "Coordinate the reviewed launch-readiness proposal.",
      citations: [{
        conceptId: "meetings/launch-review",
        sourceRevision: "revision-1",
        contentSha256: "d".repeat(64),
        charStart: 8,
        charEnd: 55,
        text: "The reviewed launch decision requires approval.",
      }],
      citationSha256: "e".repeat(64),
      candidateSha256: "f".repeat(64),
    }],
    bundleSha256: "1".repeat(64),
    citationSha256: "2".repeat(64),
    canonical: false,
    requiresReview: true,
  },
};

describe("Coordinator product contract", () => {
  beforeEach(() => invokeMock.mockReset().mockResolvedValue({}));

  it("routes objectives through the native owner without renderer credentials", async () => {
    const requestId = completeView.requestId;
    await startCoordinatorBundle("Coordinate reviewed proposals.", 3, null);
    await coordinatorBundleStatus(requestId);
    await cancelCoordinatorBundle(requestId);

    expect(invokeMock.mock.calls).toEqual([
      ["start_coordinator_bundle", {
        objective: "Coordinate reviewed proposals.",
        maximumItems: 3,
        expectedGenerationSha256: null,
      }],
      ["coordinator_bundle_status", { requestId }],
      ["cancel_coordinator_bundle", { requestId }],
    ]);
  });

  it("classifies only server-owned in-flight states as active", () => {
    for (const status of ["queued", "running", "cancellation-requested"] as const) {
      expect(coordinatorBundleIsActive(status)).toBe(true);
    }
    for (const status of ["complete", "evidence-unavailable", "cancelled", "failed"] as const) {
      expect(coordinatorBundleIsActive(status)).toBe(false);
    }
  });

  it("keeps hidden-only and absent evidence under one unavailable message", () => {
    for (const reason of ["empty-result", "evidence-unavailable"] as const) {
      expect(coordinatorStatusLine({
        available: true,
        starting: false,
        view: { ...completeView, status: "evidence-unavailable", proposalBundle: null, reason },
      })).toBe(
        "No permission-safe reviewed proposal bundle is available for that objective.",
      );
    }
  });

  it("renders only reviewed content and citations with the noncanonical boundary", () => {
    const markup = renderToStaticMarkup(
      <CoordinatorBundleResult bundle={completeView.proposalBundle!} />,
    );

    expect(markup).toContain("Coordinate the reviewed launch-readiness proposal.");
    expect(markup).toContain("meetings/launch-review");
    expect(markup).toContain("Review required · noncanonical");
    expect(markup).toContain("does not publish, activate, schedule, or modify");
    expect(markup).not.toContain(completeView.proposalBundle!.bundleSha256);
    expect(markup).not.toContain(completeView.proposalBundle!.evidenceSha256);
  });
});
