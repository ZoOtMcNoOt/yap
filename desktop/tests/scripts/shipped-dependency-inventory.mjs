import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");
const inventoryPath = path.join(repoRoot, "SHIPPED_DEPENDENCY_INVENTORY.json");
const noticeBundlePath = path.join(repoRoot, "SHIPPED_DEPENDENCY_NOTICES.json");
const noticeExemptionsPath = path.join(
  repoRoot,
  "SHIPPED_DEPENDENCY_NOTICE_EXEMPTIONS.json",
);
const windowsTarget = "x86_64-pc-windows-msvc";
const shippedEcosystems = Object.freeze(["javascript", "rust"]);
const exactNoticeName =
  /^(?:licen[cs]e|copying|notices?|copyright|authors?)(?:[._-].*)?$/i;
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

export async function buildShippedDependencyArtifacts() {
  const exemptions = await loadNoticeExemptions();
  const packageSources = {
    javascript: javascriptRuntimePackageSources(),
    rust: rustRuntimePackageSources(),
  };
  const documents = new Map();
  const usedExemptions = new Set();
  const packages = {};

  for (const ecosystem of shippedEcosystems) {
    packages[ecosystem] = [];
    for (const sourcePackage of packageSources[ecosystem]) {
      const notice = await resolvePackageNotice({
        ecosystem,
        sourcePackage,
        exemptions,
        documents,
      });
      if (notice.exemptionIdentity) usedExemptions.add(notice.exemptionIdentity);
      packages[ecosystem].push({
        name: sourcePackage.name,
        version: sourcePackage.version,
        licenseExpression: sourcePackage.licenseExpression,
        licenseTerms: sourcePackage.licenseTerms,
        reviewDisposition: sourcePackage.reviewDisposition,
        noticeDisposition: notice.noticeDisposition,
        ...(notice.reviewedExemptionReason
          ? { reviewedExemptionReason: notice.reviewedExemptionReason }
          : {}),
        noticeDocuments: notice.noticeDocuments,
      });
    }
  }

  const unusedExemptions = [...exemptions.keys()].filter(
    (identity) => !usedExemptions.has(identity),
  );
  assert(
    unusedExemptions.length === 0,
    `Reviewed notice exemptions are stale or unnecessary: ${unusedExemptions.join(", ")}.`,
  );

  // ponytail: no raw manifest/lockfile hashes here. The lockfiles are already
  // the pin, and hashing them made every dependency edit fail this gate even
  // when no shipped package moved — including devDependency bumps that ship
  // nothing. The package list below still changes whenever a shipped package
  // does, which is the property worth enforcing.
  const generatedFrom = {
    noticeExemptionsSha256: await sha256File(noticeExemptionsPath),
  };
  const inventory = {
    schemaVersion: 3,
    target: windowsTarget,
    generatedFrom,
    packages,
  };
  const notices = {
    schemaVersion: 2,
    target: windowsTarget,
    generatedFrom,
    packages: Object.fromEntries(
      shippedEcosystems.map((ecosystem) => [
        ecosystem,
        packages[ecosystem].map((packageRecord) => ({
          name: packageRecord.name,
          version: packageRecord.version,
          noticeDisposition: packageRecord.noticeDisposition,
          ...(packageRecord.reviewedExemptionReason
            ? { reviewedExemptionReason: packageRecord.reviewedExemptionReason }
            : {}),
          noticeDocuments: packageRecord.noticeDocuments,
        })),
      ]),
    ),
    documents: [...documents.values()].sort((left, right) =>
      compareText(left.sha256, right.sha256)),
  };
  return { inventory, notices };
}

export async function buildShippedDependencyInventory() {
  return (await buildShippedDependencyArtifacts()).inventory;
}

