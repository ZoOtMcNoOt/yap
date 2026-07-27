import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import {
  existsSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  cleanupWindowsSupervisorFiles,
} from "../../../../verification/windows-command-job-protocol.mjs";
import {
  startWindowsSupervisorTerminationWatchdog,
} from "../../../../verification/windows-command-supervisor-watchdog.mjs";

test("Windows supervisor watchdog settles and removes a late status", async () => {
  const root = mkdtempSync(path.join(
    realpathSync.native(os.tmpdir()),
    "yap-gate-job-watchdog-",
  ));
  const protocol = {
    launchSpecPath: path.join(root, "launch.json"),
    statusPath: path.join(root, "status.json"),
  };
  const supervisor = new EventEmitter();
  let killCalls = 0;
  let unrefCalls = 0;
  let destroyedStreams = 0;
  supervisor.kill = () => {
    killCalls += 1;
    return false;
  };
  supervisor.unref = () => {
    unrefCalls += 1;
  };
  const stream = () => ({
    destroy() {
      destroyedStreams += 1;
    },
  });
  supervisor.stdin = stream();
  supervisor.stdout = stream();
  supervisor.stderr = stream();

  try {
    const failure = await new Promise((resolve) => {
      startWindowsSupervisorTerminationWatchdog({
        supervisor,
        onLateClose: () => cleanupWindowsSupervisorFiles(protocol),
        onUnproven: resolve,
        killTimeoutMilliseconds: 5,
        finalSettlementTimeoutMilliseconds: 5,
      });
    });
    assert.match(failure.message, /did not close before its final deadline/);
    assert.equal(killCalls, 1);
    assert.equal(unrefCalls, 1);
    assert.equal(destroyedStreams, 3);

    writeFileSync(protocol.statusPath, "{}\n", { flag: "wx" });
    supervisor.emit("close", 0, null);
    assert.equal(existsSync(protocol.statusPath), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
