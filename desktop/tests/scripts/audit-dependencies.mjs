import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

export const dependencyAuditRetryDelaysMs = Object.freeze([
  10_000,
  30_000,
  60_000,
  120_000,
]);

const maxCapturedOutputCharacters = 256 * 1024;
const developmentOnlyAuditExceptionPackages = Object.freeze([
  "brace-expansion",
]);
const transientAuditFailurePatterns = [
  /\bERR_PNPM_AUDIT_BAD_RESPONSE\b/i,
  /\bERR_PNPM_FETCH_(?:502|503|504)\b/i,
  /\b(?:ECONNRESET|ETIMEDOUT|EAI_AGAIN|ECONNREFUSED|ENETUNREACH|EHOSTUNREACH|UND_ERR_CONNECT_TIMEOUT|UND_ERR_SOCKET)\b/i,
  /\b(?:502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout)\b/i,
  /\b(?:audit endpoint|security\/(?:advisories\/bulk|audits))\b[^\r\n]{0,200}\b(?:502|503|504)\b/i,
  /\bPOST https?:\/\/[^\s]+\/-\/npm\/v1\/security\/advisories\/bulk error \((?:502|503|504)\)/i,
];

function appendBoundedOutput(current, chunk) {
  const combined = current + chunk.toString();
  return combined.length <= maxCapturedOutputCharacters
    ? combined
    : combined.slice(-maxCapturedOutputCharacters);
}

