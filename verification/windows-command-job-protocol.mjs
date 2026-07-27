import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import {
  closeSync,
  existsSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SUPERVISOR_CLEANUP_TIMEOUT_MS = 5_000;

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
const supervisorSourceFileNames = [
  "windows-command-job-supervisor.cs",
  "windows-command-launch-spec.cs",
  "windows-job-owned-process.cs",
  "windows-command-job-status.cs",
  "windows-job-native-api.cs",
];
const supervisorScriptPath = path.join(
  moduleDirectory,
  "windows-command-job-supervisor.ps1",
);

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function samePath(left, right) {
  return path.normalize(left).toLowerCase()
    === path.normalize(right).toLowerCase();
}

function resolveWindowsCommand(executable, cwd) {
  const localCandidate = path.resolve(cwd, executable);
  const candidates = executable.includes("/") || executable.includes("\\")
    ? [localCandidate]
    : spawnSync("where.exe", [executable], {
      cwd,
      encoding: "utf8",
      maxBuffer: 64 * 1024,
      windowsHide: true,
    }).stdout?.split(/\r?\n/).filter(Boolean) ?? [];
  const resolved = candidates.find((candidate) => (
    [".bat", ".cmd", ".com", ".exe"].includes(path.extname(candidate).toLowerCase())
      && existsSync(candidate)
      && lstatSync(candidate).isFile()
  ));
  requireCondition(resolved, `Windows could not resolve command ${executable}.`);
  return path.normalize(resolved);
}

function verifiedRegularFile(filePath, label) {
  const normalized = path.normalize(filePath);
  const metadata = lstatSync(normalized);
  const realPath = path.normalize(realpathSync.native(normalized));
  requireCondition(
    metadata.isFile()
      && !metadata.isSymbolicLink()
      && samePath(normalized, realPath),
    `${label} must be one real file.`,
  );
  return realPath;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function encodedSupervisorCommand(loaderBytes, parameters) {
  const loaderBase64 = loaderBytes.toString("base64");
  const parametersBase64 = Buffer.from(
    JSON.stringify(parameters),
    "utf8",
  ).toString("base64");
  const command = [
    `$loaderBytes=[Convert]::FromBase64String('${loaderBase64}');`,
    "$loader=[Text.UTF8Encoding]::new($false,$true).GetString($loaderBytes);",
    `$parameterBytes=[Convert]::FromBase64String('${parametersBase64}');`,
    "$parameterJson=[Text.UTF8Encoding]::new($false,$true).GetString($parameterBytes);",
    "$parameters=$parameterJson|ConvertFrom-Json -AsHashtable;",
    "& ([ScriptBlock]::Create($loader)) @parameters",
  ].join("");
  const encoded = Buffer.from(command, "utf16le").toString("base64");
  requireCondition(
    encoded.length < 30_000,
    "The immutable Windows supervisor loader exceeded the command-line bound.",
  );
  return encoded;
}

function windowsEnvironmentBytes(environment) {
  requireCondition(
    environment && typeof environment === "object" && !Array.isArray(environment),
    "The Windows command environment must be one key/value object.",
  );
  const candidates = Object.entries(environment)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => (
      left < right ? -1 : left > right ? 1 : 0
    ));
  const seen = new Set();
  const entries = [];
  for (const [name, rawValue] of candidates) {
    const normalizedName = name.toLowerCase();
    if (seen.has(normalizedName)) continue;
    requireCondition(
      name.length > 0
        && !name.includes("=")
        && !name.includes("\0")
        && !String(rawValue).includes("\0"),
      "The Windows command environment contained an invalid entry.",
    );
    seen.add(normalizedName);
    entries.push(`${name}=${String(rawValue)}`);
  }
  const bytes = Buffer.from(JSON.stringify(entries), "utf8");
  requireCondition(
    bytes.length <= 1024 * 1024,
    "The Windows command environment exceeded its in-memory transfer bound.",
  );
  return bytes;
}

export function createWindowsSupervisorInvocation(
  invocation,
  expectedLogDirectory,
  environment,
) {
  const pwshPath = resolveWindowsCommand("pwsh.exe", invocation.cwd);
  const sourcePaths = supervisorSourceFileNames.map((fileName) => (
    verifiedRegularFile(
      path.join(moduleDirectory, fileName),
      `Windows command Job supervisor source ${fileName}`,
    )
  ));
  const scriptPath = verifiedRegularFile(
    supervisorScriptPath,
    "Windows command Job supervisor loader",
  );
  const loaderBytes = readFileSync(scriptPath);
  const csharpSourceBytes = Buffer.concat(sourcePaths.flatMap((sourcePath, index) => (
    index === 0
      ? [readFileSync(sourcePath)]
      : [Buffer.from("\n"), readFileSync(sourcePath)]
  )));
  const csharpSourceSha256 = sha256(csharpSourceBytes);
  const supervisorIdentitySha256 = sha256(Buffer.concat([
    loaderBytes,
    Buffer.from("\n"),
    csharpSourceBytes,
  ]));
  const sourcePathsBase64 = Buffer.from(
    JSON.stringify(sourcePaths),
    "utf8",
  ).toString("base64");
  const identifier = randomBytes(16).toString("hex");
  const launchNonce = randomBytes(32).toString("hex");
  const launchSpecPath = path.join(
    expectedLogDirectory,
    `.windows-command-${identifier}.launch.json`,
  );
  const statusPath = path.join(
    expectedLogDirectory,
    `.windows-command-${identifier}.status.json`,
  );
  const launchSpecBytes = Buffer.from(
    `${JSON.stringify({
      schemaVersion: 1,
      executablePath: invocation.executable,
      arguments: invocation.args,
      workingDirectory: invocation.cwd,
      launchNonce,
    })}\n`,
    "utf8",
  );
  const launchSpecSha256 = sha256(launchSpecBytes);
  const environmentBytes = windowsEnvironmentBytes(environment);
  const environmentSha256 = sha256(environmentBytes);
  const environmentPrelude = `${environmentBytes.toString("base64")}\n`;
  let launchDescriptor = null;
  let launchSpecOwned = false;
  try {
    launchDescriptor = openSync(launchSpecPath, "wx", 0o600);
    launchSpecOwned = true;
    writeFileSync(launchDescriptor, launchSpecBytes);
    closeSync(launchDescriptor);
    launchDescriptor = null;
    return {
      invocation: {
        executable: pwshPath,
        args: [
          "-NoLogo",
          "-NoProfile",
          "-NonInteractive",
          "-EncodedCommand",
          encodedSupervisorCommand(loaderBytes, {
            SourcePathsBase64: sourcePathsBase64,
            LaunchSpecPath: launchSpecPath,
            LaunchSpecSha256: launchSpecSha256,
            LaunchNonce: launchNonce,
            StatusPath: statusPath,
            ExpectedCSharpSourceSha256: csharpSourceSha256,
            ExpectedEnvironmentSha256: environmentSha256,
            SupervisorIdentitySha256: supervisorIdentitySha256,
            CleanupTimeoutMilliseconds: SUPERVISOR_CLEANUP_TIMEOUT_MS,
          }),
        ],
        cwd: invocation.cwd,
      },
      csharpSourceSha256,
      environmentPrelude,
      environmentSha256,
      expectedLogDirectory,
      launchNonce,
      launchSpecPath,
      launchSpecSha256,
      statusPath,
      supervisorIdentitySha256,
    };
  } catch (error) {
    const cleanupFailures = [];
    if (launchDescriptor !== null) {
      try {
        closeSync(launchDescriptor);
      } catch (cleanupError) {
        cleanupFailures.push(cleanupError);
      }
    }
    if (launchSpecOwned) {
      try {
        unlinkSync(launchSpecPath);
      } catch (cleanupError) {
        if (cleanupError?.code !== "ENOENT") cleanupFailures.push(cleanupError);
      }
    }
    if (cleanupFailures.length > 0) {
      throw new AggregateError(
        [error, ...cleanupFailures],
        "Windows supervisor setup failed and its launch specification could not be removed.",
      );
    }
    throw error;
  }
}

export function cleanupWindowsSupervisorFiles(protocol) {
  if (!protocol) return;
  const failures = [];
  for (const filePath of [protocol.launchSpecPath, protocol.statusPath]) {
    try {
      unlinkSync(filePath);
    } catch (error) {
      if (error?.code !== "ENOENT") failures.push(error);
    }
  }
  if (failures.length > 0) {
    throw new AggregateError(
      failures,
      "Windows supervisor private files could not all be removed.",
    );
  }
}
