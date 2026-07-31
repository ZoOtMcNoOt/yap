import {
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  loadPrivateServerSshProfile,
  privateServerControlSshInvocation,
  privateServerSshEnvironment,
  privateServerSystemSshExecutable,
  privateServerTunnelSshInvocation,
} from "../../../verification/private-server-ssh-profile.mjs";
import {
  protectAndVerifyPrivateDirectory,
  protectAndVerifyPrivateFile,
  protectAndVerifyPrivateSshFile,
} from "../../../verification/private-gate-artifacts.mjs";

let fixture;

function createFixtureProfile() {
  const root = protectAndVerifyPrivateDirectory(
    mkdtempSync(path.join(realpathSync.native(os.tmpdir()), "yap-ssh-profile-")),
  );
  const executable = privateServerSystemSshExecutable();
  const identityFile = path.join(root, "identity");
  const knownHostsFile = path.join(root, "known-hosts");
  for (const candidate of [identityFile, knownHostsFile]) {
    writeFileSync(candidate, "fixture");
    protectAndVerifyPrivateSshFile(candidate);
  }
  return {
    source: {
      YAP_PRIVATE_SERVER_SSH_DESTINATION: "admin@192.168.50.1",
      YAP_PRIVATE_SERVER_SSH_EXECUTABLE: executable,
      YAP_PRIVATE_SERVER_SSH_IDENTITY_FILE: identityFile,
      YAP_PRIVATE_SERVER_SSH_KNOWN_HOSTS_FILE: knownHostsFile,
    },
    executable,
    identityFile,
    knownHostsFile,
    root,
  };
}

beforeAll(() => {
  fixture = createFixtureProfile();
});

afterAll(() => {
  rmSync(fixture.root, { recursive: true, force: true });
});

describe("checked private-server SSH profile", () => {
  it("builds one frozen no-config control transport", () => {
    const profile = loadPrivateServerSshProfile(fixture.source);
    const invocation = privateServerControlSshInvocation(profile, ["bash", "/private/start.sh"]);

    expect(invocation.executable).toBe(fixture.executable);
    expect(invocation.args.slice(0, 2)).toEqual([
      "-F",
      process.platform === "win32" ? "NUL" : "/dev/null",
    ]);
    expect(invocation.args).toContain("ClearAllForwardings=yes");
    expect(invocation.args).toContain("ForwardAgent=no");
    expect(invocation.args).toContain("SendEnv=-*");
    expect(invocation.args).toContain(`UserKnownHostsFile=${fixture.knownHostsFile}`);
    expect(invocation.args).toContain(fixture.identityFile);
    expect(invocation.args).not.toContain("-L");
    expect(invocation.args.slice(-3)).toEqual([
      "admin@192.168.50.1",
      "bash",
      "/private/start.sh",
    ]);
  });

  it("builds exactly one explicit loopback tunnel without ambient configuration", () => {
    const invocation = privateServerTunnelSshInvocation(
      loadPrivateServerSshProfile(fixture.source),
    );
    const localForwardIndexes = invocation.args.flatMap(
      (value, index) => value === "-L" ? [index] : [],
    );

    expect(localForwardIndexes).toHaveLength(1);
    expect(invocation.args[localForwardIndexes[0] + 1])
      .toBe("127.0.0.1:18765:127.0.0.1:18765");
    expect(invocation.args).toContain("ExitOnForwardFailure=yes");
    expect(invocation.args).not.toContain("ClearAllForwardings=yes");
    expect(invocation.args.slice(-1)).toEqual(["admin@192.168.50.1"]);
  });

  it("rejects alias destinations and strips credentials from the SSH process environment", () => {
    expect(() => loadPrivateServerSshProfile({
      ...fixture.source,
      YAP_PRIVATE_SERVER_SSH_DESTINATION: "dgx-spark-eth",
    })).toThrow(/admin@192\.168\.50\.1/);

    const environment = privateServerSshEnvironment({
      SystemRoot: "C:\\Windows",
      PROGRAMDATA: "C:\\ProgramData",
      TEMP: "C:\\Temp",
      GH_TOKEN: "must-not-pass",
      AWS_SECRET_ACCESS_KEY: "must-not-pass",
    });
    expect(environment).toEqual({
      SystemRoot: "C:\\Windows",
      PROGRAMDATA: "C:\\ProgramData",
      TEMP: "C:\\Temp",
    });
  });

  it("rejects a non-system SSH executable and permissive SSH material", () => {
    const fakeExecutable = path.join(
      path.dirname(fixture.identityFile),
      process.platform === "win32" ? "ssh.exe" : "ssh",
    );
    writeFileSync(fakeExecutable, "fixture");
    expect(() => loadPrivateServerSshProfile({
      ...fixture.source,
      YAP_PRIVATE_SERVER_SSH_EXECUTABLE: fakeExecutable,
    })).toThrow(/pinned system OpenSSH executable/);

    const permissiveIdentity = path.join(
      path.dirname(fixture.identityFile),
      "permissive-identity",
    );
    writeFileSync(permissiveIdentity, "fixture");
    expect(() => loadPrivateServerSshProfile({
      ...fixture.source,
      YAP_PRIVATE_SERVER_SSH_IDENTITY_FILE: permissiveIdentity,
    })).toThrow(/private gate file|DACL|mode 600/i);

    const permissiveKnownHosts = path.join(
      path.dirname(fixture.identityFile),
      "permissive-known-hosts",
    );
    writeFileSync(permissiveKnownHosts, "fixture");
    expect(() => loadPrivateServerSshProfile({
      ...fixture.source,
      YAP_PRIVATE_SERVER_SSH_KNOWN_HOSTS_FILE: permissiveKnownHosts,
    })).toThrow(/private gate file|DACL|mode 600/i);

    if (process.platform === "win32") {
      const gatePolicyIdentity = path.join(
        path.dirname(fixture.identityFile),
        "gate-policy-identity",
      );
      writeFileSync(gatePolicyIdentity, "fixture");
      protectAndVerifyPrivateFile(gatePolicyIdentity);
      expect(() => loadPrivateServerSshProfile({
        ...fixture.source,
        YAP_PRIVATE_SERVER_SSH_IDENTITY_FILE: gatePolicyIdentity,
      })).toThrow(/DACL|unexpected access rule/i);
    }
  }, 15_000);
});
