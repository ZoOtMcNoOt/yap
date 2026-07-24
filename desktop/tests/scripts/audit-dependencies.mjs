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

export function runPnpmDependencyAudit({
  environment = process.env,
  platform = process.platform,
  commandInterpreter = process.env.ComSpec,
  spawnProcess = spawn,
  stdout = process.stdout,
  stderr = process.stderr,
} = {}) {
  const invocation = dependencyAuditInvocation(platform, commandInterpreter);

  return new Promise((resolve) => {
    let capturedOutput = "";
    let settled = false;
    const child = spawnProcess(invocation.command, invocation.args, {
      cwd: process.cwd(),
      env: {
        ...environment,
        pnpm_config_fetch_retries: "0",
      },
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
  const result = await auditDependencies();
  if (!result.ok) process.exitCode = result.exitCode || 1;
}
