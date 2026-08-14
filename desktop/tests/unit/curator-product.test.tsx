import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { CuratorProposalResult } from "@/components/curator/curator-proposal-result";
import { curatorStatusLine } from "@/components/curator/use-curator-proposal";
import {
  cancelCuratorProposal,
  curatorProposalIsActive,
  curatorProposalStatus,
  startCuratorProposal,
  type CuratorProposalJobView,
} from "@/curator";
import type { StudentQuestion } from "@/student";

const generationSha256 = "a".repeat(64);
const studentQuestion: StudentQuestion = {
  schemaVersion: 3,
  sourceSubject: "crash containment",
  question: "What should you remember about crash containment?",
  sourceSupports: [{
    sourceCitation: {
      conceptId: "meetings/launch-review",
      sourceRevision: "b".repeat(64),
      contentSha256: "c".repeat(64),
      charStart: 0,
      charEnd: 70,
    },
    supportQuote: "crash containment",
    supportCharStart: 20,
    supportCharEnd: 37,
  }],
};

const proposedView: CuratorProposalJobView = {
  schemaVersion: 1,
  requestId: `curator-proposal-${"1".repeat(32)}`,
  submissionId: "curator-native-1",
  status: "proposed",
  generationSha256,
  evidenceSha256: "d".repeat(64),
  proposalId: "e".repeat(64),
  reason: null,
};

describe("Curator product contract", () => {
  beforeEach(() => invokeMock.mockReset().mockResolvedValue({}));

  it("routes reviewed Student answers through the native owner without renderer credentials", async () => {
    const requestId = proposedView.requestId;
    await startCuratorProposal(generationSha256, "Contain the worker before retrying.", studentQuestion);
    await curatorProposalStatus(requestId);
    await cancelCuratorProposal(requestId);

    expect(invokeMock.mock.calls).toEqual([
      ["start_curator_proposal", {
        expectedGenerationSha256: generationSha256,
        reviewedContent: "Contain the worker before retrying.",
        studentQuestion,
      }],
      ["curator_proposal_status", { requestId }],
      ["cancel_curator_proposal", { requestId }],
    ]);
  });

  it("classifies only server-owned in-flight states as active", () => {
    for (const status of ["queued", "running", "cancellation-requested"] as const) {
      expect(curatorProposalIsActive(status)).toBe(true);
    }
    for (const status of ["proposed", "rejected", "cancelled", "failed"] as const) {
      expect(curatorProposalIsActive(status)).toBe(false);
    }
  });

  it("keeps proposal and rejection status explicit and noncanonical", () => {
    expect(curatorStatusLine({ available: true, starting: false, view: proposedView }))
      .toBe("A noncanonical proposal is ready for review.");
    expect(curatorStatusLine({
      available: true,
      starting: false,
      view: { ...proposedView, status: "rejected", proposalId: null, reason: "model-rejected" },
    })).toBe("Curator found the reviewed answer unsupported by its cited source.");
  });

  it("renders review-required success without authority hashes or activation claims", () => {
    const markup = renderToStaticMarkup(<CuratorProposalResult view={proposedView} />);

    expect(markup).toContain("Proposal created");
    expect(markup).toContain("Requires review");
    expect(markup).toContain("has not changed organizational knowledge");
    expect(markup).not.toContain(generationSha256);
    expect(markup).not.toContain(proposedView.evidenceSha256!);
    expect(markup).not.toContain(proposedView.proposalId!);
  });
});
