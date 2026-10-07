import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created.
const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { currentError, dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import {
  GAP_S,
  parseTranscript,
  read,
  type Sentence,
  speakerName,
  type TranscriptDoc,
} from "../../src/features/transcript/document";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import { TranscriptView } from "../../src/features/transcript/TranscriptView";
import { SHAPE, syntheticTranscript } from "../perf/fixture";
import { installHighlights } from "./highlights";

function sentence(start: number, words: string[], extra: Partial<Sentence> = {}): Sentence {
  const tokens = words.map((w, i) => ({ t: start + i * 0.3, w }));
  return { start, end: start + words.length * 0.3, text: words.join(""), tokens, ...extra };
}

function doc(sentences: Sentence[], speakers?: string[]): TranscriptDoc {
  return { audio: "a.wav", model: "m", sentences, ...(speakers ? { speakers } : {}) };
}

function paragraphs(container: HTMLElement): HTMLParagraphElement[] {
  return Array.from(container.querySelectorAll("article p"));
}

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

describe("TranscriptView over #108's 1,038-sentence fixture", () => {
  const fixture = syntheticTranscript();
  const reading = read(fixture);

  it("draws one <p> per speaker turn, with no element inside any of them", () => {
    const { container } = render(<TranscriptView reading={reading} />);
    const ps = paragraphs(container);
    expect(ps).toHaveLength(SHAPE.turns);
    expect(ps.every((p) => p.children.length === 0 && p.childNodes.length === 1)).toBe(true);
  });

  it("draws each paragraph as exactly its sentences' tokens joined", () => {
    const { container } = render(<TranscriptView reading={reading} />);
    const expected: string[] = [];
    let speaker: number | null = null;
    for (const s of fixture.sentences) {
      const joined = s.tokens.map((t) => t.w).join("");
      if (expected.length === 0 || s.speaker !== speaker) expected.push(joined);
      else expected[expected.length - 1] += joined;
      speaker = s.speaker;
    }
    expect(paragraphs(container).map((p) => p.textContent)).toEqual(expected);
  });

  it("knows every word's place in its paragraph", () => {
    const { words, turns } = reading;
    let checked = 0;
    for (let i = 0; i < words.start.length; i += 1) {
      const text = turns[words.turn[i] ?? -1]?.text ?? "";
      const word = text.slice(words.offset[i], (words.offset[i] ?? 0) + (words.length[i] ?? 0));
      expect(word.length).toBeGreaterThan(0);
      // Each word opens at the turn's start or with whitespace, and the next one
      // starts exactly where it stops.
      if (words.offset[i] !== 0) expect(word).toMatch(/^\s/);
      checked += 1;
    }
    expect(checked).toBe(words.start.length);
    expect(checked).toBeGreaterThan(SHAPE.sentences);
  });
});

describe("read", () => {
  it("draws the tokens, not `text`, where the two disagree", () => {
    // A chunk-seam sentence: text and its tokens differ (#106).
    const seam = sentence(0, [" assigned", " the", " the", " role"], {
      text: " assigned the role to the",
    });
    const { container } = render(<TranscriptView reading={read(doc([seam]))} />);
    expect(paragraphs(container).map((p) => p.textContent)).toEqual([" assigned the the role"]);
  });

  it("joins sub-word tokens into one word, ending where the next word starts", () => {
    const { words, turns } = read(doc([sentence(10, [" See", " col", "umn", " here", "."])]));
    const text = turns[0]?.text ?? "";
    const spelled = Array.from(words.offset, (o, i) => text.slice(o, o + (words.length[i] ?? 0)));
    expect(spelled).toEqual([" See", " column", " here."]);
    expect(Array.from(words.start)).toEqual([10, 10.3, 10.9]);
    // The last word of a sentence ends at the sentence's end (#60 step 6).
    expect(Array.from(words.end)).toEqual([10.3, 10.9, 11.5]);
  });

  it("counts offsets in the drawn string's own units, so an emoji does not shift the next word", () => {
    const { words, turns } = read(doc([sentence(0, [" 🙂", " after", " that"])]));
    const text = turns[0]?.text ?? "";
    // "🙂" is one code point (the file's charOffset unit) and two UTF-16 units.
    expect(text.slice(words.offset[1], (words.offset[1] ?? 0) + (words.length[1] ?? 0))).toBe(" after");
    expect(words.offset[1]).toBe(3);
  });

  it("without speaker labels, breaks a paragraph only at a pause longer than GAP_S", () => {
    const a = sentence(0, [" one"]);
    const b = sentence(a.end + GAP_S / 2, [" two"]);
    const c = sentence(b.end + GAP_S * 2, [" three"]);
    expect(read(doc([a, b, c])).turns.map((t) => t.text)).toEqual([" one two", " three"]);
  });

  it("with speaker labels, breaks at every change of speaker and at no pause", () => {
    const a = sentence(0, [" one"], { speaker: 0 });
    const b = sentence(30, [" two"], { speaker: 0 });
    const c = sentence(30.6, [" three"], { speaker: 1 });
    const reading = read(doc([a, b, c], ["SPEAKER_00", "SPEAKER_01"]));
    expect(reading.turns.map((t) => [t.speaker, t.text])).toEqual([
      [0, " one two"],
      [1, " three"],
    ]);
  });

  it("keeps the words of a sentence that has text and no tokens", () => {
    const empty: Sentence = { start: 4, end: 6, text: " no tokens here", tokens: [] };
    const { turns, words } = read(doc([empty]));
    expect(turns.map((t) => t.text)).toEqual([" no tokens here"]);
    expect(Array.from(words.start)).toEqual([4]);
  });

  it("numbers diarizer speakers by their place in the list and leaves other names alone", () => {
    expect(speakerName(["SPEAKER_00", "SPEAKER_01", "Moiz"], 1)).toBe("Speaker 2");
    expect(speakerName(["SPEAKER_00", "SPEAKER_01", "Moiz"], 2)).toBe("Moiz");
    // senko can start at 01: two speakers are still Speaker 1 and Speaker 2.
    expect(speakerName(["SPEAKER_01", "SPEAKER_02"], 0)).toBe("Speaker 1");
    expect(speakerName(["SPEAKER_01", "SPEAKER_02"], 1)).toBe("Speaker 2");
    expect(speakerName(["SPEAKER_00"], null)).toBeNull();
  });
});

describe("parseTranscript", () => {
  it.each([
    [null, "not a JSON object"],
    [{ sentences: "x" }, "no `sentences` list"],
    [{ sentences: [{ start: 0, end: 1, text: "", tokens: [{ t: "0", w: "a" }] }] }, "token of sentence 0"],
  ])("refuses %j, saying why", (json, why) => {
    expect(() => parseTranscript(json)).toThrow(why);
  });
});

describe("TranscriptPage", () => {
  const RECORDING = {
    id: 2,
    path: "/Users/me/Recordings/review.m4a",
    size_bytes: 10,
    duration_s: 12,
    content_id: "c",
    audio_codec: "aac",
    video_codec: null,
    first_seen: "2026-09-20T17:00:00+00:00",
    missing: false,
    transcripts: [
      {
        id: 7,
        finished_at: "2026-09-20T17:05:00+00:00",
        engine: "parakeet",
        model: "mlx-community/parakeet-tdt-0.6b-v3",
        diarized: false,
        speaker_count: null,
        mark_count: null,
        language: null,
      },
    ],
  };

  beforeEach(() => {
    // The page mounts the player, whose playhead paints with the Highlight API
    // and whose waveform watches its own size and the colour scheme, none of
    // which jsdom has.
    installHighlights();
    globalThis.ResizeObserver ??= class {
      observe() {}
      disconnect() {}
      unobserve() {}
    };
    window.matchMedia ??= () =>
      ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
    window.history.replaceState(null, "", "/?recording=2&transcript=7#t=a-token");
    takeToken();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/recordings") return Response.json([RECORDING]);
      if (path === "/api/transcripts/7") {
        return Response.json(doc([sentence(0, [" Hello", " there."])]));
      }
      if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3, -5, 5]));
      // Its tokens have no `e`, so the server says it cannot be edited (#66).
      if (path === "/api/transcripts/7/edits") {
        return Response.json(
          { error: "TranscriptUnusable", message: "sentence 0, token 0 has no end time `e`.", request: path },
          { status: 422 },
        );
      }
      return Response.json({ detail: "Not Found" }, { status: 404 });
    });
  });

  it("opens the transcript under its recording's name, with the token on both requests", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    expect(await screen.findByText(" Hello there.", { normalizer: (s) => s })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "review.m4a" })).toBeTruthy();
    // Speaker turns are list items under that one heading, not headings of their own.
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getAllByRole("listitem").length).toBeGreaterThan(0);
    // The library, the transcript, its edit list and the waveform; the
    // recording itself is the <audio> element's own request, with the token in
    // its query (#59).
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    const sent = fetchMock.mock.calls.map(([request]) => request.headers.get("Authorization"));
    expect(sent).toEqual(["Bearer a-token", "Bearer a-token", "Bearer a-token", "Bearer a-token"]);
    // A transcript without word ends reads, and says why it cannot be edited.
    expect(screen.getByRole("note").textContent).toContain("cannot be edited");
    expect(document.querySelector("audio")?.getAttribute("src")).toBe("/api/recording/2/media?t=a-token");
    expect(currentError()).toBeNull();
  });

  it("shows the error dialog when the library has no such transcript", async () => {
    render(<TranscriptPage recording={2} transcript={8} />);
    expect(await screen.findByText("This transcript could not be opened.")).toBeTruthy();
    expect(currentError()?.error).toBe("HTTP 404");
  });
});
