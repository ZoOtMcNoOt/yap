import { beforeEach, expect, it, vi } from "vitest";
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
import { knowledgeConnections } from "@/knowledge-connections";
const proposalId = "d".repeat(64);
const receipt = () => ({
  authorityRevision: "1",
  response: { kind: "discarded", value: {
    schemaVersion: 1, proposalId, generationSha256: "a".repeat(64), status: "discarded",
  } },
});
beforeEach(() => invokeMock.mockReset());
it("sends only the owned reference and native authority revision", async () => {
  invokeMock.mockResolvedValue(receipt());
  const result = await knowledgeConnections("request-id", { action: "discard", proposalId }, "1");
  expect(result).toEqual(receipt());
  expect(invokeMock).toHaveBeenCalledWith("knowledge_connections", {
    requestId: "request-id", request: { action: "discard", proposalId }, authorityRevision: "1",
  });
});
it("refuses a receipt belonging to a different connection or sign-in", async () => {
  invokeMock.mockResolvedValue({ ...receipt(), authorityRevision: "2" });
  await expect(knowledgeConnections("id", { action: "discard", proposalId }, "1"))
    .rejects.toEqual({ code: "identityChanged" });
});
it("cannot treat a proposal, foreign reference or malformed disposition as confirmed discard", async () => {
  for (const value of [
    { ...receipt(), response: { kind: "proposal", value: receipt().response.value } },
    { ...receipt(), response: { kind: "discarded", value: { ...receipt().response.value, proposalId: "f".repeat(64) } } },
    ...[{ status: "published" }, { schemaVersion: 2 }, { generationSha256: "invalid" }].map(change => ({
      ...receipt(), response: { kind: "discarded", value: { ...receipt().response.value, ...change } },
    })),
  ]) {
    invokeMock.mockResolvedValue(value);
    await expect(knowledgeConnections("id", { action: "discard", proposalId }, "1"))
      .rejects.toEqual({ code: "invalidResponse" });
  }
});
