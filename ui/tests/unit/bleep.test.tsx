// Reviewing the words to bleep in the app (#84).
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import {
  fades,
  fadesInWebAudio,
  gainAt,
  MUTE_FADE_S,
  MuteGate,
  type Route,
  spanReached,
} from "../../src/features/bleep/liveMute";
import { atLabel } from "../../src/features/bleep/matches";
import { currentError, dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import type { Content, Item } from "../../src/lib/editOps";
import { installHighlights, painted } from "./highlights";
import { choose, openBleepPanel } from "./menus";

describe("spanReached", () => {
  const spans = [[1, 2], [3, 3.5]] as const;
  it("finds the span a stretch of time reaches into, or -1", () => {
    expect(spanReached(spans, 0.5, 0.9)).toBe(-1);
    expect(spanReached(spans, 0.99, 1.01)).toBe(0);
    expect(spanReached(spans, 1.5, 1.5)).toBe(0);
    expect(spanReached(spans, 2, 2.9)).toBe(-1);
    expect(spanReached(spans, 3.4, 3.4)).toBe(1);
    expect(spanReached([], 1, 2)).toBe(-1);
  });
});

describe("MuteGate in WebKit, which switches muted on each frame", () => {
  function media() {
    return { currentTime: 0, paused: false, playbackRate: 1, muted: false } as unknown as HTMLMediaElement;
  }

  it("is how WebKit mutes, and only WebKit", () => {
    expect(fadesInWebAudio("Apple Computer, Inc.")).toBe(false);
    expect(fadesInWebAudio("Google Inc.")).toBe(true);
    expect(fadesInWebAudio("")).toBe(true);
  });

  it("mutes from the frame before a span and unmutes once past it", () => {
    const element = media();
    const gate = new MuteGate(element, null);
    gate.setSpans([[1, 2]]);
    gate.update(0.9);
    expect(element.muted).toBe(false);
    // One 60 Hz frame before the span: the next frame would be inside it.
    gate.update(0.99);
    expect(element.muted).toBe(true);
    gate.update(1.5);
    expect(element.muted).toBe(true);
    gate.update(2.0);
    expect(element.muted).toBe(false);
  });

  it("leaves a person's own mute alone, and never undoes it", () => {
    const element = media();
    element.muted = true;
    const gate = new MuteGate(element, null);
    gate.setSpans([[1, 2]]);
    gate.update(1.5);
    gate.update(2.5);
    expect(element.muted).toBe(true);
  });

  it("gives the sound back when its spans go, and when it is put away", () => {
    const element = media();
    const gate = new MuteGate(element, null);
    gate.setSpans([[0, 2]]);
    expect(element.muted).toBe(true);
    gate.setSpans([]);
    expect(element.muted).toBe(false);
    gate.setSpans([[0, 2]]);
    gate.dispose();
    expect(element.muted).toBe(false);
  });
});

describe("gainAt", () => {
  it("is the render's raised cosine: 1 a fade away, 0.5 halfway, 0 across the span", () => {
    const spans = [[1, 2]] as const;
    const half = MUTE_FADE_S / 2;
    expect(gainAt(spans, 0.9)).toBe(1);
    expect(gainAt(spans, 1 - MUTE_FADE_S)).toBe(1);
    expect(gainAt(spans, 1 - half)).toBeCloseTo(0.5, 9);
    // dsj/media.py `_silence` at a quarter of the fade: (1 - cos(pi * 0.75)) / 2.
    expect(gainAt(spans, 1 - 0.75 * MUTE_FADE_S)).toBeCloseTo((1 - Math.cos(Math.PI * 0.75)) / 2, 9);
    expect(gainAt(spans, 1)).toBe(0);
    expect(gainAt(spans, 1.5)).toBe(0);
    expect(gainAt(spans, 2)).toBe(0);
    expect(gainAt(spans, 2 + half)).toBeCloseTo(0.5, 9);
    expect(gainAt(spans, 2 + MUTE_FADE_S)).toBe(1);
  });

  it("joins fades that meet, and multiplies them as a render does", () => {
    // The fade back after the first span overlaps the fade out before the next.
    expect(fades([[1, 2], [2.004, 3]])).toEqual([
      [1 - MUTE_FADE_S, 1],
      [2.004 - MUTE_FADE_S, 2 + MUTE_FADE_S],
      [3, 3 + MUTE_FADE_S],
    ]);
    expect(gainAt([[1, 2], [2.004, 3]], 2.002)).toBeCloseTo(
      ((1 - Math.cos(Math.PI * 0.4)) / 2) * ((1 - Math.cos(Math.PI * 0.4)) / 2),
      9,
    );
  });
});

describe("MuteGate through Web Audio", () => {
  type Call = [string, ...unknown[]];

  /** A media element and a Web Audio route that write down what is asked of them. */
  function rig(currentTime = 0.9, paused = false) {
    const element = { currentTime, paused, playbackRate: 1, muted: false, isConnected: true };
    const calls: Call[] = [];
    const clock = { currentTime: 10, state: "running" as AudioContextState };
    let made = 0;
    let released = 0;
    const route: Route = {
      context: { ...clock, get currentTime() { return clock.currentTime; }, resume: () => Promise.resolve() },
      gain: {
        cancelScheduledValues: (at: number) => (calls.push(["cancel", at]), undefined as unknown as AudioParam),
        setValueAtTime: (value: number, at: number) => (calls.push(["set", value, at]), undefined as unknown as AudioParam),
        setValueCurveAtTime: (values: Iterable<number>, at: number, length: number) => (
          calls.push(["curve", Array.from(values), at, length]), undefined as unknown as AudioParam
        ),
      },
      release: () => {
        released += 1;
      },
    };
    const gate = new MuteGate(element as unknown as HTMLMediaElement, () => {
      made += 1;
      return route;
    });
    return { element, calls, clock, gate, made: () => made, released: () => released };
  }

  function curves(calls: Call[]) {
    return calls.filter((c) => c[0] === "curve").map(([, values, at, length]) => ({
      values: values as number[],
      at: at as number,
      length: length as number,
    }));
  }

  it("fades out over the 5 ms before a span and back in over the 5 ms after it, on the audio clock", () => {
    const { calls, gate } = rig(0.9);
    gate.setSpans([[1, 2]]);
    // Now on the audio clock is 10 s, and 0.9 s of the recording.
    expect(calls.slice(0, 2)).toEqual([
      ["cancel", 10],
      ["set", 1, 10],
    ]);
    const [out, back] = curves(calls);
    expect(out?.at).toBeCloseTo(10 + (1 - MUTE_FADE_S - 0.9), 9);
    expect(out?.length).toBeCloseTo(MUTE_FADE_S, 9);
    expect(out?.values[0]).toBe(1);
    expect(out?.values[16]).toBeCloseTo(0.5, 6);
    expect(out?.values.at(-1)).toBe(0);
    expect(back?.at).toBeCloseTo(10 + (2 - 0.9), 9);
    expect(back?.length).toBeCloseTo(MUTE_FADE_S, 9);
    expect(back?.values[0]).toBe(0);
    expect(back?.values.at(-1)).toBe(1);
    expect(curves(calls)).toHaveLength(2);
  });

  it("schedules nothing again while both clocks agree, and starts again from a seek", () => {
    const { calls, clock, element, gate } = rig(0.9);
    gate.setSpans([[1, 2]]);
    calls.length = 0;
    clock.currentTime = 10.5;
    element.currentTime = 1.401;
    gate.update(element.currentTime);
    expect(calls).toEqual([]);
    // A seek back: what was scheduled goes, and the fade out is due again.
    clock.currentTime = 10.6;
    element.currentTime = 0.5;
    gate.update(element.currentTime);
    expect(calls.slice(0, 2)).toEqual([
      ["cancel", 10.6],
      ["set", 1, 10.6],
    ]);
    expect(curves(calls)[0]?.at).toBeCloseTo(10.6 + (1 - MUTE_FADE_S - 0.5), 9);
  });

  it("moves the schedule by the median of eight readings that stay out, and not by one", () => {
    const { calls, clock, element, gate } = rig(0.5);
    gate.setSpans([[1, 2]]);
    calls.length = 0;
    // The recording's clock reads 5 ms further on than the schedule says, frame after frame,
    // as after a start whose last stalled frame set the schedule.
    for (let i = 1; i <= 7; i++) {
      clock.currentTime = 10 + i / 60;
      element.currentTime = 0.5 + i / 60 + 0.005;
      gate.update(element.currentTime);
    }
    expect(calls).toEqual([]);
    clock.currentTime = 10 + 8 / 60;
    element.currentTime = 0.5 + 8 / 60 + 0.005;
    gate.update(element.currentTime);
    expect(calls.slice(0, 2)).toEqual([
      ["cancel", 10 + 8 / 60],
      ["set", 1, 10 + 8 / 60],
    ]);
    // The fade out comes 5 ms sooner on the audio clock than first scheduled.
    expect(curves(calls)[0]?.at).toBeCloseTo(10 + (1 - MUTE_FADE_S - 0.5) - 0.005, 9);
  });

  it("starts again at once when the recording's clock jumps", () => {
    const { calls, clock, element, gate } = rig(0.5);
    gate.setSpans([[1, 2]]);
    calls.length = 0;
    // A stall of two frames on the audio clock, none on the recording's: noise, as yet.
    clock.currentTime = 10 + 2 / 60;
    gate.update(element.currentTime);
    expect(calls).toEqual([]);
    clock.currentTime = 10.1;
    gate.update(element.currentTime);
    expect(calls.slice(0, 2)).toEqual([
      ["cancel", 10.1],
      ["set", 1, 10.1],
    ]);
    expect(curves(calls)[0]?.at).toBeCloseTo(10.1 + (1 - MUTE_FADE_S - 0.5), 9);
  });

  it("plays a fade twice as fast at 2x", () => {
    const { calls, element, gate } = rig(0.9);
    element.playbackRate = 2;
    gate.setSpans([[1, 2]]);
    const [out] = curves(calls);
    expect(out?.at).toBeCloseTo(10 + (1 - MUTE_FADE_S - 0.9) / 2, 9);
    expect(out?.length).toBeCloseTo(MUTE_FADE_S / 2, 9);
  });

  it("starting halfway through a fade, goes on from where the fade is", () => {
    const { calls, gate } = rig(1 - MUTE_FADE_S / 2);
    gate.setSpans([[1, 2]]);
    expect(calls.some((c) => c[0] === "set")).toBe(false);
    const [out] = curves(calls);
    expect(out?.at).toBe(10);
    expect(out?.length).toBeCloseTo(MUTE_FADE_S / 2, 9);
    expect(out?.values[0]).toBeCloseTo(0.5, 6);
    expect(out?.values.at(-1)).toBe(0);
  });

  it("takes no sound into Web Audio until a span is played over", () => {
    const paused = rig(0.9, true);
    paused.gate.setSpans([[1, 2]]);
    expect(paused.made()).toBe(0);
    const nothing = rig(0.9);
    nothing.gate.setSpans([]);
    expect(nothing.made()).toBe(0);
  });

  it("gives the sound back when put away, and lets go of an element that left the page", () => {
    const { calls, clock, gate, released } = rig(1.5);
    gate.setSpans([[1, 2]]);
    clock.currentTime = 11;
    gate.dispose();
    expect(calls.slice(-2)).toEqual([
      ["cancel", 11],
      ["set", 1, 11],
    ]);
    expect(released()).toBe(0);
    const gone = rig(1.5);
    gone.gate.setSpans([[1, 2]]);
    gone.element.isConnected = false;
    gone.gate.dispose();
    expect(gone.released()).toBe(1);
  });
});

it("labels a time to the tenth of a second", () => {
  expect(atLabel(65.27)).toBe("1:05.3");
  expect(atLabel(0.04)).toBe("0:00.0");
});

function item(sourceStart: number, length: number, text: string): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence: 0.9 };
}

