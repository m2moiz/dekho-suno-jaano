import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  applySpeed,
  COOKIE,
  readSpeed,
  saveSpeed,
  SPEEDS,
} from "../../src/features/player/speed";
import { SpeedControl } from "../../src/features/player/SpeedControl";

function clearCookie() {
  document.cookie = `${COOKIE}=; path=/; max-age=0`;
}

beforeEach(clearCookie);
afterEach(() => {
  cleanup();
  clearCookie();
});

describe("the saved speed", () => {
  it("offers half speed to double", () => {
    expect(SPEEDS[0]).toBe(0.5);
    expect(SPEEDS.at(-1)).toBe(2);
  });

  it("is 1 when nothing is saved, and what was saved after that", () => {
    expect(readSpeed()).toBe(1);
    saveSpeed(1.75);
    expect(readSpeed()).toBe(1.75);
  });

  it("is kept in a cookie, not localStorage, so a new dsj ui port still has it", () => {
    saveSpeed(0.5);
    expect(document.cookie).toContain(`${COOKIE}=0.5`);
    expect(window.localStorage.length).toBe(0);
  });

  it("ignores a cookie holding a speed it does not offer", () => {
    document.cookie = `${COOKIE}=3; path=/`;
    expect(readSpeed()).toBe(1);
    document.cookie = `${COOKIE}=fast; path=/`;
    expect(readSpeed()).toBe(1);
  });
});

describe("applySpeed", () => {
  it("sets the rate, the rate a reload falls back to, and natural pitch", () => {
    const audio = document.createElement("audio");
    audio.preservesPitch = false;
    applySpeed(audio, 2);
    expect(audio.playbackRate).toBe(2);
    expect(audio.defaultPlaybackRate).toBe(2);
    expect(audio.preservesPitch).toBe(true);
  });
});

describe("SpeedControl", () => {
  it("starts the recording at the saved speed", () => {
    saveSpeed(1.5);
    const media = createRef<HTMLAudioElement>();
    render(
      <>
        <audio ref={media} />
        <SpeedControl media={media} />
      </>,
    );
    expect(media.current?.playbackRate).toBe(1.5);
    expect(screen.getByRole("combobox", { name: "Playback speed" }).textContent).toContain("1.5×");
  });

  it("plays at the speed picked, and keeps it", async () => {
    const media = createRef<HTMLAudioElement>();
    render(
      <>
        <audio ref={media} />
        <SpeedControl media={media} />
      </>,
    );
    act(() => fireEvent.click(screen.getByRole("combobox", { name: "Playback speed" })));
    const double = await screen.findByRole("option", { name: "2×" });
    // A click alone picks nothing here: Base UI's Select item also wants the
    // pointerdown a real click starts with (tried one event at a time).
    act(() => {
      fireEvent.pointerDown(double, { pointerType: "mouse" });
      fireEvent.click(double);
    });
    expect(media.current?.playbackRate).toBe(2);
    expect(readSpeed()).toBe(2);
  });
});
