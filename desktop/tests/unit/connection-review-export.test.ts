import { beforeEach, expect, it, vi } from "vitest";
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
import { exportConnectionReviewPackage } from "@/knowledge-connections";
const proposalId = "d".repeat(64);
const generationSha256 = "a".repeat(64);
const receipt = () => ({ authorityRevision: "1", proposalId, generationSha256,
  result: { status: "saved", path: "/review/café.json" } });
const run = () => exportConnectionReviewPackage(proposalId, generationSha256, "1");
beforeEach(() => { invokeMock.mockReset(); });
it("sends only the displayed proposal, generation and connection authority", async () => {
  invokeMock.mockResolvedValue(receipt());
  expect(await run()).toEqual(receipt().result);
  expect(invokeMock).toHaveBeenCalledWith("export_connection_review_package", {
    proposalId, generationSha256, authorityRevision: "1",
  });
});
it("a foreign connection receipt cannot report a saved path", async () => {
  invokeMock.mockResolvedValue({ ...receipt(), authorityRevision: "2" });
  await expect(run()).rejects.toEqual({ code: "identityChanged" });
});
it("wrong proposal, generation and malformed saved results remain unconfirmed", async () => {
  for (const change of [
    { proposalId: "f".repeat(64) }, { generationSha256: "b".repeat(64) },
    { result: null }, { result: {status:"published"} },
    ...["", 42, "bad\0path", "x".repeat(32769)].map(path => ({result:{status:"saved",path}})),
  ]) {
    invokeMock.mockResolvedValue({...receipt(), ...change});
    await expect(run()).rejects.toEqual({code:"exportUnconfirmed"});
  }
});
it("picker cancellation and native destination refusal retain their distinct outcomes", async () => {
  invokeMock.mockResolvedValue({...receipt(),result:{status:"cancelled"}});
  expect(await run()).toEqual({status:"cancelled"});
  invokeMock.mockRejectedValue({code:"destinationExists"});
  await expect(run()).rejects.toEqual({code:"destinationExists"});
});
