import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { AuditorReportResult } from "@/components/auditor/auditor-report-result";
import { auditorStatusLine } from "@/components/auditor/use-auditor-report";
import {
  auditorReportIsActive,
  auditorReportStatus,
  cancelAuditorReport,
  startAuditorReport,
  type AuditorReportJobView,
} from "@/auditor";

const citation = (conceptId: string, text: string) => ({
  conceptId,
  sourceRevision: "revision-1",
  contentSha256: "d".repeat(64),
  charStart: 0,
  charEnd: [...text].length,
  text,
});

const completeView: AuditorReportJobView = {
  schemaVersion: 1,
  requestId: `auditor-report-${"1".repeat(32)}`,
  status: "complete",
  report: {
    schemaVersion: 1,
    generationSha256: "a".repeat(64),
    sourceAdmissionSha256: "b".repeat(64),
    evidenceSha256: "c".repeat(64),
    findings: [{
      kind: "potential-contradiction",
      summary: "These two current reviewed knowledge statements may conflict.",
      citations: [
        citation("limits/helios-five", "Helios release limit is five items."),
        citation("limits/helios-ten", "Helios release limit is ten items."),
      ],
      findingSha256: "e".repeat(64),
      requiresReview: true,
    }],
    citationSha256: "f".repeat(64),
    canonical: false,
    requiresReview: true,
    reportSha256: "1".repeat(64),
  },
};

describe("Auditor product contract", () => {
  beforeEach(() => invokeMock.mockReset().mockResolvedValue({}));

  it("routes audit focus through the native owner without renderer credentials", async () => {
    const requestId = completeView.requestId;
    await startAuditorReport("Helios release limit", 3, null);
    await auditorReportStatus(requestId);
    await cancelAuditorReport(requestId);

    expect(invokeMock.mock.calls).toEqual([
      ["start_auditor_report", {
        focus: "Helios release limit",
        maximumFindings: 3,
        expectedGenerationSha256: null,
      }],
      ["auditor_report_status", { requestId }],
      ["cancel_auditor_report", { requestId }],
    ]);
  });

  it("classifies only server-owned in-flight states as active", () => {
    for (const status of ["queued", "running", "cancellation-requested"] as const) {
      expect(auditorReportIsActive(status)).toBe(true);
    }
    for (const status of ["complete", "evidence-unavailable", "cancelled", "failed"] as const) {
      expect(auditorReportIsActive(status)).toBe(false);
    }
  });

  it("keeps hidden-only and absent evidence under one unavailable message", () => {
    for (const reason of ["empty-result", "evidence-unavailable"] as const) {
      expect(auditorStatusLine({
        available: true,
        starting: false,
        view: { ...completeView, status: "evidence-unavailable", report: null, reason },
      })).toBe("No permission-safe review finding is available for that focus.");
    }
  });

  it("renders only fixed review findings and exact citations", () => {
    const markup = renderToStaticMarkup(<AuditorReportResult report={completeView.report!} />);

    expect(markup).toContain("These two current reviewed knowledge statements may conflict.");
    expect(markup).toContain("limits/helios-five");
    expect(markup).toContain("limits/helios-ten");
    expect(markup).toContain("Review required · noncanonical");
    expect(markup).toContain("does not publish, activate, schedule, or modify");
    expect(markup).not.toContain(completeView.report!.reportSha256);
    expect(markup).not.toContain(completeView.report!.evidenceSha256);
  });
});
