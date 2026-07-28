import {
  lstatSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertPrivateSshFile,
} from "./private-gate-artifacts.mjs";

const EXPECTED_DESTINATION = "admin@192.168.50.1";
const LOOPBACK_FORWARD = "127.0.0.1:18765:127.0.0.1:18765";
const NULL_CONFIG = process.platform === "win32" ? "NUL" : "/dev/null";
const PROFILE_ENVIRONMENT_NAMES = Object.freeze({
  destination: "YAP_PRIVATE_SERVER_SSH_DESTINATION",
  executable: "YAP_PRIVATE_SERVER_SSH_EXECUTABLE",
  identityFile: "YAP_PRIVATE_SERVER_SSH_IDENTITY_FILE",
  knownHostsFile: "YAP_PRIVATE_SERVER_SSH_KNOWN_HOSTS_FILE",
});

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function samePath(left, right) {
  const normalizedLeft = path.normalize(left);
  const normalizedRight = path.normalize(right);
  return process.platform === "win32"
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function verifiedRegularFile(candidate, label, { singleLink }) {
  requireCondition(path.isAbsolute(candidate), `${label} must be absolute.`);
  const normalized = path.normalize(candidate);
  const metadata = lstatSync(normalized);
  const real = path.normalize(realpathSync.native(normalized));
  requireCondition(
    metadata.isFile()
      && !metadata.isSymbolicLink()
      && samePath(normalized, real)
      && (!singleLink || metadata.nlink === 1),
    `${label} must be one real${singleLink ? " single-link" : ""} file.`,
  );
  return real;
}

function requiredEnvironment(source, name) {
  const value = source[name];
  requireCondition(
    typeof value === "string" && value.length > 0,
    `${name} is required for the checked private-server SSH profile.`,
  );
  return value;
}

export function privateServerSystemSshExecutable() {
  if (process.platform === "win32") {
    const systemRoot = process.env.SystemRoot ?? process.env.WINDIR;
    requireCondition(
      typeof systemRoot === "string" && path.isAbsolute(systemRoot),
      "Windows system root is unavailable for the checked OpenSSH profile.",
    );
    return verifiedRegularFile(
      path.join(systemRoot, "System32", "OpenSSH", "ssh.exe"),
      "Windows system OpenSSH executable",
      { singleLink: false },
    );
  }
  return verifiedRegularFile(
    "/usr/bin/ssh",
    "System OpenSSH executable",
    { singleLink: false },
  );
}

export function loadPrivateServerSshProfile(source = process.env) {
  const destination = requiredEnvironment(
    source,
    PROFILE_ENVIRONMENT_NAMES.destination,
  );
  requireCondition(
    destination === EXPECTED_DESTINATION,
    `${PROFILE_ENVIRONMENT_NAMES.destination} must be ${EXPECTED_DESTINATION}.`,
  );
  const expectedExecutable = privateServerSystemSshExecutable();
  const executable = verifiedRegularFile(
    requiredEnvironment(source, PROFILE_ENVIRONMENT_NAMES.executable),
    "Private-server SSH executable",
    { singleLink: false },
  );
  requireCondition(
    samePath(executable, expectedExecutable),
    `Private-server SSH executable must be the pinned system OpenSSH executable: ${
      expectedExecutable
    }.`,
  );
  const identityFile = assertPrivateSshFile(verifiedRegularFile(
    requiredEnvironment(source, PROFILE_ENVIRONMENT_NAMES.identityFile),
    "Private-server SSH identity",
    { singleLink: true },
  ));
  const knownHostsFile = assertPrivateSshFile(verifiedRegularFile(
    requiredEnvironment(source, PROFILE_ENVIRONMENT_NAMES.knownHostsFile),
    "Private-server SSH known-hosts database",
    { singleLink: true },
  ));
  requireCondition(
    !samePath(identityFile, knownHostsFile),
    "Private-server SSH identity and known-hosts database must be distinct files.",
  );
  return Object.freeze({
    destination,
    executable,
    identityFile,
    knownHostsFile,
  });
}

export function privateServerSshEnvironment(source = process.env) {
  const allowed = [
    "SystemRoot",
    "WINDIR",
    "PROGRAMDATA",
    "TEMP",
    "TMP",
  ];
  return Object.freeze(Object.fromEntries(allowed.flatMap((name) => (
    typeof source[name] === "string" && source[name].length > 0
      ? [[name, source[name]]]
      : []
  ))));
}

function commonArguments(profile) {
  return [
    "-F", NULL_CONFIG,
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "IdentityAgent=none",
    "-o", "StrictHostKeyChecking=yes",
    "-o", `UserKnownHostsFile=${profile.knownHostsFile}`,
    "-o", `GlobalKnownHostsFile=${NULL_CONFIG}`,
    "-o", "ForwardAgent=no",
    "-o", "ForwardX11=no",
    "-o", "ForwardX11Trusted=no",
    "-o", "PermitLocalCommand=no",
    "-o", "PasswordAuthentication=no",
    "-o", "KbdInteractiveAuthentication=no",
    "-o", "NumberOfPasswordPrompts=0",
    "-o", "ProxyCommand=none",
    "-o", "ProxyJump=none",
    "-o", "ControlMaster=no",
    "-o", "ControlPath=none",
    "-o", "SendEnv=-*",
    "-o", "RequestTTY=no",
    "-o", "Tunnel=no",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
    "-o", "ConnectionAttempts=1",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
    "-i", profile.identityFile,
  ];
}

export function privateServerControlSshInvocation(
  profile,
  remoteArguments = [],
) {
  requireCondition(Array.isArray(remoteArguments), "Remote SSH arguments must be an array.");
  requireCondition(
    remoteArguments.every(
      (argument) => typeof argument === "string" && !argument.includes("\0"),
    ),
    "Remote SSH arguments must be NUL-free strings.",
  );
  return Object.freeze({
    executable: profile.executable,
    args: Object.freeze([
      ...commonArguments(profile),
      "-o", "ClearAllForwardings=yes",
      "-T",
      profile.destination,
      ...remoteArguments,
    ]),
  });
}

export function privateServerTunnelSshInvocation(profile) {
  return Object.freeze({
    executable: profile.executable,
    args: Object.freeze([
      ...commonArguments(profile),
      "-o", "ExitOnForwardFailure=yes",
      "-N",
      "-T",
      "-L", LOOPBACK_FORWARD,
      profile.destination,
    ]),
  });
}

function runCli() {
  requireCondition(
    process.argv.length === 3 && process.argv[2] === "describe",
    "Usage: private-server-ssh-profile.mjs describe",
  );
  const profile = loadPrivateServerSshProfile();
  const control = privateServerControlSshInvocation(profile);
  const tunnel = privateServerTunnelSshInvocation(profile);
  process.stdout.write(`${JSON.stringify({
    schemaVersion: 1,
    profile,
    environment: privateServerSshEnvironment(),
    control,
    tunnel,
  })}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    runCli();
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
