import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import {
  isHistoryBodySearchPending,
  projectHistorySearchDisplay,
} from "@/components/history/history-search";
import { visibleTranscriptChange } from "@/components/transcript-correction/transcript-correction-preview";
import { transcriptCorrectionIsActive } from "@/transcript-correction";

function cspSources(csp: string, directive: string) {
  const value = csp
    .split(";")
    .map((entry) => entry.trim())
    .find((entry) => entry.startsWith(`${directive} `));
  return value?.slice(directive.length + 1).trim().split(/\s+/) ?? [];
}

describe("product surface contracts", () => {
  it("does not report an empty history while transcript bodies are indexing", () => {
    expect(projectHistorySearchDisplay({ hasResults: false, indexingBodies: true }))
      .toBe("indexing");
    expect(projectHistorySearchDisplay({ hasResults: true, indexingBodies: true }))
      .toBe("results");
    expect(projectHistorySearchDisplay({ hasResults: false, indexingBodies: false }))
      .toBe("empty");
  });

  it("derives body-search pending synchronously from query and cache", () => {
    expect(isHistoryBodySearchPending({
      cachedOutputPaths: new Set(["one.txt"]),
      hasPreviewLoader: true,
      outputPaths: ["one.txt", "two.txt"],
      query: "spoken phrase",
    })).toBe(true);
    expect(isHistoryBodySearchPending({
      cachedOutputPaths: new Set(["one.txt", "two.txt"]),
      hasPreviewLoader: true,
      outputPaths: ["one.txt", "two.txt"],
      query: "spoken phrase",
    })).toBe(false);
    expect(isHistoryBodySearchPending({
      cachedOutputPaths: new Set(),
      hasPreviewLoader: true,
      outputPaths: ["one.txt"],
      query: "x",
    })).toBe(false);
  });

  it("classifies only server-owned in-flight correction states as active", () => {
    expect(transcriptCorrectionIsActive("queued")).toBe(true);
    expect(transcriptCorrectionIsActive("running")).toBe(true);
    expect(transcriptCorrectionIsActive("cancellation-requested")).toBe(true);
    expect(transcriptCorrectionIsActive("cancelled")).toBe(false);
    expect(transcriptCorrectionIsActive("complete")).toBe(false);
    expect(transcriptCorrectionIsActive("failed")).toBe(false);
  });

  it("marks the exact changed region while preserving shared source text", () => {
    expect(visibleTranscriptChange("Dose is twenty mg.", "Dose is 20 mg.")).toEqual({
      before: "Dose is ",
      original: "twenty",
      corrected: "20",
      after: " mg.",
    });
  });

  it("allows only the loopback media owner and removes the asset protocol", () => {
    const config = JSON.parse(readFileSync(
      new URL("../../src-tauri/tauri.conf.json", import.meta.url),
      "utf8",
    )) as {
      app: { security: { assetProtocol?: unknown; csp: string; devCsp?: string } };
      bundle: { resources: Record<string, string> };
    };
    const productionConnect = cspSources(config.app.security.csp, "connect-src");
    const developmentConnect = cspSources(config.app.security.devCsp ?? "", "connect-src");

    expect(productionConnect).toEqual([
      "'self'",
      "ipc:",
      "http://ipc.localhost",
      "https://ipc.localhost",
      "http://127.0.0.1:*",
    ]);
    expect(developmentConnect).toEqual(productionConnect);
    expect(cspSources(config.app.security.csp, "media-src")).toContain(
      "http://127.0.0.1:*",
    );
    expect(cspSources(config.app.security.csp, "form-action")).toEqual(["'none'"]);
    expect(cspSources(config.app.security.devCsp ?? "", "form-action")).toEqual(["'none'"]);
    expect(config.app.security.assetProtocol).toBeUndefined();
    expect(config.bundle.resources["../../THIRD_PARTY_NOTICES.md"])
      .toBe("THIRD_PARTY_NOTICES.md");
  });

  it("keeps renderer event authority listen-only in both application windows", () => {
    const readCapability = (name: string) => JSON.parse(readFileSync(
      new URL(`../../src-tauri/capabilities/${name}.json`, import.meta.url),
      "utf8",
    )) as { permissions: string[]; windows: string[] };
    const main = readCapability("default");
    const overlay = readCapability("live-overlay");

    expect(main.windows).toEqual(["main"]);
    expect(main.permissions).toEqual([
      "core:event:allow-listen",
      "core:event:allow-unlisten",
      "core:window:allow-close",
      "core:window:allow-minimize",
      "core:window:allow-start-dragging",
      "core:window:allow-toggle-maximize",
    ]);
    expect(overlay.windows).toEqual(["live-overlay"]);
    expect(overlay.permissions).toEqual([
      "core:event:allow-listen",
      "core:event:allow-unlisten",
    ]);
    expect([...main.permissions, ...overlay.permissions].some((permission) =>
      permission.includes("allow-emit") || permission.endsWith(":default"))).toBe(false);
  });
});