export async function verifyShippedDependencyInventory() {
  const { inventory } = await buildShippedDependencyArtifacts();
  const expected = serialize(inventory);
  const actual = await readFile(inventoryPath, "utf8");
  assert(
    actual === expected,
    "Shipped dependency inventory differs from the exact lockfiles. "
      + "Regenerate it on Windows with cargo and pnpm available: "
      + "cd desktop && pnpm install --frozen-lockfile && "
      + "node ./tests/scripts/shipped-dependency-inventory.mjs --write, "
      + "then commit SHIPPED_DEPENDENCY_INVENTORY.json and "
      + "SHIPPED_DEPENDENCY_NOTICES.json.",
  );
  const notice = await readFile(path.join(repoRoot, "THIRD_PARTY_NOTICES.md"), "utf8");
  assert(
    notice.includes("## Shipped desktop dependency inventory"),
    "Shipped dependency notice section is missing.",
  );
  for (const packageRecord of [
    ...inventory.packages.javascript,
    ...inventory.packages.rust,
  ]) {
    for (const term of packageRecord.licenseTerms) {
      assert(
        notice.includes(`\`${term}\``),
        `License term ${term} has no shipped license-family mapping.`,
      );
    }
  }
  return inventory;
}

export async function verifyShippedDependencyNotices(inventory = null) {
  const expectedArtifacts = await buildShippedDependencyArtifacts();
  const expected = serialize(expectedArtifacts.notices);
  const actual = await readFile(noticeBundlePath, "utf8");
  assert(
    actual === expected,
    "Shipped dependency notice bundle differs from the exact installed dependency sources.",
  );
  const notices = JSON.parse(actual);
  const comparedInventory = inventory ?? JSON.parse(await readFile(inventoryPath, "utf8"));
  const documentHashes = new Set();
  for (const document of notices.documents) {
    assert(
      sha256(Buffer.from(document.content, "utf8")) === document.sha256,
      `Shipped notice document ${document.sha256} does not match its exact bytes.`,
    );
    assert(
      !documentHashes.has(document.sha256),
      `Shipped notice document ${document.sha256} is duplicated.`,
    );
    documentHashes.add(document.sha256);
  }
  for (const ecosystem of shippedEcosystems) {
    assert(
      serialize(notices.packages[ecosystem])
        === serialize(comparedInventory.packages[ecosystem].map((packageRecord) => ({
          name: packageRecord.name,
          version: packageRecord.version,
          noticeDisposition: packageRecord.noticeDisposition,
          ...(packageRecord.reviewedExemptionReason
            ? { reviewedExemptionReason: packageRecord.reviewedExemptionReason }
            : {}),
          noticeDocuments: packageRecord.noticeDocuments,
        }))),
      `Shipped ${ecosystem} notice bindings do not match the dependency inventory.`,
    );
    for (const packageRecord of notices.packages[ecosystem]) {
      assert(
        packageRecord.noticeDocuments.length > 0,
        `${ecosystem} dependency ${packageRecord.name}@${packageRecord.version} has no notice bytes.`,
      );
      for (const document of packageRecord.noticeDocuments) {
        assert(
          documentHashes.has(document.sha256),
          `${ecosystem} dependency ${packageRecord.name}@${packageRecord.version} references a missing notice document.`,
        );
      }
    }
  }
  return notices;
}

