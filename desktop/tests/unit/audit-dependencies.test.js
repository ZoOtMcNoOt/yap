import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import { parse as parseYaml } from "yaml";

import {
  auditDependencies,
  dependencyAuditRetryDelaysMs,
  dependencyAuditInvocation,
  isTransientDependencyAuditFailure,
  runPnpmDependencyAudit,
} from "../scripts/audit-dependencies.mjs";

const desktopRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

function auditResult(exitCode, output = "") {
  return { exitCode, output };
}

describe("dependency audit retry policy", () => {
  it("keeps patched transitive overrides exact without advisory exceptions", () => {
    const workspace = parseYaml(
      readFileSync(path.join(desktopRoot, "pnpm-workspace.yaml"), "utf8"),
    );

    expect(workspace.auditConfig).toBeUndefined();
    expect(workspace.overrides).toMatchObject({
      "brace-expansion@1": "1.1.18",
      "brace-expansion@2": "2.1.4",
      postcss: "8.5.23",
      "undici@6": "6.28.0",
      "undici@7": "7.29.0",
    });
  });

  it("passes a clean first attempt without waiting", async () => {
    const waits = [];
    const statuses = [];

    const result = await auditDependencies({
      runAudit: async () => auditResult(0),
      sleep: async (delayMs) => waits.push(delayMs),
      writeStatus: (status) => statuses.push(status),
    });

    expect(result).toEqual({ ok: true, attempts: 1, exitCode: 0 });
    expect(waits).toEqual([]);
    expect(statuses).toEqual(["DEPENDENCY_AUDIT=PASS attempts=1"]);
  });

  it("retries an audit registry 503 using the exact bounded schedule", async () => {
    const results = [
      auditResult(
        1,
        "[ERR_PNPM_AUDIT_BAD_RESPONSE] The audit endpoint responded with 503",
      ),
      auditResult(
        1,
        "POST https://registry.npmjs.org/-/npm/v1/security/advisories/bulk error (504)",
      ),
      auditResult(0),
    ];
    const waits = [];

    const result = await auditDependencies({
      runAudit: async () => results.shift(),
      retryDelaysMs: dependencyAuditRetryDelaysMs,
      sleep: async (delayMs) => waits.push(delayMs),
      writeStatus: () => {},
    });

    expect(dependencyAuditRetryDelaysMs).toEqual([10_000, 30_000, 60_000, 120_000]);
    expect(result).toEqual({ ok: true, attempts: 3, exitCode: 0 });
    expect(waits).toEqual([10_000, 30_000]);
  });

  it("retries pnpm's generic fetch failure before accepting a clean audit", async () => {
    const results = [
      auditResult(1, "[ERROR] fetch failed\n\nTypeError: fetch failed"),
      auditResult(0),
    ];
    const waits = [];

    const result = await auditDependencies({
      runAudit: async () => results.shift(),
      retryDelaysMs: [10_000],
      sleep: async (delayMs) => waits.push(delayMs),
      writeStatus: () => {},
    });

    expect(result).toEqual({ ok: true, attempts: 2, exitCode: 0 });
    expect(waits).toEqual([10_000]);
  });

  it("does not retry a vulnerability result or another non-transient failure", async () => {
    let attempts = 0;
    const waits = [];

    const result = await auditDependencies({
      runAudit: async () => {
        attempts += 1;
        return auditResult(1, "3 high severity vulnerabilities");
      },
      sleep: async (delayMs) => waits.push(delayMs),
      writeStatus: () => {},
    });

    expect(result).toEqual({ ok: false, attempts: 1, exitCode: 1 });
    expect(attempts).toBe(1);
    expect(waits).toEqual([]);
  });

  it("does not retry a signaled audit even when its output contains a network failure", async () => {
    let attempts = 0;
    const waits = [];

    const result = await auditDependencies({
      runAudit: async () => {
        attempts += 1;
        return {
          ...auditResult(1, "[ERROR] fetch failed"),
          signal: "SIGTERM",
        };
      },
      sleep: async (delayMs) => waits.push(delayMs),
      writeStatus: () => {},
    });

    expect(result).toEqual({ ok: false, attempts: 1, exitCode: 1 });
    expect(attempts).toBe(1);
    expect(waits).toEqual([]);
  });

  it("fails after exhausting the configured transient retries", async () => {
    let attempts = 0;
    const waits = [];

    const result = await auditDependencies({
      runAudit: async () => {
        attempts += 1;
        return auditResult(1, "503 Service Unavailable");
      },
      retryDelaysMs: [1, 2],
      sleep: async (delayMs) => waits.push(delayMs),
      writeStatus: () => {},
    });

    expect(result).toEqual({ ok: false, attempts: 3, exitCode: 1 });
    expect(attempts).toBe(3);
    expect(waits).toEqual([1, 2]);
  });

  it.each([
    "[ERR_PNPM_AUDIT_BAD_RESPONSE] audit endpoint responded with 503",
    "POST https://registry.npmjs.org/-/npm/v1/security/advisories/bulk error (502)",
    "request failed with ECONNRESET",
    "request failed with ETIMEDOUT",
    "request failed with EAI_AGAIN",
    "504 Gateway Timeout",
    "[ERROR] fetch failed",
    "TypeError: fetch failed",
  ])("recognizes a transient registry or network failure: %s", (output) => {
    expect(isTransientDependencyAuditFailure(output)).toBe(true);
  });

  it.each([
    "3 high severity vulnerabilities",
    "3 high severity vulnerabilities\n[ERROR] fetch failed",
    "2 vulnerabilities found\nSeverity: 2 high\n[ERROR] fetch failed",
    "SELF_SIGNED_CERT_IN_CHAIN",
    "ERR_PNPM_LOCKFILE_BREAKING_CHANGE",
    "503 high severity vulnerabilities",
  ])("does not classify a finding or configuration failure as transient: %s", (output) => {
    expect(isTransientDependencyAuditFailure(output)).toBe(false);
  });

  it("uses a shell only for the static Windows pnpm command", () => {
    expect(dependencyAuditInvocation("win32", "C:\\Windows\\System32\\cmd.exe")).toEqual({
      command: "C:\\Windows\\System32\\cmd.exe",
      args: ["/d", "/s", "/c", "pnpm audit --audit-level high"],
    });
    expect(dependencyAuditInvocation("linux")).toEqual({
      command: "pnpm",
      args: ["audit", "--audit-level", "high"],
    });
  });

  it("disables nested fetch retries in the spawned pnpm audit", async () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    let observed;

    const resultPromise = runPnpmDependencyAudit({
      environment: {
        EXISTING_VALUE: "preserved",
        PNPM_CONFIG_FETCH_RETRIES: "9",
      },
      platform: "linux",
      spawnProcess: (command, args, options) => {
        observed = { command, args, options };
        queueMicrotask(() => child.emit("close", 0, null));
        return child;
      },
      stdout: { write: () => {} },
      stderr: { write: () => {} },
    });

    await expect(resultPromise).resolves.toEqual({ exitCode: 0, output: "" });
    expect(observed.command).toBe("pnpm");
    expect(observed.args).toEqual(["audit", "--audit-level", "high"]);
    expect(observed.options.env).toMatchObject({
      EXISTING_VALUE: "preserved",
      pnpm_config_fetch_retries: "0",
    });
    expect(observed.options.env).not.toHaveProperty("PNPM_CONFIG_FETCH_RETRIES");
  });

  it("preserves a child termination signal for fail-closed retry policy", async () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();

    const resultPromise = runPnpmDependencyAudit({
      platform: "linux",
      spawnProcess: () => {
        queueMicrotask(() => child.emit("close", null, "SIGTERM"));
        return child;
      },
      stdout: { write: () => {} },
      stderr: { write: () => {} },
    });

    await expect(resultPromise).resolves.toEqual({
      exitCode: 1,
      output: "\nProcess signal: SIGTERM",
      signal: "SIGTERM",
    });
  });

});
