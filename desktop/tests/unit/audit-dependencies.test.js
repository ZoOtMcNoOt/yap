import { EventEmitter } from "node:events";

import { describe, expect, it } from "vitest";

import {
  auditDependencies,
  dependencyAuditRetryDelaysMs,
  dependencyAuditInvocation,
  isTransientDependencyAuditFailure,
  runPnpmDependencyAudit,
} from "../scripts/audit-dependencies.mjs";

function auditResult(exitCode, output = "") {
  return { exitCode, output };
}

describe("dependency audit retry policy", () => {
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
  ])("recognizes a transient registry or network failure: %s", (output) => {
    expect(isTransientDependencyAuditFailure(output)).toBe(true);
  });

  it.each([
    "3 high severity vulnerabilities",
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
      environment: { EXISTING_VALUE: "preserved" },
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
  });
});