async function resolvePackageNotice({
  ecosystem,
  sourcePackage,
  exemptions,
  documents,
}) {
  const perSource = [];
  for (const sourceDirectory of sourcePackage.sourceDirectories) {
    const entries = await readdir(sourceDirectory, { withFileTypes: true });
    const exactNoticeFiles = entries
      .filter((entry) => entry.isFile() && exactNoticeName.test(entry.name))
      .map((entry) => entry.name)
      .sort(compareText);
    const exemptionIdentity = packageIdentity(
      ecosystem,
      sourcePackage.name,
      sourcePackage.version,
    );
    const exemption = exemptions.get(exemptionIdentity);
    assert(
      exactNoticeFiles.length > 0 || exemption,
      `${ecosystem} dependency ${sourcePackage.name}@${sourcePackage.version} has no standalone notice and no exact reviewed exemption.`,
    );
    assert(
      exactNoticeFiles.length === 0 || !exemption,
      `${ecosystem} dependency ${sourcePackage.name}@${sourcePackage.version} no longer needs its reviewed notice exemption.`,
    );
    const sourceFiles = exactNoticeFiles.length > 0
      ? exactNoticeFiles
      : [exemption.sourceFile];
    const noticeDocuments = [];
    for (const sourceFile of sourceFiles) {
      assert(
        path.basename(sourceFile) === sourceFile && sourceFile !== "." && sourceFile !== "..",
        `Unsafe notice source name for ${sourcePackage.name}@${sourcePackage.version}.`,
      );
      const bytes = await readFile(path.join(sourceDirectory, sourceFile));
      const content = decodeUtf8(bytes, `${sourcePackage.name}@${sourcePackage.version}/${sourceFile}`);
      const digest = sha256(bytes);
      const existing = documents.get(digest);
      if (existing) {
        assert(
          existing.content === content,
          `Notice SHA-256 collision while reading ${sourcePackage.name}@${sourcePackage.version}.`,
        );
      } else {
        documents.set(digest, { sha256: digest, content });
      }
      noticeDocuments.push({ sourceFile, sha256: digest });
    }
    perSource.push(noticeDocuments);
  }
  for (const candidate of perSource.slice(1)) {
    assert(
      serialize(candidate) === serialize(perSource[0]),
      `${ecosystem} dependency ${sourcePackage.name}@${sourcePackage.version} has inconsistent installed copies.`,
    );
  }
  const exemptionIdentity = packageIdentity(
    ecosystem,
    sourcePackage.name,
    sourcePackage.version,
  );
  const exemption = exemptions.get(exemptionIdentity);
  return {
    noticeDisposition: exemption
      ? "reviewed-installed-metadata-exemption"
      : "exact-installed-notice-files",
    ...(exemption ? { reviewedExemptionReason: exemption.reason, exemptionIdentity } : {}),
    noticeDocuments: perSource[0],
  };
}

function javascriptRuntimePackageSources() {
  const executable = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
  const raw = run(executable, ["licenses", "list", "--prod", "--json"], {
    cwd: path.join(repoRoot, "desktop"),
  });
  const grouped = JSON.parse(raw);
  const packages = [];
  for (const entries of Object.values(grouped)) {
    for (const entry of entries) {
      assert(Array.isArray(entry.paths) && entry.paths.length > 0,
        `JavaScript dependency ${entry.name} has no installed source path.`);
      for (const sourceDirectory of entry.paths) {
        const metadata = JSON.parse(
          readFileSync(path.join(sourceDirectory, "package.json"), "utf8"),
        );
        assert(
          metadata.name === entry.name && entry.versions.includes(metadata.version),
          `JavaScript dependency source identity differs from pnpm output at ${sourceDirectory}.`,
        );
        packages.push({
          ...packageRecord("javascript", entry.name, metadata.version, entry.license),
          sourceDirectories: [sourceDirectory],
        });
      }
    }
  }
  return uniqueSortedSources(packages);
}

