import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { LibrarianEvidenceResults } from "@/components/librarian/librarian-evidence-results";
import { librarianStatusLine } from "@/components/librarian/use-librarian-query";
import { LibrarianPanel } from "@/components/panels/librarian-panel";
import {
  cancelLibrarianQuery,
  librarianQueryIsActive,
  librarianQueryStatus,
  startLibrarianQuery,
  type LibrarianEvidencePack,
} from "@/librarian";

const pack: LibrarianEvidencePack = {
  operation: "search",
  generationSha256: "a".repeat(64),
  permissionHash: "b".repeat(64),
  authorizationHash: "c".repeat(64),
  evidenceSha256: "d".repeat(64),
  items: [
    {
      conceptId: "meetings/launch-review",
      sourceRevision: "revision-1",
      contentSha256: "e".repeat(64),
      charStart: 8,
      charEnd: 55,
      text: "The reviewed launch decision requires approval.",
    },
  ],
  outputBudgetExhausted: false,
};

describe("Librarian product contract", () => {
  beforeEach(() => invokeMock.mockReset().mockResolvedValue({}));

  it("routes every query through the native owner without renderer credentials", async () => {
    await startLibrarianQuery("reviewed launch decision", 3, null);
    await librarianQueryStatus(`librarian-query-${"1".repeat(32)}`);
    await cancelLibrarianQuery(`librarian-query-${"1".repeat(32)}`);

    expect(invokeMock.mock.calls).toEqual([
      ["start_librarian_query", {
        searchText: "reviewed launch decision",
        maximumResults: 3,
        expectedGenerationSha256: null,
      }],
      ["librarian_query_status", { requestId: `librarian-query-${"1".repeat(32)}` }],
      ["cancel_librarian_query", { requestId: `librarian-query-${"1".repeat(32)}` }],
    ]);
  });

  it("classifies only server-owned in-flight states as active", () => {
    for (const status of ["queued", "running", "cancellation-requested"] as const) {
      expect(librarianQueryIsActive(status)).toBe(true);
    }
    for (const status of ["complete", "evidence-unavailable", "cancelled", "failed"] as const) {
      expect(librarianQueryIsActive(status)).toBe(false);
    }
  });

  it("keeps hidden-only and absent results under one public unavailable message", () => {
    for (const reason of ["empty-result", "evidence-unavailable"] as const) {
      expect(librarianStatusLine({
        available: true,
        starting: false,
        view: {
          schemaVersion: 1,
          requestId: `librarian-query-${"1".repeat(32)}`,
          status: "evidence-unavailable",
          evidencePack: null,
          reason,
        },
      })).toBe("No permission-safe evidence is available for that query.");
    }
  });

  it("renders only permission-safe evidence and source-bound citation labels", () => {
    const markup = renderToStaticMarkup(<LibrarianEvidenceResults pack={pack} />);

    expect(markup).toContain("The reviewed launch decision requires approval.");
    expect(markup).toContain("meetings/launch-review");
    expect(markup).toContain("revision-1");
    expect(markup).toContain("characters 8–55");
    expect(markup).not.toContain(pack.permissionHash);
    expect(markup).not.toContain(pack.authorizationHash);
  });

  it("keeps local controls available when organization knowledge is unavailable", () => {
    const markup = renderToStaticMarkup(<LibrarianPanel available={false} />);

    expect(markup).toContain("Knowledge search needs your connected organization server");
    expect(markup).toContain("Local recording, playback, transcripts, export, and deletion remain available.");
    expect(markup).toContain("Search knowledge");
    expect(markup).toContain("disabled");
    expect(markup).not.toContain("chat");
  });
});
