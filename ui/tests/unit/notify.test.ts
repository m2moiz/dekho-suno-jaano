import { describe, expect, it } from "vitest";

import { askToNotify, type Notifier, notifyFinished, words } from "../../src/features/shell/notify";

// A notifier the test controls: what the browser would answer, and what was shown.
function fake(over: Partial<Notifier> & { focused?: () => boolean } = {}) {
  const shown: [string, string][] = [];
  let chimes = 0;
  let asked = 0;
  const notifier: Notifier = {
    permission: () => "granted",
    ask: async () => {
      asked += 1;
      return "granted";
    },
    show: (title, body) => {
      shown.push([title, body]);
    },
    focused: () => false,
    chime: () => {
      chimes += 1;
    },
    ...over,
  };
  return { notifier, shown, chimes: () => chimes, asked: () => asked };
}

const DONE = { kind: "transcription", name: "standup.m4a", outcome: "done" } as const;

describe("a finished job tells the person (#130)", () => {
  it("notifies and chimes when the window is not focused", () => {
    const f = fake();
    expect(notifyFinished(DONE, f.notifier)).toBe(true);
    expect(f.shown).toEqual([["Transcription finished", "standup.m4a"]]);
    expect(f.chimes()).toBe(1);
  });

  it("stays quiet when the window is focused: the row already shows it", () => {
    const f = fake({ focused: () => true });
    expect(notifyFinished(DONE, f.notifier)).toBe(false);
    expect(f.shown).toEqual([]);
    expect(f.chimes()).toBe(0);
  });

  it("degrades to silence when permission is denied, and never throws", () => {
    const f = fake({ permission: () => "denied" });
    expect(notifyFinished(DONE, f.notifier)).toBe(false);
    expect(f.shown).toEqual([]);
    // The chime does not need permission.
    expect(f.chimes()).toBe(1);
  });

  it("never throws when the browser has no Notification API or no audio", () => {
    const f = fake({
      permission: () => null,
      show: () => {
        throw new Error("no Notification here");
      },
      chime: () => {
        throw new Error("no AudioContext here");
      },
    });
    expect(() => notifyFinished(DONE, f.notifier)).not.toThrow();
  });

  it("names a failed render as failed, without a chime", () => {
    const f = fake();
    notifyFinished({ kind: "render", name: "call.bleeped.m4a", outcome: "failed" }, f.notifier);
    expect(f.shown).toEqual([["Bleep render failed", "call.bleeped.m4a"]]);
    expect(f.chimes()).toBe(0);
    expect(words(DONE).title).toBe("Transcription finished");
  });

  it("asks for permission once, only while the answer is still default", async () => {
    let permission: NotificationPermission = "default";
    const f = fake({
      permission: () => permission,
      ask: async () => {
        permission = "granted";
        return permission;
      },
    });
    await askToNotify(f.notifier);
    await askToNotify(f.notifier);
    expect(permission).toBe("granted");
    const denied = fake({ permission: () => "denied" });
    await askToNotify(denied.notifier);
    expect(denied.asked()).toBe(0);
  });

  it("swallows a refusal to ask", async () => {
    const f = fake({
      permission: () => "default",
      ask: async () => {
        throw new Error("no");
      },
    });
    await expect(askToNotify(f.notifier)).resolves.toBeUndefined();
  });
});
