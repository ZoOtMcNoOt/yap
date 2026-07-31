// Runs the vitest suites the hosted job skips. Exists because `VAR=1 cmd` is
// not portable to cmd.exe and this repository is Windows-first.
import { spawnSync } from "node:child_process";

const result = spawnSync("vitest", ["run"], {
  env: { ...process.env, YAP_RUN_LOCAL_ONLY_TESTS: "1" },
  shell: process.platform === "win32",
  stdio: "inherit",
});
process.exit(result.status ?? 1);
