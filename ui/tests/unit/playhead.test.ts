import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HIGHLIGHT, Playhead } from "../../src/features/player/playhead";
import {
  read,
  type Sentence,
  type TranscriptDoc,
  wordAtOffset,
  wordAtTime,
} from "../../src/features/transcript/document";
import { offsetAtPoint } from "../../src/lib/offsetAtPoint";
import { syntheticTranscript } from "../perf/fixture";
import { type FakeHighlight, installHighlights, painted } from "./highlights";

// jsdom has Range but lays nothing out, so Range has no geometry methods at
// all; each test spies on these placeholders to say where the text is.
Range.prototype.getClientRects ??= () => [] as unknown as DOMRectList;
Range.prototype.getBoundingClientRect ??= () => new DOMRect();

function sentence(start: number, words: string[], step = 0.5): Sentence {
  const tokens = words.map((w, i) => ({ t: start + i * step, w }));
  return { start, end: start + words.length * step, text: words.join(""), tokens };
}

function doc(sentences: Sentence[]): TranscriptDoc {
  return { audio: "a.wav", model: "m", sentences };
}

describe("wordAtTime", () => {
  const reading = read(doc([sentence(1, [" one", " two"]), sentence(5, [" three"])]));

  it.each([
    [0.5, -1], // before the first word
    [1, 0],
    [1.49, 0],
    [1.5, 1], // a word ends where the next starts
    [1.99, 1],
    [2, -1], // the sentence's end closes its last word; the pause has none
    [5.2, 2],
    [99, -1],
  ])("at %s s is word %s", (seconds, word) => {
    expect(wordAtTime(reading.words, seconds)).toBe(word);
  });

  it("finds the right word an hour in, on the 1,038-sentence fixture", () => {
    const { words } = read(syntheticTranscript());
    for (const seconds of [3600, 3600.13, 3601.7, 6000]) {
      // The slow way: the last word starting at or before the time, if it is still being said.
      let expected = -1;
      for (let i = 0; i < words.start.length; i += 1) {
        if ((words.start[i] ?? 0) <= seconds) expected = i;
      }
      if (expected >= 0 && seconds >= (words.end[expected] ?? 0)) expected = -1;
      expect(wordAtTime(words, seconds)).toBe(expected);
      expect(expected).toBeGreaterThan(5_000);
    }
  });
});

describe("wordAtOffset", () => {
  const reading = read(doc([sentence(0, [" See", " this", " column."]), sentence(1.5, [" Next."])]));

  it("maps every character of a paragraph to the word it is in", () => {
    const text = reading.turns[0]?.text ?? "";
    expect(text).toBe(" See this column. Next.");
    const words = Array.from(text, (_, offset) => wordAtOffset(reading, 0, offset));
    expect(words.join("")).toBe("00001111122222222333333".slice(0, text.length));
  });

  it("is -1 for a paragraph that does not exist", () => {
    expect(wordAtOffset(reading, 5, 0)).toBe(-1);
  });
});

