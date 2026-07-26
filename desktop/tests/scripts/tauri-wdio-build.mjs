import { copyFile, rm } from "node:fs/promises";
import path from "node:path";
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { resolvePackageManagerCommand } from "./package-manager-command.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const repositoryRoot = path.resolve(root, "..");
const source = path.join(root, "tests", "wdio", "capabilities", "wdio.json");
const generated = path.join(root, "src-tauri", "capabilities", "wdio.generated.json");
const argumentsSet = new Set(process.argv.slice(2));
if ([...argumentsSet].some((argument) => argument !== "--release")) {
  throw new Error("tauri-wdio-build accepts only the optional --release argument.");
}
const release = argumentsSet.has("--release");
const checkedHead = process.env.YAP_CHECKED_HEAD?.trim();
const buildGitSha = checkedHead || "unbound";
if (checkedHead) {
  assertCleanCheckedHead(checkedHead, "before");
}
const packageManager = resolvePackageManagerCommand({
  args: [
    "tauri",
    "build",
    ...(release ? [] : ["--debug"]),
    "--features",
    "wdio",
    "--config",
    "src-tauri/tauri.wdio.conf.json",
    "--no-bundle",
  ],
  nodeExecPath: process.execPath,
  npmExecPath: process.env.npm_execpath,
});

let exitCode = 1;
await rm(generated, { force: true });
await copyFile(source, generated);

try {
  exitCode = await run(
    packageManager.command,
    packageManager.args,
  );
} finally {
  await rm(generated, { force: true });
}
if (exitCode === 0 && checkedHead) {
  assertCleanCheckedHead(checkedHead, "after");
}
process.exitCode = exitCode;

function assertCleanCheckedHead(expectedHead, boundary) {
  if (!/^[0-9a-f]{40}$/.test(expectedHead)) {
    throw new Error("YAP_CHECKED_HEAD must be one exact lowercase Git SHA.");
  }
  const actualHead = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim();
  if (actualHead !== expectedHead) {
    throw new Error(`The WDIO build head changed ${boundary} compilation.`);
  }
  const status = execFileSync(
    "git",
    ["status", "--porcelain=v1", "--untracked-files=normal"],
    { cwd: repositoryRoot, encoding: "utf8" },
  ).trim();
  if (status) {
    throw new Error(`The checked-head WDIO build was dirty ${boundary} compilation.`);
  }
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      env: {
        ...process.env,
        VITE_WDIO: "1",
        YAP_BUILD_GIT_SHA: buildGitSha,
      },
      stdio: "inherit",
    });

    child.on("error", reject);
    child.on("exit", (code) => resolve(code ?? 1));
  });
}
