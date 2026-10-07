// Review mode's model (Hashiya spec, Review mode), and Review Focus 2 to 5.
import { describe, expect, it } from "vitest";

import { correction } from "../../src/features/edit/correct";
import {
  counts,
  documentOf,
  entryRange,
  freshSegments,
  likelyErrors,
  mergeWithPrevious,
  passOrder,
  type ReviewDocument,
  resume,
  type Segment,
  segmentText,
  sentenceSpans,
  splitAt,
  step,
  timeLeft,
  wordIndex,
} from "../../src/features/review/model";
import type { Content, Entry, Item } from "../../src/lib/editOps";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}
const para = (speaker: string): Entry => ({ kind: "paragraph", speaker, language: null });

// Three sentences. The third has a word in two pieces, " questi" "on".
const CONTENT: Content = [
  para("SPEAKER_00"),
  item(0, 0.2, "", null),
  item(0.2, 0.3, " alpha"),
  item(0.6, 0.3, " bravo"),
  item(1.0, 0.3, " charlie", 0.2),
  item(1.3, 0.3, " delta"),
  item(1.6, 0.4, "", null),
  para("SPEAKER_01"),
  item(2.0, 0.4, " echo"),
  para("SPEAKER_00"),
  item(3.0, 0.3, " a"),
  item(3.3, 0.2, " questi"),
  item(3.5, 0.1, "on"),
];

const seg = (start: number, end: number, extra: Partial<Segment> = {}): Segment => ({
  start, end, state: "unchecked", flags: [], speaker: null, edited: false, ...extra,
});

describe("segments", () => {
  it("are the list's sentences, from first word to last word's end", () => {
    expect(sentenceSpans(CONTENT)).toEqual([
      { start: 0.2, end: 1.6 },
      { start: 2.0, end: 2.4 },
      { start: 3.0, end: 3.6 },
    ]);
    expect(freshSegments(CONTENT)[0]).toEqual(seg(0.2, 1.6));
  });

  it("know their words and the entries holding them", () => {
    const words = wordIndex(CONTENT);
    expect(entryRange(words, { start: 0.2, end: 1.6 })).toEqual({ start: 2, stop: 6 });
    expect(segmentText(CONTENT, words, { start: 3.0, end: 3.6 })).toBe("a question");
    expect(entryRange(words, { start: 5, end: 6 })).toBeNull();
  });
});

describe("a correction that changes the word count (Review Focus 2)", () => {
  it("keeps the sentence's span, shows the new words, leaves the neighbours, and is not applied twice", () => {
    const words = wordIndex(CONTENT);
    const span = { start: 0.2, end: 1.6 };
    const range = entryRange(words, { start: 1.0, end: 1.3 });
    if (range === null) throw new Error("no charlie");
    const op = correction(CONTENT, range.start, range.stop, "Charles Darwin");
    const after = [...CONTENT.slice(0, op.start), ...op.entries, ...CONTENT.slice(op.stop)];
    const again = wordIndex(after);
    expect(segmentText(after, again, span)).toBe("alpha bravo Charles Darwin delta");
    expect(segmentText(after, again, { start: 2.0, end: 2.4 })).toBe("echo");
    expect(sentenceSpans(after)).toEqual(sentenceSpans(CONTENT));
    // Checking the sentence again finds the stretch's words already as typed
    // (F20): retyping them must leave the list exactly as it was.
    const second = correction(after, op.start, op.start + op.entries.length, "Charles Darwin");
    const twice = [...after.slice(0, second.start), ...second.entries, ...after.slice(second.stop)];
    expect(twice).toEqual(after);
  });
});

describe("splitAt (Review Focus 3)", () => {
  const segments = freshSegments(CONTENT);
  // "alpha bravo charlie delta": alpha 0-5, bravo 6-11, charlie 12-19, delta 20-25.
  it.each([
    [5, 0.6],
    [6, 0.6],
    [8, 0.6],
    [10, 1.0],
    [19, 1.3],
  ])("splits at the word boundary nearest caret %i, at %f s", (caret, at) => {
    const split = splitAt(CONTENT, segments, 0, caret);
    if ("refused" in split) throw new Error(split.refused);
    expect(split.segments.slice(0, 2)).toEqual([seg(0.2, at), seg(at, 1.6)]);
    expect(split.segments).toHaveLength(4);
  });

  it.each([0, 2, 25])("refuses caret %i, which snaps to the sentence's own start or end", (caret) => {
    const split = splitAt(CONTENT, segments, 0, caret);
    expect("refused" in split && split.refused).toMatch(/between two words/);
  });

  it("refuses a one-word sentence, and a word in two pieces is one word", () => {
    expect(splitAt(CONTENT, segments, 1, 2)).toEqual({ refused: "This sentence is one word, so there is nowhere to split it." });
    const pieces = splitAt(CONTENT, segments, 2, 5);
    if ("refused" in pieces) throw new Error(pieces.refused);
    expect(pieces.segments[2]).toEqual(seg(3.0, 3.3));
  });
});

describe("merging", () => {
  it("joins a sentence to the one before, unchecked, keeping both sets of flags", () => {
    const merged = mergeWithPrevious([seg(0.2, 1.6, { state: "checked", flags: ["overlap"] }), seg(2.0, 2.4, { flags: ["unclear"] })], 1);
    expect(merged).toEqual([seg(0.2, 2.4, { flags: ["overlap", "unclear"] })]);
    expect(mergeWithPrevious([seg(0, 1)], 0)).toBeNull();
  });
});