// " alpha bravo charlie", each word followed by a pause.
const CONTENT: Content = [
  { kind: "paragraph", speaker: null, language: null },
  item(0, 0.3, ""),
  item(0.3, 0.4, " alpha"),
  item(0.7, 0.3, ""),
  item(1.0, 0.4, " bravo"),
  item(1.4, 0.3, ""),
  item(1.7, 0.4, " charlie"),
];

const BRAVO = { start: 4, stop: 5, word: "bravo", entry: "en:bravo", start_s: 1.0, end_s: 1.4 };
const CHARLIE = { start: 6, stop: 7, word: "charlie", entry: "user:charlie", start_s: 1.7, end_s: 2.1 };

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

describe("the words to bleep, on the transcript page", () => {
  let words: string[] = [];
  let listed: (typeof BRAVO)[] = [];
  let registry: ReturnType<typeof installHighlights>;

  beforeEach(() => {
    registry = installHighlights();
    globalThis.ResizeObserver ??= class {
      observe() {}
      disconnect() {}
      unobserve() {}
    };
    window.matchMedia ??= () =>
      ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
    window.history.replaceState(null, "", "/?recording=2&transcript=7#t=a-token");
    takeToken();
    words = [];
    listed = [BRAVO];
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/recordings") {
        return Response.json([
          {
            id: 2, path: "/rec/a.wav", size_bytes: 1, duration_s: 3, content_id: "c", audio_codec: "pcm",
            video_codec: null, first_seen: "x", missing: false, unreadable: null,
            transcripts: [{ id: 7, finished_at: "x", engine: "parakeet", model: "parakeet", diarized: null, speaker_count: null, mark_count: null, language: null }],
          },
        ]);
      }
      if (path === "/api/transcripts/7") return Response.json({ audio: "/rec/a.wav", model: "parakeet", sentences: [] });
      if (path === "/api/transcripts/7/edits") {
        const content = request.method === "PUT" ? ((await request.json()) as { content: Content }).content : CONTENT;
        return Response.json({ content, names: {}, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null });
      }
      if (path === "/api/transcripts/7/matches") {
        return Response.json({ matches: listed, words_searched: 3, lists: ["en", "ur", "hi", "pa"], recall: "recall: x" });
      }
      if (path === "/api/words") {
        const { word } = (await request.json()) as { word: string };
        words.push(word);
        listed = [BRAVO, CHARLIE];
        return Response.json({ entry: "user:charlie", added: true });
      }
      if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
      return Response.json({ detail: "Not Found" }, { status: 404 });
    });
  });

  async function panel(): Promise<HTMLElement> {
    render(<TranscriptPage recording={2} transcript={7} />);
    const section = await openBleepPanel();
    await within(section).findByRole("list", { name: "Matches" });
    return section;
  }

  it("lists each match with its word, time and entry, nothing muted until asked", async () => {
    const section = await panel();
    const row = within(section).getByRole("listitem", { name: "bravo" });
    expect(row.textContent).toContain("0:01.0");
    expect(row.textContent).toContain("en:bravo");
    expect(row.textContent).toContain("dismissed");
    fireEvent.click(within(section).getByRole("button", { name: "Mute all 1" }));
    expect(row.textContent).toContain("muted");
    expect(painted(registry, "dsj-muted")).toEqual(["bravo"]);
  });

  it("badges the menu's Bleep item with the matches Mute all would still mute", async () => {
    const section = await panel();
    const openMenu = async () => {
      act(() => {
        fireEvent.click(screen.getByRole("button", { name: "More" }));
      });
      return screen.findByRole("menuitem", { name: /^Bleep/ });
    };
    const badged = await openMenu();
    expect(badged.textContent).toBe("Bleep1");
    // Bleep again closes the menu; the drawer is already open, and Mute all is in it.
    choose(badged);
    fireEvent.click(within(section).getByRole("button", { name: "Mute all 1" }));
    await vi.waitFor(() => expect(painted(registry, "dsj-muted")).toEqual(["bravo"]));
    expect((await openMenu()).textContent).toBe("Bleep");
  });

  it("dismisses a match and brings it back with one undo each", async () => {
    const section = await panel();
    fireEvent.click(within(section).getByRole("button", { name: "Mute all 1" }));
    fireEvent.click(within(section).getByRole("button", { name: "Dismiss" }));
    expect(painted(registry, "dsj-muted")).toEqual([]);
    act(() => {
      fireEvent.keyDown(document.body, { key: "z", metaKey: true });
    });
    expect(painted(registry, "dsj-muted")).toEqual(["bravo"]);
    act(() => {
      fireEvent.keyDown(document.body, { key: "z", metaKey: true });
    });
    expect(painted(registry, "dsj-muted")).toEqual([]);
    expect(screen.getByRole("button", { name: "Undo" })).toHaveProperty("disabled", true);
  });

  // The menu's export items, with the edit list's PUT held or refused by the test.
  async function exportAfterAMute(putting: Promise<Response>): Promise<string[]> {
    const normal = fetchMock.getMockImplementation();
    const exported: string[] = [];
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/transcripts/7/export/srt") {
        exported.push(path);
        return new Response("1\n", { headers: { "content-type": "text/plain" } });
      }
      if (path === "/api/transcripts/7/edits" && request.method === "PUT") return putting;
      return (normal as (request: Request) => Promise<Response>)(request);
    });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const section = await panel();
    fireEvent.click(within(section).getByRole("button", { name: "Mute all 1" }));
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "More" }));
    });
    choose(await screen.findByRole("menuitem", { name: "Subtitles (SRT)" }));
    return exported;
  }

  it("exports only once the edit list the mute started saving is saved", async () => {
    let answer: (reply: Response) => void = () => undefined;
    const putting = new Promise<Response>((resolve) => {
      answer = resolve;
    });
    const exported = await exportAfterAMute(putting);
    // The save has not come back, so the server's copy is behind the page's: no export yet.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(exported).toEqual([]);
    answer(Response.json({ content: CONTENT, names: {}, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null }));
    await vi.waitFor(() => expect(exported).toEqual(["/api/transcripts/7/export/srt"]));
  });

  it("exports nothing, and says so, when the edit list could not be saved", async () => {
    const exported = await exportAfterAMute(Promise.resolve(Response.json({ detail: "disk full" }, { status: 500 })));
    await vi.waitFor(() => expect(currentError()?.message).toContain("Nothing was exported"));
    expect(exported).toEqual([]);
  });

  it("adds a word to the user's list and mutes what the next pass finds of it", async () => {
    const section = await panel();
    const field = within(section).getByRole("textbox", { name: "A word to add to your list" });
    fireEvent.change(field, { target: { value: "charlie" } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    await within(section).findByRole("listitem", { name: "charlie" });
    await vi.waitFor(() => expect(painted(registry, "dsj-muted")).toEqual(["charlie"]));
    expect(words).toEqual(["charlie"]);
    expect(within(section).getByRole("status").textContent).toContain('Added "charlie"');
    expect(currentError()).toBeNull();
  });

  it("says in words that nothing matched", async () => {
    listed = [];
    render(<TranscriptPage recording={2} transcript={7} />);
    const section = await openBleepPanel();
    expect((await within(section).findByRole("status")).textContent).toBe(
      "No word matched: 3 words searched against the en, ur, hi, pa lists.",
    );
  });
});
