import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// The provenance release contract verifies these hashes, but it lives in the
// CI-only contract suite — so editing a ported file without rebinding its
// manifest hash sailed through the fast local loop (tsc, unit, e2e all green)
// and reached CI three separate times. This mirror puts the same local-hash
// check in the sub-second suite every change runs.
const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");
const manifest = JSON.parse(
  readFileSync(path.join(repoRoot, "THIRD_PARTY_PROVENANCE.json"), "utf8"),
) as {
  sources: Array<{ id: string; files?: Array<{ path: string; sha256?: string }> }>;
};

describe("third-party provenance local hashes", () => {
  const pinned = manifest.sources.flatMap((source) =>
    (source.files ?? []).flatMap((file) => (file.sha256 ? [file] : [])));

  it("tracks at least the FreeFlow port set", () => {
    expect(pinned.length).toBeGreaterThanOrEqual(3);
  });

  for (const file of pinned) {
    it(`${file.path} matches its manifest hash`, () => {
      const digest = createHash("sha256")
        .update(readFileSync(path.join(repoRoot, file.path)))
        .digest("hex");
      expect(
        digest,
        `${file.path} changed; rebind its sha256 in THIRD_PARTY_PROVENANCE.json`,
      ).toBe(file.sha256);
    });
  }
});
