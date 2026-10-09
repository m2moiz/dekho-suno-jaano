// Who said a stretch, changed as an edit (Hashiya spec, Review mode: "Speaker
// changes are a new EditOp kind that splits the speaker's paragraph at the
// sentence boundary and sets the speaker").
import { describe, expect, it } from "vitest";

import { readContent, speakerLabels } from "../../src/features/edit/readContent";
import { governingParagraph, newSpeakerLabel, speakerAt, speakerChange } from "../../src/features/edit/speaker";
import { type Content, Editor, type Entry, type Item } from "../../src/lib/editOps";
import { lint } from "../../src/lib/linter";

function item(sourceStart: number, length: number, text: string): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence: 0.9 };
}
const para = (speaker: string | null): Entry => ({ kind: "paragraph", speaker, language: "ur" });

// Two sentences: SPEAKER_00 says "alpha bravo charlie", SPEAKER_01 "delta echo".
// Contiguous, with an item of no text for every pause, as dsj/hatao.py
// `from_transcript` builds a list, so the linter (lib/linter.ts) accepts it.
const CONTENT: Content = [
  para("SPEAKER_00"), // 0
  item(0, 0.2, ""), // 1
  item(0.2, 0.3, " alpha"), // 2
  item(0.5, 0.1, ""), // 3
  item(0.6, 0.3, " bravo"), // 4
  item(0.9, 0.1, ""), // 5
  item(1.0, 0.3, " charlie"), // 6
  para("SPEAKER_01"), // 7
  item(1.3, 0.7, ""), // 8
  item(2.0, 0.4, " delta"), // 9
  item(2.4, 0.1, ""), // 10
  item(2.5, 0.4, " echo"), // 11
];
const LEGEND = ["SPEAKER_00", "SPEAKER_01"];
const SOURCES = new Set(["0"]);

function turns(content: Content): [string | undefined, string][] {
  const { reading } = readContent(content, LEGEND);
  return reading.turns.map((t) => [t.speaker === null ? undefined : reading.speakers[t.speaker], t.text]);
}

function apply(content: Content, start: number, stop: number, speaker: string): Content {
  const op = speakerChange(content, start, stop, speaker);
  if (op === null) throw new Error("no change");
  const editor = new Editor(content, { check: (c) => lint(c, SOURCES) });
  editor.applyEdit(op);
  return editor.content;
}

describe("speakerChange", () => {
  it("sets a whole sentence's speaker on its own paragraph mark", () => {
    const op = speakerChange(CONTENT, 2, 7, "SPEAKER_01");
    expect(op).toMatchObject({ kind: "speaker", start: 0, stop: 7 });
    expect(turns(apply(CONTENT, 2, 7, "SPEAKER_01"))).toEqual([["SPEAKER_01", " alpha bravo charlie delta echo"]]);
  });

  it("splits a sentence at a stretch inside it, and the rest keeps its speaker", () => {
    expect(turns(apply(CONTENT, 4, 5, "SPEAKER_01"))).toEqual([
      ["SPEAKER_00", " alpha"],
      ["SPEAKER_01", " bravo"],
      ["SPEAKER_00", " charlie"],
      ["SPEAKER_01", " delta echo"],
    ]);
  });

  it("sets every sentence a stretch runs across", () => {
    expect(turns(apply(CONTENT, 6, 12, "SPEAKER_02"))).toEqual([
      ["SPEAKER_00", " alpha bravo"],
      ["SPEAKER_02", " charlie delta echo"],
    ]);
  });

  it("sets a stretch that runs from a speaker's sentence through someone else's into theirs again", () => {
    // A third sentence, SPEAKER_00's again: entries 12 to 15.
    const three: Content = [...CONTENT, para("SPEAKER_00"), item(2.9, 0.3, " foxtrot"), item(3.2, 0.1, ""), item(3.3, 0.3, " golf")];
    expect(turns(apply(three, 4, 14, "SPEAKER_00"))).toEqual([["SPEAKER_00", " alpha bravo charlie delta echo foxtrot golf"]]);
  });

  it("leaves no mark inside the stretch that says its speaker again (Task 5 carry)", () => {
    // Review sets a merged sentence's speaker over both its halves: the mark between them would only repeat it.
    const after = apply(CONTENT, 6, 12, "SPEAKER_02");
    expect(after.filter((e) => e.kind === "paragraph").map((e) => e.kind === "paragraph" && e.speaker)).toEqual(["SPEAKER_00", "SPEAKER_02"]);
    const whole = apply(CONTENT, 2, 12, "SPEAKER_01");
    expect(whole.filter((e) => e.kind === "paragraph").map((e) => e.kind === "paragraph" && e.speaker)).toEqual(["SPEAKER_01"]);
    // A mark before the stretch is a sentence's own boundary and stays, even when it names the same speaker.
    const next = apply(CONTENT, 9, 12, "SPEAKER_00");
    expect(next.filter((e) => e.kind === "paragraph").map((e) => e.kind === "paragraph" && e.speaker)).toEqual(["SPEAKER_00", "SPEAKER_00"]);
  });

  it("is undone in one step, back to the list as it was", () => {
    const op = speakerChange(CONTENT, 4, 5, "SPEAKER_01");
    if (op === null) throw new Error("no change");
    const editor = new Editor(CONTENT, { check: (c) => lint(c, SOURCES) });
    editor.applyEdit(op);
    editor.undo();
    expect(editor.content).toEqual(CONTENT);
  });

  it("changes nothing when the stretch already has that speaker", () => {
    expect(speakerChange(CONTENT, 2, 7, "SPEAKER_00")).toBeNull();
  });

  it("keeps each paragraph's language on the marks it adds", () => {
    const after = apply(CONTENT, 4, 5, "SPEAKER_01");
    expect(after.filter((e) => e.kind === "paragraph").every((e) => e.kind === "paragraph" && e.language === "ur")).toBe(true);
  });
});

describe("who speaks where", () => {
  it("finds the paragraph that governs an entry, and its speaker", () => {
    expect(governingParagraph(CONTENT, 11)).toBe(7);
    expect(speakerAt(CONTENT, 4)).toBe("SPEAKER_00");
  });

  it("makes a label for a new speaker that no speaker has", () => {
    expect(newSpeakerLabel(["SPEAKER_00", "SPEAKER_01"])).toBe("SPEAKER_02");
    // senko numbered a real two-speaker clip SPEAKER_01 and SPEAKER_02 (document.ts).
    expect(newSpeakerLabel(["SPEAKER_01", "SPEAKER_02"])).toBe("SPEAKER_00");
  });

  it("reads a label the list uses and the legend lacks as one more speaker, in order of first use", () => {
    const after = apply(CONTENT, 6, 12, "SPEAKER_02");
    expect(speakerLabels(after, LEGEND)).toEqual(["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]);
    expect(speakerLabels([para(null), item(0, 1, " hi")], undefined)).toBeUndefined();
  });
});
