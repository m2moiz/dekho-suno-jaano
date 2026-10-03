// Reviewing the words to bleep in the app (#84).
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { MuteGate, spanReached } from "../../src/features/bleep/liveMute";
import { atLabel } from "../../src/features/bleep/matches";
import { currentError, dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import type { Content, Item } from "../../src/lib/editOps";
import { installHighlights, painted } from "./highlights";

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

describe("MuteGate", () => {
  function media() {
    return { currentTime: 0, paused: false, playbackRate: 1, muted: false } as unknown as HTMLMediaElement;
  }

  it("mutes from the frame before a span and unmutes once past it", () => {
    const element = media();
    const gate = new MuteGate(element);
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
    const gate = new MuteGate(element);
    gate.setSpans([[1, 2]]);
    gate.update(1.5);
    gate.update(2.5);
    expect(element.muted).toBe(true);
  });

  it("gives the sound back when its spans go, and when it is put away", () => {
    const element = media();
    const gate = new MuteGate(element);
    gate.setSpans([[0, 2]]);
    expect(element.muted).toBe(true);
    gate.setSpans([]);
    expect(element.muted).toBe(false);
    gate.setSpans([[0, 2]]);
    gate.dispose();
    expect(element.muted).toBe(false);
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
        return Response.json({ content, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null });
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
    const section = await screen.findByRole("region", { name: "Words to bleep" });
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
    const section = await screen.findByRole("region", { name: "Words to bleep" });
    expect((await within(section).findByRole("status")).textContent).toBe(
      "No word matched: 3 words searched against the en, ur, hi, pa lists.",
    );
  });
});
