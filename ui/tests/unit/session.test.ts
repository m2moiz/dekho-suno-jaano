import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created, so a stub put in place later is never called.
const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { api } from "../../src/api/client";
import { startHeartbeat, takeToken } from "../../src/features/session/session";

const TOKEN = "abcDEF123_-xyz";

beforeEach(() => {
  window.sessionStorage.clear();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => Response.json([]));
});

afterEach(() => {
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

describe("the API client", () => {
  it("sends the token as a header, never in the address", async () => {
    window.history.replaceState(null, "", `/#t=${TOKEN}`);
    takeToken();
    await api.GET("/api/recordings");
    const request = fetchMock.mock.calls[0]?.[0];
    expect(request?.headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(request?.url).not.toContain(TOKEN);
  });

  it("sends no Authorization header at all when there is no token", async () => {
    window.history.replaceState(null, "", "/");
    takeToken();
    await api.GET("/api/recordings");
    expect(fetchMock.mock.calls[0]?.[0].headers.has("Authorization")).toBe(false);
  });
});

describe("startHeartbeat", () => {
  it("beats at once, then every 15 seconds, until stopped", async () => {
    vi.useFakeTimers();
    window.history.replaceState(null, "", `/#t=${TOKEN}`);
    takeToken();
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
    const stop = startHeartbeat();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const first = fetchMock.mock.calls[0]?.[0];
    expect(new URL(first?.url ?? "").pathname).toBe("/api/heartbeat");
    expect(first?.method).toBe("POST");
    expect(first?.headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    await vi.advanceTimersByTimeAsync(45_000);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

describe("a hidden tab (#204)", () => {
  function setVisibility(state: DocumentVisibilityState) {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
    document.dispatchEvent(new Event("visibilitychange"));
  }

  afterEach(() => {
    Reflect.deleteProperty(document, "visibilityState");
  });

  it("beats the moment it comes back into view, not at its next slowed tick", async () => {
    vi.useFakeTimers();
    window.history.replaceState(null, "", `/#t=${TOKEN}`);
    takeToken();
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
    const stop = startHeartbeat();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(5_000);
    // Going out of view sends nothing of its own.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new URL(fetchMock.mock.calls[1]?.[0].url ?? "").pathname).toBe("/api/heartbeat");
    stop();
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
