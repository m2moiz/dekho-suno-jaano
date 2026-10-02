import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created. The waveform's request gets a tiny envelope.
vi.hoisted(() => {
  globalThis.fetch = (async () => new Response(new Int8Array([-1, 1]))) as unknown as typeof fetch;
});

import type { RecordingRow } from "../../src/features/library/types";
import { Player } from "../../src/features/player/Player";
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
