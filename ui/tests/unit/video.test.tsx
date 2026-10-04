import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created. The waveform's request gets a tiny envelope.
vi.hoisted(() => {
  globalThis.fetch = (async () => new Response(new Int8Array([-1, 1]))) as unknown as typeof fetch;
});

import { currentError, dismissError } from "../../src/features/errors/appError";
import type { RecordingRow } from "../../src/features/library/types";
import { Player } from "../../src/features/player/Player";
import { PLAYER_HEIGHT } from "../../src/features/player/playhead";
import { COOKIE, readVideoShown, saveVideoShown } from "../../src/features/player/video";
import { read } from "../../src/features/transcript/document";
import { installHighlights } from "./highlights";

function recording(video_codec: string | null): RecordingRow {
  return {
    id: 4,
    path: video_codec === null ? "/r/call.mp3" : "/r/screen.mov",
    size_bytes: 10,
    duration_s: 30,
    content_id: "c",
    audio_codec: "aac",
    video_codec,
    first_seen: "2026-09-20T17:00:00+00:00",
    missing: false,
    unreadable: null,
    transcripts: [],
  };
}

const reading = read({
  audio: "a",
  model: "m",
  sentences: [{ start: 0, end: 1, text: " Hi.", tokens: [{ t: 0, w: " Hi." }] }],
});

function mount(video_codec: string | null) {
  const article = createRef<HTMLElement>();
  return render(
    <>
      <article ref={article}>
        <p data-turn="0"> Hi.</p>
      </article>
      <Player recording={recording(video_codec)} reading={reading} article={article} />
    </>,
  );
}

beforeEach(() => {
  installHighlights();
  globalThis.ResizeObserver ??= class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
  window.matchMedia ??= () =>
    ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
  document.cookie = `${COOKIE}=; path=/; max-age=0`;
});

afterEach(() => {
  cleanup();
  document.cookie = `${COOKIE}=; path=/; max-age=0`;
});

describe("the picture", () => {
  it("is shown unless it was folded away, and the choice is a cookie", () => {
    expect(readVideoShown()).toBe(true);
    saveVideoShown(false);
    expect(document.cookie).toContain(`${COOKIE}=hidden`);
    expect(readVideoShown()).toBe(false);
  });

  it("plays a screen recording in a <video> on the media route, and an audio file in an <audio>", () => {
    const { container, unmount } = mount("h264");
    expect(container.querySelector("video")?.getAttribute("src")).toMatch(/^\/api\/recording\/4\/media\?t=/);
    expect(container.querySelector("audio")).toBeNull();
    unmount();
    const audioOnly = mount(null);
    expect(audioOnly.container.querySelector("video")).toBeNull();
    expect(audioOnly.container.querySelector("audio")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /picture/ })).toBeNull();
  });

  it("folds away without unmounting the element, offers play and the time instead, and remembers", () => {
    const { container } = mount("h264");
    const video = container.querySelector("video");
    act(() => fireEvent.click(screen.getByRole("button", { name: "Hide picture" })));
    expect(container.querySelector("video")).toBe(video);
    expect(video?.parentElement?.className).toContain("hidden");
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(readVideoShown()).toBe(false);
    cleanup();
    mount("h264");
    expect(screen.getByRole("button", { name: "Show picture" })).toBeTruthy();
  });
});

describe("the page's scroll padding (#230)", () => {
  it("is the player bar's height while the player is on the page, and gone after", () => {
    // jsdom lays nothing out and the shared stub never calls back: this one
    // calls back at once, with the bar's measured height made up here.
    const stub = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      private readonly callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
      }
      observe(target: Element) {
        vi.spyOn(target, "getBoundingClientRect").mockReturnValue({ height: 371 } as DOMRect);
        this.callback([], this as unknown as ResizeObserver);
      }
      disconnect() {}
      unobserve() {}
    };
    try {
      const { unmount } = mount("h264");
      expect(document.documentElement.style.getPropertyValue(PLAYER_HEIGHT)).toBe("371px");
      unmount();
      expect(document.documentElement.style.getPropertyValue(PLAYER_HEIGHT)).toBe("");
    } finally {
      globalThis.ResizeObserver = stub;
    }
  });
});

describe("a file the browser will not open", () => {
  function refuse(element: HTMLMediaElement, code: number) {
    Object.defineProperty(element, "error", { configurable: true, value: { code, message: "" } });
    act(() => fireEvent.error(element));
  }

  it("plays a copy of its sound instead, with no error and a word about it (#110)", () => {
    const { container } = mount("av1");
    const video = container.querySelector("video");
    if (video === null) throw new Error("no <video> for a screen recording");
    refuse(video, 4);
    expect(container.querySelector("video")).toBeNull();
    expect(container.querySelector("audio")?.getAttribute("src")).toMatch(
      /^\/api\/recording\/4\/media\?t=.*&sound=true$/,
    );
    expect(screen.getByText(/a copy of its sound is playing/)).toBeTruthy();
    expect(currentError()).toBeNull();
  });

  it("names the failure when even the copy is refused, or the file fails another way", () => {
    const { container } = mount("av1");
    refuse(container.querySelector("video") as HTMLMediaElement, 4);
    refuse(container.querySelector("audio") as HTMLMediaElement, 4);
    expect(currentError()?.message).toContain("the browser cannot play this kind of file");
    act(() => dismissError());
    cleanup();
    const other = mount("h264");
    refuse(other.container.querySelector("video") as HTMLMediaElement, 3);
    expect(currentError()?.message).toContain("the browser could not decode it");
    expect(other.container.querySelector("video")).not.toBeNull();
    act(() => dismissError());
  });
});
