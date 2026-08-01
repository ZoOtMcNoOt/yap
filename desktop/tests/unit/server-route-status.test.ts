import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  serverRoute,
  serverRouteAnnouncement,
  serverRouteLabel,
} from "../../src/components/app/server-route-status";
import type { ServerConnectionState } from "../../src/lib/setup-model";

const headerSource = readFileSync(
  new URL("../../src/components/panels/workspace-header.tsx", import.meta.url),
  "utf8",
);

const ALL_STATES: ServerConnectionState[] = [
  "not_set",
  "connecting",
  "ready",
  "offline",
  "sign_in_required",
  "access_denied",
  "retrying",
  "disabled",
];

describe("server route status", () => {
  // Anything that is not a working server connection means the recording stays
  // local. Saying so is more useful than naming the failure, and it is the
  // "private on this device" vs "org server" distinction PRODUCT.md asks for.
  it("treats every non-working connection as the local route", () => {
    expect(serverRoute("not_set")).toBe("local");
    expect(serverRoute("offline")).toBe("local");
    expect(serverRoute("disabled")).toBe("local");
    expect(serverRoute("ready")).toBe("server");
  });

  it("separates the two states a user can act on from the ones they cannot", () => {
    expect(serverRoute("sign_in_required")).toBe("sign-in");
    expect(serverRoute("access_denied")).toBe("blocked");
    expect(serverRoute("connecting")).toBe("checking");
    expect(serverRoute("retrying")).toBe("checking");
  });

  // A missing case would fall through to undefined and render an empty badge,
  // which reads as "no server configured" rather than as a bug.
  it("maps every connection state the backend can report", () => {
    for (const state of ALL_STATES) {
      const route = serverRoute(state);
      expect(route, `${state} has no route`).toBeDefined();
      expect(serverRouteLabel(route), `${state} has no label`).toBeTruthy();
      expect(serverRouteAnnouncement(route), `${state} has no announcement`).toBeTruthy();
    }
  });

  // Autoconnect moves this without the user touching anything, so the change
  // has to be spoken, not only drawn.
  it("gives every route a distinct spoken form", () => {
    const spoken = new Set(ALL_STATES.map((s) => serverRouteAnnouncement(serverRoute(s))));
    expect(spoken.size).toBe(new Set(ALL_STATES.map(serverRoute)).size);
  });

  // The point of the change: connection state used to be reachable only by
  // opening the settings sheet.
  it("is mounted in the workspace header, not only in settings", () => {
    expect(headerSource).toMatch(/<ServerRouteStatus\b/);
    expect(headerSource).toMatch(/state=\{serverState\}/);
    expect(headerSource).toMatch(/onSignIn=\{onOpenDetails\}/);
  });
});
