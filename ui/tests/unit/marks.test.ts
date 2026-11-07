import { describe, expect, it } from "vitest";

import { wordsOfSpan } from "../../src/features/marks/marks";
import { read } from "../../src/features/transcript/document";
import { MARK_KINDS } from "../../src/registries/markKinds";

const reading = read({
  audio: "a",
  model: "m",
  sentences: [
    { start: 0.2, end: 1.3, text: " alpha bravo charlie", tokens: [{ t: 0.2, w: " alpha", e: 0.5 }, { t: 0.6, w: " bravo", e: 0.9 }, { t: 1.0, w: " charlie", e: 1.3 }] },
    { start: 2.0, end: 2.4, text: " delta", tokens: [{ t: 2.0, w: " delta", e: 2.4 }] },
  ],
});

describe("wordsOfSpan (#67)", () => {
  it("finds the words a stretch of seconds covers, and only them", () => {
    expect(wordsOfSpan(reading.words, 0.6, 1.3)).toEqual([1, 2]);
    expect(wordsOfSpan(reading.words, 0.2, 0.5)).toEqual([0]);
    expect(wordsOfSpan(reading.words, 1.9, 2.5)).toEqual([3]);
  });

  it("is not moved by a millisecond either way, as a re-run can move a token", () => {
    expect(wordsOfSpan(reading.words, 0.605, 1.295)).toEqual([1, 2]);
    expect(wordsOfSpan(reading.words, 0.59, 1.31)).toEqual([1, 2]);
  });

  it("finds nothing in silence", () => {
    expect(wordsOfSpan(reading.words, 1.4, 1.9)).toEqual([]);
  });
});

describe("the mark kinds", () => {
  it("are four, each with its own highlight name and swatch", () => {
    expect(MARK_KINDS.map((k) => k.id)).toEqual(["key", "question", "todo", "quote"]);
    expect(new Set(MARK_KINDS.map((k) => k.highlight)).size).toBe(4);
  });
});
