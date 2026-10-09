// One change, not the whole list (#251): the splice the page sends is the
// longest common prefix and suffix of the list before and after a change,
// compared by value, and nothing when nothing changed.
import { describe, expect, it } from "vitest";

import { sameEntry, spliceOf, spliced } from "../../src/lib/splice";
import { type Content, type Entry, Editor, type Item } from "../../src/lib/editOps";

const para = (speaker: string | null): Entry => ({ kind: "paragraph", speaker, language: null });
const item = (sourceStart: number, text: string, confidence: number | null = 0.9): Item => ({
  kind: "item",
  source: "0",
  sourceStart,
  length: 0.3,
  text,
  muted: false,
  confidence,
});

const CONTENT: Content = [para("SPEAKER_00"), item(0.2, " alpha"), item(0.5, ""), item(0.6, " bravo"), para("SPEAKER_01"), item(1.0, " charlie")];

/** The splice from `before` to `after`, checked to turn one into the other. */
function check(before: Content, after: Content) {
  const change = spliceOf(before, after, sameEntry);
  if (change !== null) expect(spliced(before, change)).toEqual(after);
  return change;
}

describe("spliceOf", () => {
  it("is null when nothing changed, even for copies of every entry", () => {
    expect(check(CONTENT, CONTENT)).toBeNull();
    expect(check(CONTENT, CONTENT.map((e) => ({ ...e })))).toBeNull();
  });

  it("sends one entry for a mute", () => {
    const editor = new Editor(CONTENT);
    editor.applyEdit({ kind: "mute", entries: [3], muted: [true] });
    expect(check(CONTENT, editor.content)).toEqual({ start: 3, delete: 1, insert: [{ ...item(0.6, " bravo"), muted: true }] });
  });

  it("sends the corrected words for a correction that changes the word count", () => {
    const after = [...CONTENT.slice(0, 5), item(1.0, " Charles"), item(1.15, " Darwin")];
    expect(check(CONTENT, after)).toEqual({ start: 5, delete: 1, insert: [item(1.0, " Charles"), item(1.15, " Darwin")] });
  });

  it("sends a paragraph mark added inside a run of words", () => {
    const after = [...CONTENT.slice(0, 3), para("SPEAKER_02"), ...CONTENT.slice(3)];
    expect(check(CONTENT, after)).toEqual({ start: 3, delete: 0, insert: [para("SPEAKER_02")] });
  });

  it("inserts at the start", () => {
    const after = [para(null), ...CONTENT];
    expect(check(CONTENT, after)).toEqual({ start: 0, delete: 0, insert: [para(null)] });
  });

  it("deletes at the end", () => {
    expect(check(CONTENT, CONTENT.slice(0, -1))).toEqual({ start: 5, delete: 1, insert: [] });
  });

  it("does not let the common prefix and suffix overlap when a repeated entry is taken out", () => {
    const twice: Content = [para(null), item(0.2, " a"), item(0.2, " a"), item(0.2, " a")];
    expect(check(twice, twice.slice(0, 3))).toEqual({ start: 3, delete: 1, insert: [] });
    expect(check(twice.slice(0, 3), twice)).toEqual({ start: 3, delete: 0, insert: [item(0.2, " a")] });
  });

  it("ignores confidence, which is not in the file: the server works it out on every read", () => {
    expect(check(CONTENT, CONTENT.map((e) => (e.kind === "item" ? { ...e, confidence: 1 } : e)))).toBeNull();
  });

  it("turns the list into the edited one for every kind of edit, over random edits", () => {
    let seed = 7;
    const random = (n: number) => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed % n;
    };
    let before: Content = CONTENT;
    for (let k = 0; k < 300; k += 1) {
      const at = 1 + random(before.length - 1);
      const after: Entry[] = [...before];
      const kind = random(3);
      if (kind === 0) after.splice(at, random(3), ...Array.from({ length: random(3) }, (_, i) => item(at + i, ` w${k}`)));
      else if (kind === 1) after.splice(at, 0, para(`SPEAKER_0${random(3)}`));
      else after[at] = { ...(after[at] as Entry) };
      check(before, after);
      before = after;
    }
  });
});