function wait(delayMs) {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

export function isTransientDependencyAuditFailure(output) {
  return transientAuditFailurePatterns.some((pattern) => pattern.test(output));
}

export function dependencyAuditInvocation(
  platform = process.platform,
  commandInterpreter = process.env.ComSpec,
) {
  if (platform === "win32") {
    return {
      command: commandInterpreter || "cmd.exe",
      args: ["/d", "/s", "/c", "pnpm audit --audit-level high"],
    };
  }

  return {
    command: "pnpm",
    args: ["audit", "--audit-level", "high"],
  };
}

export function productionDependencyWhyInvocation(
  platform = process.platform,
  commandInterpreter = process.env.ComSpec,
) {
  const args = [
    "why",
    "--prod",
    ...developmentOnlyAuditExceptionPackages,
    "--json",
  ];

  if (platform === "win32") {
    return {
      command: commandInterpreter || "cmd.exe",
      args: ["/d", "/s", "/c", `pnpm ${args.join(" ")}`],
    };
  }

  return {
    command: "pnpm",
    args,
  };
}

function runPnpmCommand({
  invocation,
  environment,
  spawnProcess,
  stdout,
  stderr,
}) {
  return new Promise((resolve) => {
    let capturedOutput = "";
    let settled = false;
    const child = spawnProcess(invocation.command, invocation.args, {
      cwd: process.cwd(),
      env: environment,
      stdio: ["inherit", "pipe", "pipe"],
      windowsHide: true,
    });

    const capture = (destination, chunk) => {
      capturedOutput = appendBoundedOutput(capturedOutput, chunk);
      destination.write(chunk);
    };

    child.stdout.on("data", (chunk) => capture(stdout, chunk));
    child.stderr.on("data", (chunk) => capture(stderr, chunk));
    child.once("error", (error) => {
      if (settled) return;
      settled = true;
      resolve({
        exitCode: 1,
        output: appendBoundedOutput(capturedOutput, `${error.name}: ${error.message}`),
      });
    });
    child.once("close", (exitCode, signal) => {
      if (settled) return;
      settled = true;
      resolve({
        exitCode: exitCode ?? 1,
        output: signal
          ? appendBoundedOutput(capturedOutput, `\nProcess signal: ${signal}`)
          : capturedOutput,
      });
    });
  });
}

export function runPnpmDependencyAudit({
  environment = process.env,
  platform = process.platform,
  commandInterpreter = process.env.ComSpec,
  spawnProcess = spawn,
  stdout = process.stdout,
  stderr = process.stderr,
} = {}) {
  const invocation = dependencyAuditInvocation(platform, commandInterpreter);

  return runPnpmCommand({
    invocation,
    environment: {
      ...environment,
      pnpm_config_fetch_retries: "0",
    },
    spawnProcess,
    stdout,
    stderr,
  });
}

export function productionAuditExceptionPackagesFromWhy(whyResult) {
  if (!Array.isArray(whyResult)) {
    throw new TypeError("pnpm why output must be a JSON array");
  }

  return whyResult.length === 0
    ? []
    : [...developmentOnlyAuditExceptionPackages];
}

export function runPnpmProductionDependencyWhy({
  environment = process.env,
  platform = process.platform,
  commandInterpreter = process.env.ComSpec,
  spawnProcess = spawn,
  stdout = { write: () => {} },
  stderr = process.stderr,
} = {}) {
  return runPnpmCommand({
    invocation: productionDependencyWhyInvocation(
      platform,
      commandInterpreter,
    ),
    environment,
    spawnProcess,
    stdout,
    stderr,
  });
}

export async function verifyProductionAuditExceptionBoundary({
  runProductionWhy = runPnpmProductionDependencyWhy,
  writeStatus = (message) => process.stderr.write(`${message}\n`),
} = {}) {
  const result = await runProductionWhy();
  if (result.exitCode !== 0) {
    writeStatus(
      "DEPENDENCY_AUDIT_PRODUCTION_BOUNDARY=FAIL reason=production-why-failed",
    );
    return { ok: false, exitCode: result.exitCode || 1 };
  }

  let whyResult;
  try {
    whyResult = JSON.parse(result.output);
    const productionExceptions =
      productionAuditExceptionPackagesFromWhy(whyResult);
    if (productionExceptions.length > 0) {
      writeStatus(
        `DEPENDENCY_AUDIT_PRODUCTION_BOUNDARY=FAIL reason=ignored-package-production-reachable packages=${productionExceptions.join(",")}`,
      );
      return {
        ok: false,
        exitCode: 1,
        productionExceptions,
      };
    }
  } catch {
    writeStatus(
      "DEPENDENCY_AUDIT_PRODUCTION_BOUNDARY=FAIL reason=invalid-production-why-json",
    );
    return { ok: false, exitCode: 1 };
  }

  writeStatus("DEPENDENCY_AUDIT_PRODUCTION_BOUNDARY=PASS");
  return { ok: true, exitCode: 0, productionExceptions: [] };
}

export async function auditDependencies({
  runAudit = runPnpmDependencyAudit,
  retryDelaysMs = dependencyAuditRetryDelaysMs,
  sleep = wait,
  writeStatus = (message) => process.stderr.write(`${message}\n`),
} = {}) {
  const maximumAttempts = retryDelaysMs.length + 1;

  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    const result = await runAudit();
    if (result.exitCode === 0) {
      writeStatus(`DEPENDENCY_AUDIT=PASS attempts=${attempt}`);
      return { ok: true, attempts: attempt, exitCode: 0 };
    }

    const transient = isTransientDependencyAuditFailure(result.output);
    if (!transient) {
      writeStatus(
        `DEPENDENCY_AUDIT=FAIL attempts=${attempt} reason=non-transient-audit-failure`,
      );
      return { ok: false, attempts: attempt, exitCode: result.exitCode };
    }

    if (attempt === maximumAttempts) {
      writeStatus(
        `DEPENDENCY_AUDIT=FAIL attempts=${attempt} reason=transient-retries-exhausted`,
      );
      return { ok: false, attempts: attempt, exitCode: result.exitCode };
    }

    const delayMs = retryDelaysMs[attempt - 1];
    writeStatus(
      `DEPENDENCY_AUDIT_RETRY attempt=${attempt + 1}/${maximumAttempts} delayMs=${delayMs}`,
    );
    await sleep(delayMs);
  }

  throw new Error("dependency audit retry loop ended without a result");
}

const invokedAsScript = process.argv[1]
  && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (invokedAsScript) {
  const productionBoundary = await verifyProductionAuditExceptionBoundary();
  if (!productionBoundary.ok) {
    process.exitCode = productionBoundary.exitCode || 1;
  } else {
    const result = await auditDependencies();
    if (!result.ok) process.exitCode = result.exitCode || 1;
  }
}