describe("resume (Review Focus 4)", () => {
  const saved = (sha: string, segments: Segment[], cursor = 2.0): ReviewDocument => ({
    version: 1, transcript_sha: sha, review_pass: "every", cursor_s: cursor,
    started_at: "x", updated_at: "x", segments, corrections: [],
  });

  it("starts fresh with no review", () => {
    expect(resume(null, CONTENT, "s1")).toEqual({ segments: freshSegments(CONTENT), cursor: 0, lost: 0 });
  });

  it("takes the saved review as it is when the transcript is the one it was made against, at the same sentence", () => {
    const segments = [seg(0.2, 1.0, { state: "checked" }), seg(1.0, 1.6), seg(2.0, 2.4), seg(3.0, 3.6)];
    expect(resume(saved("s1", segments), CONTENT, "s1")).toEqual({ segments, cursor: 2, lost: 0 });
  });

  it("hands the new sha to the document it saves, so the server accepts the next save", () => {
    const old = [seg(0.2, 1.6, { state: "checked" }), seg(2.0, 2.4), seg(3.0, 3.6)];
    const back = resume(saved("a".repeat(64), old), CONTENT, "b".repeat(64));
    const document = documentOf({ sha: "b".repeat(64), pass: "every", cursorS: 0, startedAt: "x", segments: back.segments, corrections: [] });
    expect(document.transcript_sha).toBe("b".repeat(64));
    expect(document.segments.map((s) => s.state)).toEqual(["checked", "unchecked", "unchecked"]);
  });

  it("transcribed again: keeps what still matches by span, and counts the checked ones that do not", () => {
    // The second sentence moved by 0.03 s, inside SAME_SPAN_S: still the same sentence.
    const old = [seg(0.2, 1.6, { state: "checked", flags: ["overlap"] }), seg(2.0, 2.43, { state: "checked" }), seg(3.0, 3.6, { state: "checked" })];
    const back = resume(saved("old", old), CONTENT, "new");
    expect(back.segments.map((s) => s.state)).toEqual(["checked", "checked", "checked"]);
    expect(back.segments[0]?.flags).toEqual(["overlap"]);
    const moved = [seg(0.2, 1.4, { state: "checked" }), seg(2.0, 2.4, { state: "checked" })];
    const again = resume(saved("old", moved), CONTENT, "new");
    expect(again.segments.map((s) => s.state)).toEqual(["unchecked", "checked", "unchecked"]);
    expect(again.lost).toBe(1);
    expect(again.cursor).toBe(1);
  });
});

describe("passes and likely errors", () => {
  const segments = [seg(0.2, 1.6), seg(2.0, 2.4, { flags: ["cut_off"] }), seg(3.0, 3.6)];
  it("finds unsure words, flags and disagreements", () => {
    const words = wordIndex(CONTENT);
    expect(likelyErrors(CONTENT, words, segments, 0.3, new Set())).toEqual([0, 1]);
    expect(likelyErrors(CONTENT, words, segments, null, new Set([2]))).toEqual([1, 2]);
  });

  it("orders a pass and steps through it", () => {
    expect(passOrder(3, "every", [1])).toEqual([0, 1, 2]);
    expect(passOrder(3, "likely", [0, 2])).toEqual([0, 2]);
    expect(step([0, 2], 0, 1)).toBe(2);
    expect(step([0, 2], 1, 1)).toBe(2);
    expect(step([0, 2], 2, 1)).toBeNull();
    expect(step([0, 2], 2, -1)).toBe(0);
  });

  it("counts what the pass did", () => {
    expect(counts([seg(0, 1, { state: "checked", edited: true }), seg(1, 2, { flags: ["unclear"], speaker: "SPEAKER_01" })])).toEqual({
      checked: 1, total: 2, edited: 1, flagged: 1, reassigned: 1,
    });
  });
});

describe("timeLeft", () => {
  it("says nothing until three checks give a pace, then goes by the median gap", () => {
    expect(timeLeft([0, 10_000], 100)).toBeNull();
    // Gaps of 10 s, 12 s and a 300 s coffee break: the median is 12 s.
    expect(timeLeft([0, 10_000, 22_000, 322_000], 250)).toBe("about 50 min left");
    expect(timeLeft([0, 10_000, 20_000], 600)).toBe("about 1 h 40 min left");
    expect(timeLeft([0, 1000, 2000], 10)).toBe("under a minute left");
  });
});

describe("a 2.5 h call (Review Focus 5)", () => {
  it("builds its 1,500 sentences, their index and their likely errors in under 50 ms", () => {
    const long: Entry[] = [];
    let t = 0;
    for (let s = 0; s < 1500; s += 1) {
      long.push(para(`SPEAKER_0${s % 4}`));
      for (let w = 0; w < 21; w += 1) {
        long.push(item(t, 0.28, ` w${w}`, w === 7 ? 0.1 : 0.95));
        t += 0.2886;
      }
    }
    const began = performance.now();
    const segments = freshSegments(long);
    const words = wordIndex(long);
    const likely = likelyErrors(long, words, segments, 0.3, new Set());
    const took = performance.now() - began;
    expect(segments).toHaveLength(1500);
    expect(likely).toHaveLength(1500);
    expect(took).toBeLessThan(50);
  });
});
