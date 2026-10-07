// Which words were corrected, for the margin (Hashiya spec, "The margin").
import { describe, expect, it } from "vitest";

import { correction } from "../../src/features/edit/correct";
import { corrections, originalText, tokensOf } from "../../src/features/edit/corrections";
import { readContent } from "../../src/features/edit/readContent";
import type { TranscriptDoc } from "../../src/features/transcript/document";
import type { Content, Item } from "../../src/lib/editOps";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.9): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}

const DOC: TranscriptDoc = {
  audio: "a.wav",
  model: "parakeet",
  sentences: [
    { start: 0.2, end: 1.6, text: " alpha bravo charlie delta", tokens: [
      { t: 0.2, w: " alpha", e: 0.5, c: 0.9 },
      { t: 0.6, w: " bravo", e: 0.9, c: 1 },
      { t: 1.0, w: " charlie", e: 1.3, c: 0.3 },
      { t: 1.3, w: " delta", e: 1.6, c: 0.9 },
    ] },
  ],
};

const CONTENT: Content = [
  { kind: "paragraph", speaker: null, language: null },
  item(0, 0.2, "", null),
  item(0.2, 0.3, " alpha"),
  item(0.5, 0.1, "", null),
  // A word the recogniser was fully sure of: confidence 1, never edited.
  item(0.6, 0.3, " bravo", 1),
  item(0.9, 0.1, "", null),
  item(1.0, 0.3, " charlie", 0.3),
  item(1.3, 0.3, " delta"),
];

describe("corrections", () => {
  const tokens = tokensOf(DOC);

  it("finds a retyped stretch and what the transcript had there", () => {
    const retyped = CONTENT.slice();
    const op = correction(retyped, 6, 7, "Charles Darwin");
    const after = [...retyped.slice(0, 6), ...op.entries, ...retyped.slice(7)];
    const found = corrections(readContent(after, undefined).reading, tokens);
    expect(found).toEqual([{ turn: 0, first: 2, last: 3, original: "charlie", now: "Charles Darwin" }]);
  });

  it("does not count a word the recogniser was sure of, or one whose edges alone moved", () => {
    expect(corrections(readContent(CONTENT, undefined).reading, tokens)).toEqual([]);
    const retimed = CONTENT.map((e, i) => (i === 7 && e.kind === "item" ? { ...e, sourceStart: 1.35, length: 0.25, confidence: 1 } : e));
    expect(corrections(readContent(retimed, undefined).reading, tokens)).toEqual([]);
  });

  it("leaves out a word whose start was dragged earlier, into its neighbour's time (#85)", () => {
    // bounds.ts gives both words whose edge moved confidence 1.
    const retimed = CONTENT.map((e, i) => {
      if (e.kind !== "item") return e;
      if (i === 6) return { ...e, length: 0.2, confidence: 1 };
      if (i === 7) return { ...e, sourceStart: 1.2, length: 0.4, confidence: 1 };
      return e;
    });
    expect(corrections(readContent(retimed, undefined).reading, tokens)).toEqual([]);
  });

  it("marks only the word retyped when the stretch retyped took in a word left as it was", () => {
    const retyped = CONTENT.slice();
    const op = correction(retyped, 4, 7, "bravo Charlie");
    const after = [...retyped.slice(0, 4), ...op.entries, ...retyped.slice(7)];
    const found = corrections(readContent(after, undefined).reading, tokens);
    expect(found).toEqual([{ turn: 0, first: 2, last: 2, original: "charlie", now: "Charlie" }]);
  });

  it("compares a word cut into pieces by the recogniser as the whole word", () => {
    const doc: TranscriptDoc = {
      audio: "a.wav",
      model: "parakeet",
      sentences: [{ start: 0, end: 0.6, text: " question", tokens: [{ t: 0, w: " questi", e: 0.4, c: 0.9 }, { t: 0.4, w: "on", e: 0.6, c: 0.9 }] }],
    };
    // Its start dragged later, past where its first piece ended.
    const content: Content = [
      { kind: "paragraph", speaker: null, language: null },
      item(0, 0.45, "", null),
      item(0.45, 0.05, " questi", 1),
      item(0.5, 0.1, "on", 1),
    ];
    expect(corrections(readContent(content, undefined).reading, tokensOf(doc))).toEqual([]);
  });

  it("records a stretch emptied of words as a deletion, struck beside the word before it", () => {
    const op = correction(CONTENT, 6, 7, "");
    const after = [...CONTENT.slice(0, 6), ...op.entries, ...CONTENT.slice(7)];
    expect(corrections(readContent(after, undefined).reading, tokens)).toEqual([
      { turn: 0, first: 2, last: 1, original: "charlie", now: "" },
    ]);
  });

  it("records a doubled word retyped once as the deletion of the second", () => {
    // " bravo charlie" (entries 4 to 7) retyped as "bravo": charlie is gone, bravo kept.
    const op = correction(CONTENT, 4, 7, "bravo");
    const after = [...CONTENT.slice(0, 4), ...op.entries, ...CONTENT.slice(7)];
    expect(corrections(readContent(after, undefined).reading, tokens)).toEqual([
      { turn: 0, first: 2, last: 1, original: "charlie", now: "" },
    ]);
  });

  it("lists nothing for two unedited words that start at the same time, the first with no length", () => {
    const doc: TranscriptDoc = {
      audio: "a.wav",
      model: "parakeet",
      sentences: [{ start: 0.2, end: 0.5, text: " uh okay", tokens: [{ t: 0.2, w: " uh", e: 0.2, c: 0.9 }, { t: 0.2, w: " okay", e: 0.5, c: 0.9 }] }],
    };
    const content: Content = [
      { kind: "paragraph", speaker: null, language: null },
      item(0, 0.2, "", null),
      item(0.2, 0, " uh"),
      item(0.2, 0.3, " okay"),
    ];
    expect(corrections(readContent(content, undefined).reading, tokensOf(doc))).toEqual([]);
    // And both still count once retyped: "uh" deleted, "okay" kept.
    const op = correction(content, 2, 4, "okay");
    const after = [...content.slice(0, 2), ...op.entries];
    expect(corrections(readContent(after, undefined).reading, tokensOf(doc))).toEqual([
      { turn: 0, first: 0, last: -1, original: "uh", now: "" },
    ]);
  });

  it("reads the transcript's own words over a stretch of time", () => {
    expect(originalText(tokens, 0.6, 1.3)).toBe("bravo charlie");
    expect(originalText(tokens, 5, 6)).toBe("");
  });
});
