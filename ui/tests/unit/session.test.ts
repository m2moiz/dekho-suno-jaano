// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, startHeartbeat, takeToken } from "../../src/features/session/session";

const TOKEN = "abcDEF123_-xyz";

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("takeToken", () => {
  it("takes the token and wipes it from the address bar", () => {
    window.history.replaceState(null, "", `/?x=1#t=${TOKEN}`);
    expect(takeToken()).toBe(TOKEN);
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain(TOKEN);
    // The rest of the address is left as it was.
    expect(window.location.search).toBe("?x=1");
  });

  it("keeps the token for a reload of the same tab", () => {
    window.history.replaceState(null, "", `/#t=${TOKEN}`);
    takeToken();
    window.history.replaceState(null, "", "/");
    expect(takeToken()).toBe(TOKEN);
  });

  it("has no token when the page was opened without one", () => {
    window.history.replaceState(null, "", "/");
    expect(takeToken()).toBeNull();
  });
});

describe("apiFetch", () => {
  it("sends the token as a header, never in the address", async () => {
    window.history.replaceState(null, "", `/#t=${TOKEN}`);
    takeToken();
    const seen = vi.fn<typeof fetch>().mockResolvedValue(new Response("[]"));
    vi.stubGlobal("fetch", seen);
    await apiFetch("/api/recordings");
    const [path, init] = seen.mock.calls[0] ?? [];
    expect(path).toBe("/api/recordings");
    expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${TOKEN}`);
  });
});

describe("startHeartbeat", () => {
  it("beats at once, then every 15 seconds, until stopped", () => {
    vi.useFakeTimers();
    window.history.replaceState(null, "", `/#t=${TOKEN}`);
    takeToken();
    const seen = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", seen);
    const stop = startHeartbeat();
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen.mock.calls[0]?.[0]).toBe("/api/heartbeat");
    expect(seen.mock.calls[0]?.[1]?.method).toBe("POST");
    vi.advanceTimersByTime(45_000);
    expect(seen).toHaveBeenCalledTimes(4);
    stop();
    vi.advanceTimersByTime(60_000);
    expect(seen).toHaveBeenCalledTimes(4);
  });
});