function rustRuntimePackageSources() {
  const executable = process.platform === "win32" ? "cargo.exe" : "cargo";
  const treeOutput = runCargo(executable, [
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
  const metadata = JSON.parse(runCargo(executable, [
    "metadata",
    "--locked",
    "--format-version",
    "1",
    "--manifest-path",
    path.join(repoRoot, "desktop", "src-tauri", "Cargo.toml"),
    "--filter-platform",
    windowsTarget,
  ]));
  const sourceDirectories = new Map();
  for (const packageMetadata of metadata.packages) {
    const identity = simpleIdentity(packageMetadata.name, packageMetadata.version);
    const directories = sourceDirectories.get(identity) ?? [];
    directories.push(path.dirname(packageMetadata.manifest_path));
    sourceDirectories.set(identity, directories);
  }
  const packages = [];
  for (const line of treeOutput.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [normalized, license = ""] = line.replace(/ \(\*\)$/, "").split("\t");
    const match = /^(.*?) v([^\s]+)(?: \(.+\))?$/.exec(normalized);
    assert(match, `Cargo dependency row is invalid: ${line}`);
    const [, name, version] = match;
    if (name === "yap-desktop") continue;
    const directories = sourceDirectories.get(simpleIdentity(name, version)) ?? [];
    assert(
      directories.length === 1,
      `Rust dependency ${name}@${version} did not resolve to one installed crate source.`,
    );
    packages.push({
      ...packageRecord("rust", name, version, license),
      sourceDirectories: directories,
    });
  }
  return uniqueSortedSources(packages);
}

export function cargoCommandEnvironment(environment = process.env) {
  return {
    ...environment,
    CARGO_TERM_COLOR: "never",
  };
}

function runCargo(executable, args) {
  return run(executable, args, {
    env: cargoCommandEnvironment(),
  });
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
  )].sort(compareText);
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

function uniqueSortedSources(packages) {
  const byIdentity = new Map();
  for (const candidate of packages) {
    const identity = simpleIdentity(candidate.name, candidate.version);
    const existing = byIdentity.get(identity);
    if (existing) {
      assert(
        existing.licenseExpression === candidate.licenseExpression,
        `Dependency ${candidate.name}@${candidate.version} has conflicting licenses.`,
      );
      existing.sourceDirectories.push(...candidate.sourceDirectories);
      existing.sourceDirectories = [...new Set(existing.sourceDirectories)].sort(compareText);
    } else {
      byIdentity.set(identity, candidate);
    }
  }
  return [...byIdentity.values()].sort(
    (left, right) =>
      compareText(left.name, right.name) || compareText(left.version, right.version),
  );
}

async function loadNoticeExemptions() {
  const value = JSON.parse(await readFile(noticeExemptionsPath, "utf8"));
  assert(value?.schemaVersion === 1, "Notice exemption schemaVersion must be 1.");
  assert(
    Array.isArray(value.exemptions),
    "Notice exemptions must contain an exemptions array.",
  );
  const exemptions = new Map();
  for (const exemption of value.exemptions) {
    assert(
      exemption
        && shippedEcosystems.includes(exemption.ecosystem)
        && typeof exemption.name === "string"
        && typeof exemption.version === "string"
        && typeof exemption.sourceFile === "string"
        && typeof exemption.reason === "string"
        && exemption.reason.length > 0,
      "Notice exemption is invalid.",
    );
    assert(
      Object.keys(exemption).sort(compareText).join("\0")
        === ["ecosystem", "name", "reason", "sourceFile", "version"].join("\0"),
      `Notice exemption ${exemption.name}@${exemption.version} has unsupported fields.`,
    );
    const identity = packageIdentity(
      exemption.ecosystem,
      exemption.name,
      exemption.version,
    );
    assert(!exemptions.has(identity), `Duplicate notice exemption ${identity}.`);
    exemptions.set(identity, exemption);
  }
  return exemptions;
}

function run(executable, args, options = {}) {
  const command = process.platform === "win32" && executable.endsWith(".cmd")
    ? process.env.ComSpec ?? "cmd.exe"
    : executable;
  const commandArgs = command === executable ? args : ["/d", "/s", "/c", executable, ...args];
  return execFileSync(command, commandArgs, {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    windowsHide: true,
    ...options,
  });
}

function decodeUtf8(bytes, label) {
  try {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new Error(`Installed dependency notice is not UTF-8 text: ${label}.`);
  }
}

function simpleIdentity(name, version) {
  return `${name}\0${version}`;
}

function packageIdentity(ecosystem, name, version) {
  return `${ecosystem}:${name}@${version}`;
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function serialize(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function sha256File(filePath) {
  return sha256(await readFile(filePath));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main(args) {
  const write = args.includes("--write");
  assert(args.every((argument) => argument === "--write"), "Unknown inventory argument.");
  const artifacts = await buildShippedDependencyArtifacts();
  if (write) {
    await Promise.all([
      writeFile(inventoryPath, serialize(artifacts.inventory), "utf8"),
      writeFile(noticeBundlePath, serialize(artifacts.notices), "utf8"),
    ]);
    console.log("Shipped dependency inventory and exact notice bundle updated.");
    return;
  }
  const inventory = await verifyShippedDependencyInventory();
  const notices = await verifyShippedDependencyNotices(inventory);
  console.log(
    `Shipped dependency inventory passed (${inventory.packages.javascript.length} JavaScript, `
      + `${inventory.packages.rust.length} Rust packages, `
      + `${notices.documents.length} exact notice documents).`,
  );
}

const entryPoint = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (entryPoint === import.meta.url) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
