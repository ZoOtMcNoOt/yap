import { describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import {
  generationReference,
  knowledgeRebuild,
  rebuildError,
  sameGeneration,
  type GenerationReceipt,
} from "../../src/knowledge-rebuild";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
const receipt: GenerationReceipt = {
  schemaVersion: 1,
  generationSha256: "a".repeat(64),
  sourceRevision: "reviewed-1",
  status: "staged",
  activeGenerationSha256: null,
  conceptCount: 2,
  chunkCount: 2,
  relationshipCount: 1,
  permissionCount: 2,
};
describe("reviewed rebuild decisions", () => {
  it("binds source identity and every descriptor count before publication", () => {
    expect(sameGeneration(receipt, { ...receipt, status: "retained" })).toBe(
      true,
    );
    for (const key of [
      "conceptCount",
      "chunkCount",
      "relationshipCount",
      "permissionCount",
    ] as const)
      expect(
        sameGeneration(receipt, { ...receipt, [key]: receipt[key] + 1 }),
      ).toBe(false);
    expect(
      sameGeneration(receipt, { ...receipt, sourceRevision: "other" }),
    ).toBe(false);
    expect(
      sameGeneration(receipt, { ...receipt, generationSha256: "b".repeat(64) }),
    ).toBe(false);
  });
  it("saved references cannot contain credentials, URLs, whitespace or shortened hashes", () => {
    expect(generationReference(receipt.generationSha256)).toBe(true);
    for (const value of [
      "",
      "a".repeat(63),
      "A".repeat(64),
      "https://private.example/",
      ` ${receipt.generationSha256}`,
    ])
      expect(generationReference(value)).toBe(false);
  });
  it("contains private error text while conservatively retaining uncertain delivery", () => {
    expect(
      rebuildError(new Error("private corpus and credentials")).unconfirmed,
    ).toBe(true);
    expect(
      rebuildError(new Error("private corpus and credentials")).message,
    ).not.toContain("private corpus");
    expect(
      rebuildError({ code: "knowledgeChanged", unconfirmed: false })
        .unconfirmed,
    ).toBe(false);
  });
  it("refuses a result bound to a different native account or generation", async () => {
    const request = {
      action: "inspect" as const,
      generationSha256: receipt.generationSha256,
    };
    vi.mocked(invoke).mockResolvedValueOnce({
      authorityRevision: "2",
      response: { kind: "generation", value: receipt },
    });
    await expect(knowledgeRebuild(request, "1")).rejects.toMatchObject({
      code: "invalidResponse",
      unconfirmed: false,
    });
    vi.mocked(invoke).mockResolvedValueOnce({
      authorityRevision: "1",
      response: {
        kind: "generation",
        value: { ...receipt, generationSha256: "b".repeat(64) },
      },
    });
    await expect(knowledgeRebuild(request, "1")).rejects.toMatchObject({
      code: "invalidResponse",
      unconfirmed: false,
    });
  });
  it("a malformed native write result leaves delivery unconfirmed", async () => {
    vi.mocked(invoke).mockResolvedValueOnce({
      authorityRevision: "1",
      response: { kind: "generation", value: receipt },
    });
    await expect(
      knowledgeRebuild(
        {
          action: "publish",
          generationSha256: receipt.generationSha256,
          expectedActiveGenerationSha256: null,
        },
        "1",
      ),
    ).rejects.toMatchObject({ code: "invalidResponse", unconfirmed: true });
  });
});
