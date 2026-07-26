import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");
const inventoryPath = path.join(repoRoot, "SHIPPED_DEPENDENCY_INVENTORY.json");
const windowsTarget = "x86_64-pc-windows-msvc";
const knownLicenseTerms = new Set([
  "0BSD",
  "Apache-2.0",
  "BSD-2-Clause",
  "BSD-3-Clause",
  "CC0-1.0",
  "CDLA-Permissive-2.0",
  "ISC",
  "LGPL-2.1-or-later",
  "LLVM-exception",
  "MIT",
  "MIT-0",
  "MPL-2.0",
  "Unicode-3.0",
  "Unlicense",
  "Zlib",
]);

export async function buildShippedDependencyInventory() {
  const javascript = javascriptRuntimePackages();
  const rust = rustRuntimePackages();
  return {
    schemaVersion: 1,
    target: windowsTarget,
    generatedFrom: {
      packageJsonSha256: await sha256File(path.join(repoRoot, "desktop", "package.json")),
      pnpmLockSha256: await sha256File(path.join(repoRoot, "desktop", "pnpm-lock.yaml")),
      cargoTomlSha256: await sha256File(
        path.join(repoRoot, "desktop", "src-tauri", "Cargo.toml"),
      ),
      cargoLockSha256: await sha256File(
        path.join(repoRoot, "desktop", "src-tauri", "Cargo.lock"),
      ),
    },
    packages: { javascript, rust },
  };
}

export async function verifyShippedDependencyInventory() {
  const expected = `${JSON.stringify(await buildShippedDependencyInventory(), null, 2)}\n`;
  const actual = await readFile(inventoryPath, "utf8");
  assert(actual === expected, "Shipped dependency inventory differs from the exact lockfiles.");
  const notice = await readFile(path.join(repoRoot, "THIRD_PARTY_NOTICES.md"), "utf8");
  assert(
    notice.includes("## Shipped desktop dependency inventory"),
    "Shipped dependency notice section is missing.",
  );
  const inventory = JSON.parse(actual);
  const packages = [...inventory.packages.javascript, ...inventory.packages.rust];
  for (const packageRecord of packages) {
    for (const term of packageRecord.licenseTerms) {
      assert(
        notice.includes(`\`${term}\``),
        `License term ${term} has no shipped notice mapping.`,
      );
    }
  }
  return inventory;
}

function javascriptRuntimePackages() {
  const executable = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
  const raw = run(executable, ["licenses", "list", "--prod", "--json"], {
    cwd: path.join(repoRoot, "desktop"),
  });
  const grouped = JSON.parse(raw);
  const packages = [];
  for (const entries of Object.values(grouped)) {
    for (const entry of entries) {
      for (const version of entry.versions) {
        packages.push(packageRecord("javascript", entry.name, version, entry.license));
      }
    }
  }
  return uniqueSorted(packages);
}

function rustRuntimePackages() {
  const executable = process.platform === "win32" ? "cargo.exe" : "cargo";
  const output = run(executable, [
    "tree",
    "--locked",
    "--manifest-path",
    path.join(repoRoot, "desktop", "src-tauri", "Cargo.toml"),
    "--target",
    windowsTarget,
    "--edges",
    "normal",
    "--prefix",
    "none",
    "--format",
    "{p}\t{l}",
  ]);
  const packages = [];
  for (const line of output.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [normalized, license = ""] = line.replace(/ \(\*\)$/, "").split("\t");
    const match = /^(.*?) v([^\s]+)(?: \(.+\))?$/.exec(normalized);
    assert(match, `Cargo dependency row is invalid: ${line}`);
    const [, name, version] = match;
    if (name === "yap-desktop") continue;
    packages.push(packageRecord("rust", name, version, license));
  }
  return uniqueSorted(packages);
}

function packageRecord(ecosystem, name, version, licenseExpression) {
  assert(typeof name === "string" && name.length > 0, "Dependency name is missing.");
  assert(typeof version === "string" && version.length > 0, `Dependency ${name} has no version.`);
  assert(
    typeof licenseExpression === "string" && licenseExpression.trim().length > 0,
    `Dependency ${name}@${version} has no declared license.`,
  );
  if (
    ecosystem === "javascript"
    && name === "gsap"
    && licenseExpression.startsWith("Standard 'no charge' license:")
  ) {
    return {
      name,
      version,
      licenseExpression,
      licenseTerms: ["GSAP-Standard"],
      reviewDisposition: "reviewed-custom-runtime-license",
    };
  }
  const terms = [...new Set(
    licenseExpression
      .match(/[A-Za-z0-9.-]+/g)
      ?.filter((term) => !["AND", "OR", "WITH"].includes(term)) ?? [],
  )].sort();
  assert(terms.length > 0, `Dependency ${name}@${version} has no parseable license term.`);
  for (const term of terms) {
    assert(
      knownLicenseTerms.has(term),
      `Dependency ${name}@${version} uses unreviewed license term ${term}.`,
    );
  }
  return {
    name,
    version,
    licenseExpression,
    licenseTerms: terms,
    reviewDisposition: "mapped-to-shipped-license-family",
  };
}

function uniqueSorted(packages) {
  const byIdentity = new Map();
  for (const packageRecord of packages) {
    const identity = `${packageRecord.name}\0${packageRecord.version}`;
    const existing = byIdentity.get(identity);
    if (existing) {
      assert(
        existing.licenseExpression === packageRecord.licenseExpression,
        `Dependency ${packageRecord.name}@${packageRecord.version} has conflicting licenses.`,
      );
    } else {
      byIdentity.set(identity, packageRecord);
    }
  }
  return [...byIdentity.values()].sort(
    (left, right) => left.name.localeCompare(right.name) || left.version.localeCompare(right.version),
  );
}

function run(executable, args, options = {}) {
  const command = process.platform === "win32" && executable.endsWith(".cmd")
    ? process.env.ComSpec ?? "cmd.exe"
    : executable;
  const commandArgs = command === executable ? args : ["/d", "/s", "/c", executable, ...args];
  return execFileSync(command, commandArgs, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    windowsHide: true,
    ...options,
  });
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main(args) {
  const write = args.includes("--write");
  assert(args.every((argument) => argument === "--write"), "Unknown inventory argument.");
  if (write) {
    const inventory = await buildShippedDependencyInventory();
    await writeFile(inventoryPath, `${JSON.stringify(inventory, null, 2)}\n`, "utf8");
    console.log("Shipped dependency inventory updated.");
    return;
  }
  const inventory = await verifyShippedDependencyInventory();
  console.log(
    `Shipped dependency inventory passed (${inventory.packages.javascript.length} JavaScript, `
      + `${inventory.packages.rust.length} Rust packages).`,
  );
}

const entryPoint = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (entryPoint === import.meta.url) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
