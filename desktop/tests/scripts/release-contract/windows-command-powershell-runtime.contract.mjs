import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  realpathSync,
  rmSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  cleanupWindowsSupervisorFiles,
  createWindowsSupervisorInvocation,
} from "../../../../verification/windows-command-job-protocol.mjs";

const contractRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(contractRoot, "..", "..", "..", "..");

function createCanonicalTemporaryDirectory(prefix) {
  return mkdtempSync(path.join(realpathSync.native(os.tmpdir()), prefix));
}

function requireUnsupportedRuntime({
  commandMutation,
  directoryPrefix,
}) {
  const root = createCanonicalTemporaryDirectory(directoryPrefix);
  const markerPath = path.join(root, "target-ran");
  let protocol;
  try {
    protocol = createWindowsSupervisorInvocation(
      {
        executable: process.execPath,
        args: [
          "-e",
          `require("node:fs").writeFileSync(${JSON.stringify(markerPath)},"ran")`,
        ],
        cwd: repoRoot,
      },
      root,
      process.env,
    );
    const encodedIndex = protocol.invocation.args.indexOf("-EncodedCommand") + 1;
    const decodedCommand = Buffer.from(
      protocol.invocation.args[encodedIndex],
      "base64",
    ).toString("utf16le");
    assert.match(
      decodedCommand,
      /\$PSVersionTable\.PSEdition -cne 'Core'.*\$PSVersionTable\.PSVersion -lt \[version\] '7\.4'/,
    );
    const unsupportedCommand = commandMutation(decodedCommand);
    assert.notEqual(unsupportedCommand, decodedCommand);
    protocol.invocation.args[encodedIndex] = Buffer.from(
      unsupportedCommand,
      "utf16le",
    ).toString("base64");

    const result = spawnSync(
      protocol.invocation.executable,
      protocol.invocation.args,
      {
        cwd: protocol.invocation.cwd,
        encoding: "utf8",
        env: process.env,
        input: protocol.environmentPrelude,
        maxBuffer: 64 * 1024,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    assert.notEqual(result.status, 0);
    assert.match(
      result.stderr,
      /requires PowerShell Core 7\.4 or newer/,
    );
    assert.equal(existsSync(markerPath), false);
    assert.equal(existsSync(protocol.statusPath), false);
  } finally {
    cleanupWindowsSupervisorFiles(protocol);
    rmSync(root, { recursive: true, force: true });
  }
}

test("encoded Windows supervisor rejects unsupported PowerShell before loading", {
  skip: process.platform !== "win32",
}, () => {
  requireUnsupportedRuntime({
    commandMutation: (command) => command.replace(
      "[version] '7.4'",
      "[version] '99.0'",
    ),
    directoryPrefix: "yap-gate-pwsh-version-",
  });
  requireUnsupportedRuntime({
    commandMutation: (command) => command.replace(
      "-cne 'Core'",
      "-cne 'UnsupportedEdition'",
    ),
    directoryPrefix: "yap-gate-pwsh-edition-",
  });
});
