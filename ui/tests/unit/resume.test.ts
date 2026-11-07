import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created.
const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { keepPlayhead, resumeAt, SAVE_EVERY_S } from "../../src/features/player/resume";
import { takeToken } from "../../src/features/session/session";

const puts = () =>
  fetchMock.mock.calls.map(([request]) => request).filter((r) => r.method === "PUT" && new URL(r.url).pathname === "/api/recordings/4/playhead");

/** A media element whose time and paused state a test can set: jsdom plays nothing. */
function media(): HTMLMediaElement & { time: number; stopped: boolean } {
  const audio = document.createElement("audio") as HTMLMediaElement & { time: number; stopped: boolean };
  audio.time = 0;
  audio.stopped = true;
  Object.defineProperty(audio, "currentTime", { get: () => audio.time, set: (t: number) => (audio.time = t), configurable: true });
  Object.defineProperty(audio, "paused", { get: () => audio.stopped, configurable: true });
  return audio;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/#t=a-token");
  takeToken();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => Response.json({}));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resumeAt (#69)", () => {
  it("is where the recording was left, except at either end or when never played", () => {
    expect(resumeAt(null, 100)).toBeNull();
    expect(resumeAt(0, 100)).toBeNull();
    expect(resumeAt(1.5, 100)).toBeNull();
    expect(resumeAt(42, 100)).toBe(42);
    expect(resumeAt(99, 100)).toBeNull();
    // Before the media says how long it is, the row's number is trusted.
    expect(resumeAt(42, Number.NaN)).toBe(42);
  });
});

describe("keepPlayhead (#69)", () => {
  it("writes on pause, every SAVE_EVERY_S of play and on pagehide, and never the same time twice", async () => {
    const audio = media();
    const forget = keepPlayhead(4, audio);
    audio.stopped = false;
    audio.time = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(puts()).toHaveLength(0);
    audio.time = SAVE_EVERY_S + 2;
    audio.dispatchEvent(new Event("timeupdate"));
    await vi.waitFor(() => expect(puts()).toHaveLength(1));
    expect(await puts()[0]?.json()).toEqual({ seconds: SAVE_EVERY_S + 2 });
    expect(puts()[0]?.headers.get("Authorization")).toBe("Bearer a-token");
    // Paused at the time already kept: nothing to write.
    audio.stopped = true;
    audio.dispatchEvent(new Event("pause"));
    expect(puts()).toHaveLength(1);
    audio.time = 20;
    audio.dispatchEvent(new Event("pause"));
    await vi.waitFor(() => expect(puts()).toHaveLength(2));
    audio.time = 25;
    window.dispatchEvent(new Event("pagehide"));
    await vi.waitFor(() => expect(puts()).toHaveLength(3));
    forget();
    audio.time = 30;
    audio.dispatchEvent(new Event("pause"));
    expect(puts()).toHaveLength(3);
  });

  it("says a failure in the console and nowhere else", async () => {
    const warned = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    fetchMock.mockImplementation(async () => Response.json({ error: "LibraryError", message: "gone", request: "x" }, { status: 500 }));
    const audio = media();
    const forget = keepPlayhead(4, audio);
    audio.time = 20;
    audio.dispatchEvent(new Event("pause"));
    await vi.waitFor(() => expect(warned).toHaveBeenCalled());
    forget();
  });
});