describe("offsetAtPoint", () => {
  let p: HTMLParagraphElement;
  let text: Text;

  beforeEach(() => {
    document.body.innerHTML = '<article><p data-turn="3"> See this</p><h2>Speaker 1</h2></article>';
    p = document.querySelector("p") as HTMLParagraphElement;
    text = p.firstChild as Text;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  // jsdom lays nothing out, so each test says where the characters are: one
  // 10 px box per character on one line.
  function layOut() {
    vi.spyOn(Range.prototype, "getClientRects").mockImplementation(function (this: Range) {
      const left = this.startOffset * 10;
      return [new DOMRect(left, 0, 10, 20)] as unknown as DOMRectList;
    });
  }

  afterEach(() => vi.restoreAllMocks());

  it("uses caretPositionFromPoint when the browser has it", () => {
    layOut();
    const doc = {
      createRange: () => document.createRange(),
      caretPositionFromPoint: (x: number) => ({ offsetNode: text, offset: Math.round(x / 10) }),
    };
    // x = 32 is inside character 3 ("e" of "See"); the nearest gap is 3.
    expect(offsetAtPoint({ clientX: 32, clientY: 5 }, doc)).toEqual({ turn: 3, offset: 3 });
  });

  it("falls back to caretRangeFromPoint, as Safari before 26.2 needs", () => {
    layOut();
    const doc = {
      createRange: () => document.createRange(),
      caretRangeFromPoint: (x: number) => {
        const range = document.createRange();
        range.setStart(text, Math.round(x / 10));
        return range;
      },
    };
    expect(offsetAtPoint({ clientX: 52, clientY: 5 }, doc)).toEqual({ turn: 3, offset: 5 });
  });

  it("counts a click on the right half of a word's last letter as that letter, not the next word's space", () => {
    layOut();
    // Character 3 ("e") spans 30 to 40. A click at 38 rounds to the gap at 4,
    // which is the space opening " this".
    const doc = {
      createRange: () => document.createRange(),
      caretPositionFromPoint: (x: number) => ({ offsetNode: text, offset: Math.round(x / 10) }),
    };
    expect(offsetAtPoint({ clientX: 38, clientY: 5 }, doc)).toEqual({ turn: 3, offset: 3 });
  });

  it("is null off the transcript's paragraphs", () => {
    const heading = document.querySelector("h2")?.firstChild as Text;
    const doc = {
      createRange: () => document.createRange(),
      caretPositionFromPoint: () => ({ offsetNode: heading, offset: 1 }),
    };
    expect(offsetAtPoint({ clientX: 0, clientY: 0 }, doc)).toBeNull();
    expect(offsetAtPoint({ clientX: 0, clientY: 0 }, { createRange: () => document.createRange() })).toBeNull();
  });
});

describe("Playhead", () => {
  let registry: Map<string, FakeHighlight>;
  const reading = read(doc([sentence(0, [" See", " this", " col", "umn."]), sentence(9, [" Next."])]));
  let media: { currentTime: number };
  let texts: Text[];

  beforeEach(() => {
    registry = installHighlights();
    document.body.innerHTML = reading.turns.map((t, i) => `<p data-turn="${i}">${t.text}</p>`).join("");
    texts = Array.from(document.querySelectorAll("p"), (p) => p.firstChild as Text);
    media = { currentTime: 0 };
    vi.spyOn(Range.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 300, 10, 20));
    vi.spyOn(window, "scrollBy").mockImplementation(() => undefined);
  });

  afterEach(() => vi.restoreAllMocks());

  function playhead(onFollowing = vi.fn()) {
    return new Playhead({ media: media as HTMLMediaElement, reading, texts, onFollowing });
  }

  it("paints the word being said, without the space before it", () => {
    const head = playhead();
    media.currentTime = 1.1;
    head.paint();
    expect(painted(registry, HIGHLIGHT)).toEqual(["column."]);
    media.currentTime = 9.1;
    head.paint();
    expect(painted(registry, HIGHLIGHT)).toEqual(["Next."]);
    media.currentTime = 5;
    head.paint();
    expect(painted(registry, HIGHLIGHT)).toEqual([]);
  });

  it("scrolls a word below the band into view while following, and not after the reader scrolls away", () => {
    const onFollowing = vi.fn();
    const head = playhead(onFollowing);
    // The word's box is at 900 px, below 75% of jsdom's 768 px window.
    vi.mocked(Range.prototype.getBoundingClientRect).mockReturnValue(new DOMRect(0, 900, 10, 20));
    media.currentTime = 0.6;
    head.paint();
    expect(window.scrollBy).toHaveBeenCalledTimes(1);
    head.unfollow();
    expect(onFollowing).toHaveBeenLastCalledWith(false);
    media.currentTime = 1.1;
    head.paint();
    expect(window.scrollBy).toHaveBeenCalledTimes(1);
    head.follow();
    expect(onFollowing).toHaveBeenLastCalledWith(true);
    expect(window.scrollBy).toHaveBeenCalledTimes(2);
  });

  it("leaves the view alone while the word is inside the band", () => {
    const head = playhead();
    media.currentTime = 0.6;
    head.paint();
    expect(window.scrollBy).not.toHaveBeenCalled();
  });

  it("unregisters its highlight when disposed", () => {
    const head = playhead();
    expect(registry.has(HIGHLIGHT)).toBe(true);
    head.dispose();
    expect(registry.has(HIGHLIGHT)).toBe(false);
  });
});
