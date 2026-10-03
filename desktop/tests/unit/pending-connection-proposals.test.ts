import { beforeEach, expect, it, vi } from "vitest";
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
import { knowledgeConnections } from "@/knowledge-connections";

const entry = { proposalId: "d".repeat(64), createdAtUtc: "2026-10-03T12:00:00.123456Z" };
const receipt = () => ({
  authorityRevision: "1",
  response: { kind: "pending", value: { schemaVersion: 1, proposals: [entry] } },
});
beforeEach(() => invokeMock.mockReset());

it("discovers pending references with native authority and no owner selectors", async () => {
  invokeMock.mockResolvedValue(receipt());
  expect(await knowledgeConnections("id", { action: "pending" }, "1")).toEqual(receipt());
  expect(invokeMock).toHaveBeenCalledWith("knowledge_connections", {
    requestId: "id", request: { action: "pending" }, authorityRevision: "1",
  });
});

it("cannot attach a list to a changed connection or accept source inspection as discovery", async () => {
  invokeMock.mockResolvedValue({ ...receipt(), authorityRevision: "2" });
  await expect(knowledgeConnections("id", { action: "pending" }, "1"))
    .rejects.toEqual({ code: "identityChanged" });
  invokeMock.mockResolvedValue({ ...receipt(), response: { kind: "proposal", value: {} } });
  await expect(knowledgeConnections("id", { action: "pending" }, "1"))
    .rejects.toEqual({ code: "invalidResponse" });
});

it("refuses malformed, duplicate or excessive metadata instead of presenting a partial list", async () => {
  const page = receipt().response.value;
  for (const value of [
    { ...page, schemaVersion: 2 },
    { ...page, proposals: [entry, entry] },
    {
      ...page, proposals: Array.from({ length: 65 }, (_, index) => ({
        ...entry, proposalId: index.toString(16).padStart(64, "0"),
      }))
    },
    { ...page, proposals: [{ ...entry, proposalId: "invalid" }] },
    { ...page, proposals: [{ ...entry, createdAtUtc: "infinity" }] },
    { ...page, proposals: [{ ...entry, createdAtUtc: "2026-10-03T12:00:00+01:00" }] },
  ]) {
    invokeMock.mockResolvedValue({ ...receipt(), response: { kind: "pending", value } });
    await expect(knowledgeConnections("id", { action: "pending" }, "1"))
      .rejects.toEqual({ code: "invalidResponse" });
  }
});
