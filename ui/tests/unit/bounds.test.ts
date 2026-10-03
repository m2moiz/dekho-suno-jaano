// Dragging a word's edge (#85).
import { describe, expect, it } from "vitest";

import { boundsOf, edgeRange, retime } from "../../src/features/edit/bounds";
import { type Content, Editor, type Entry, type Item } from "../../src/lib/editOps";
import { lint } from "../../src/lib/linter";

function item(sourceStart: number, length: number, text: string, extra: Partial<Item> = {}): Item {
  // A pause has no word, so nothing to be sure of.
  const confidence = text === "" ? null : 0.9;
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence, ...extra };
}
const PARAGRAPH: Entry = { kind: "paragraph", speaker: null, language: null };

// " one" " two" " three", pauses between, " two" in two pieces with a pause
// inside it, and a second paragraph before " four".
const CONTENT: Content = [
  PARAGRAPH,
  item(0, 0.5, ""),
  item(0.5, 0.4, " one"),
  item(0.9, 0.2, ""),
  item(1.1, 0.2, " tw"),
  item(1.3, 0.05, ""),
  item(1.35, 0.15, "o"),
  item(1.5, 0.3, ""),
  item(1.8, 0.4, " three"),
  PARAGRAPH,
  item(2.2, 0.1, ""),
  item(2.3, 0.5, " four"),
];

const words = (content: Content) =>
  content.filter((e): e is Item => e.kind === "item" && e.text !== "").map((e) => [e.text, e.sourceStart, +(e.sourceStart + e.length).toFixed(3)]);

// " two" is entries [4, 7).
const TWO = boundsOf(CONTENT, 4, 7);

function apply(content: Content, op: ReturnType<typeof retime>): Content {
  const editor = new Editor(content, { check: (c) => lint(c, new Set(["0"])) });
  editor.applyEdit(op);
  return editor.content;
}

describe("dragging an edge", () => {
  it("finds the word's pieces and its neighbours", () => {
    expect(TWO).toMatchObject({ from: 2, stop: 9, first: 4, last: 6, previous: 2, next: 8 });
  });

  it("moves the start earlier into a pause, and later, leaving a pause behind", () => {
    expect(words(apply(CONTENT, retime(CONTENT, TWO, "start", 1.0))).slice(0, 3)).toEqual([
      [" one", 0.5, 0.9], [" tw", 1.0, 1.3], ["o", 1.35, 1.5],
    ]);
    const later = apply(CONTENT, retime(CONTENT, TWO, "start", 1.2));
    expect(words(later)[1]).toEqual([" tw", 1.2, 1.3]);
    expect(later.slice(3, 5)).toEqual([item(0.9, 0.3, ""), { ...item(1.2, 0.1, " tw"), confidence: 1 }]);
  });

  it("takes time from the neighbour it moves into, and never overlaps it", () => {
    const into = apply(CONTENT, retime(CONTENT, TWO, "start", 0.7));
    expect(words(into).slice(0, 2)).toEqual([[" one", 0.5, 0.7], [" tw", 0.7, 1.3]]);
    const end = apply(CONTENT, retime(CONTENT, TWO, "end", 2.0));
    expect(words(end).slice(2, 4)).toEqual([["o", 1.35, 2.0], [" three", 2.0, 2.2]]);
  });

  it("stops at the neighbour's far end and at the word's own other end", () => {
    expect(edgeRange(CONTENT, TWO, "start")).toEqual([0.5, 1.3]);
    expect(edgeRange(CONTENT, TWO, "end")).toEqual([1.35, 2.2]);
    const far = apply(CONTENT, retime(CONTENT, TWO, "start", -5));
    expect(words(far).slice(0, 2)).toEqual([[" one", 0.5, 0.5], [" tw", 0.5, 1.3]]);
    const past = apply(CONTENT, retime(CONTENT, TWO, "start", 9));
    expect(words(past)[1]).toEqual([" tw", 1.3, 1.3]);
  });

  it("drags the first word's start back to the start of the recording", () => {
    const one = boundsOf(CONTENT, 2, 3);
    const moved = apply(CONTENT, retime(CONTENT, one, "start", 0.1));
    expect(moved.slice(0, 3)).toEqual([PARAGRAPH, item(0, 0.1, ""), { ...item(0.1, 0.8, " one"), confidence: 1 }]);
  });

  it("keeps the paragraph between two words where it was", () => {
    const three = boundsOf(CONTENT, 8, 9);
    const moved = apply(CONTENT, retime(CONTENT, three, "end", 2.25));
    expect(moved.slice(8, 12)).toEqual([
      { ...item(1.8, 0.45, " three"), confidence: 1 },
      PARAGRAPH,
      item(2.25, 0.05, ""),
      item(2.3, 0.5, " four"),
    ]);
  });

  it("never makes an overlap or a negative length, wherever a drag goes", () => {
    let seed = 85;
    const random = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    let content = CONTENT;
    const wordRanges = [[2, 3], [4, 7], [8, 9]] as const;
    for (let i = 0; i < 500; i += 1) {
      // Find the word again in the list as it is now: its entries move as pauses come and go.
      const texts = content.flatMap((e, index) => (e.kind === "item" && e.text !== "" ? [index] : []));
      const pick = wordRanges[Math.floor(random() * wordRanges.length)] ?? wordRanges[0];
      const at = pick[0] === 4 ? [texts[1] ?? 0, (texts[2] ?? 0) + 1] : [texts[pick[0] === 2 ? 0 : 3] ?? 0, (texts[pick[0] === 2 ? 0 : 3] ?? 0) + 1];
      const bounds = boundsOf(content, at[0] ?? 0, at[1] ?? 0);
      content = apply(content, retime(content, bounds, random() < 0.5 ? "start" : "end", random() * 3 - 0.2));
      const items = content.filter((e): e is Item => e.kind === "item");
      expect(items.every((e) => e.length >= 0)).toBe(true);
      const spoken = items.filter((e) => e.text !== "");
      for (let k = 1; k < spoken.length; k += 1) {
        const a = spoken[k - 1] as Item;
        const b = spoken[k] as Item;
        expect(b.sourceStart).toBeGreaterThanOrEqual(+(a.sourceStart + a.length).toFixed(3) - 1e-9);
      }
    }
  });

  it("is one undo step for a whole drag", () => {
    const editor = new Editor(CONTENT, { check: (c) => lint(c, new Set(["0"])) });
    const base = editor.content;
    let length = TWO.stop - TWO.from;
    editor.beginGesture();
    for (const seconds of [1.05, 1.0, 0.95, 0.8, 0.75]) {
      const op = retime(base, TWO, "start", seconds);
      editor.applyEdit({ ...op, stop: TWO.from + length });
      length = op.entries.length;
    }
    editor.endGesture();
    expect(words(editor.content)[1]).toEqual([" tw", 0.75, 1.3]);
    expect(editor.undoLabel()).toBe("timing");
    editor.undo();
    expect(editor.content).toEqual(CONTENT);
    expect(editor.canUndo()).toBe(false);
  });
});
