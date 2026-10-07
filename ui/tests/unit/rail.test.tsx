import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  globalThis.fetch = (async () => new Response(new Int8Array([-1, 1, -2, 2]))) as unknown as typeof fetch;
});

import type { RecordingRow } from "../../src/features/library/types";
import { Player, type PlayerControls } from "../../src/features/player/Player";
import { REVIEW_SPEEDS, saveSpeed, stepSpeed } from "../../src/features/player/speed";
import { read } from "../../src/features/transcript/document";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

const recording: RecordingRow = {
  id: 4,
  path: "/r/call.mp3",
  size_bytes: 10,
  duration_s: 30,
  content_id: "c",
  audio_codec: "aac",
  video_codec: null,
  first_seen: "2026-09-20T17:00:00+00:00",
  missing: false,
  unreadable: null,
  transcripts: [],
};

const reading = read({ audio: "a", model: "m", sentences: [{ start: 0, end: 1, text: " Hi.", tokens: [{ t: 0, w: " Hi." }] }] });

beforeEach(() => {
  installHighlights();
  stubMatchMedia();
  document.cookie = "dsj-speed=; max-age=0; path=/";
});
afterEach(cleanup);

describe("the player rail", () => {
  it("is one blue rail with a play button, the time, the waveform and the speed, and no browser audio bar", () => {
    render(<Player recording={recording} reading={reading} />);
    const rail = screen.getByRole("region", { name: "Player" });
    expect(rail.querySelector(".bg-field")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Position" })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Playback speed" })).toBeTruthy();
    expect(document.querySelector("audio")?.hasAttribute("controls")).toBe(false);
  });

  it("moves the position by five seconds an arrow key, thirty with Shift", () => {
    render(<Player recording={recording} reading={reading} />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    Object.defineProperty(audio, "duration", { value: 120 });
    audio.play = () => Promise.resolve();
    const slider = screen.getByRole("slider", { name: "Position" });
    act(() => fireEvent.keyDown(slider, { key: "ArrowRight" }));
    expect(audio.currentTime).toBe(5);
    act(() => fireEvent.keyDown(slider, { key: "ArrowRight", shiftKey: true }));
    expect(audio.currentTime).toBe(35);
    act(() => fireEvent.keyDown(slider, { key: "Home" }));
    expect(audio.currentTime).toBe(0);
  });

  it("starts at the saved speed, and the page can change it through its controls", () => {
    saveSpeed(1.5);
    const controls = createRef<PlayerControls | null>() as { current: PlayerControls | null };
    render(<Player recording={recording} reading={reading} controls={controls} />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    expect(audio.playbackRate).toBe(1.5);
    act(() => controls.current?.setSpeed(0.75));
    expect(audio.playbackRate).toBe(0.75);
    expect(controls.current?.speed()).toBe(0.75);
  });

  it("backs up when told to on resuming", () => {
    const controls = { current: null } as { current: PlayerControls | null };
    render(<Player recording={recording} reading={reading} controls={controls} />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    audio.play = () => Promise.resolve();
    audio.currentTime = 10;
    act(() => controls.current?.toggle(1.5));
    expect(audio.currentTime).toBe(8.5);
  });
});

describe("stepSpeed", () => {
  it("walks Review's four speeds and stops at either end", () => {
    expect(REVIEW_SPEEDS).toEqual([0.75, 1, 1.25, 1.5]);
    expect(stepSpeed(1, 1)).toBe(1.25);
    expect(stepSpeed(1.5, 1)).toBe(1.5);
    expect(stepSpeed(0.75, -1)).toBe(0.75);
    // From a reader speed outside the four, to the nearest one in that direction.
    expect(stepSpeed(2, -1)).toBe(1.5);
    expect(stepSpeed(0.5, 1)).toBe(0.75);
  });
});
