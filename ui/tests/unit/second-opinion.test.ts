// The other transcript's reading of the same span (Hashiya spec, Review mode).
import { describe, expect, it } from "vitest";

import type { RecordingRow, TranscriptRow } from "../../src/features/library/types";
import {
  differing,
  normalize,
  opinionWords,
  otherTranscript,
  rememberedOpinion,
  sameScript,
  secondOpinion,
} from "../../src/features/review/secondOpinion";
import { read, type Sentence } from "../../src/features/transcript/document";
import { sentence } from "./sentences";

// The other engine cut its sentences elsewhere: one sentence across both spans.
const OTHER = read({ audio: "a", model: "whisper", sentences: [sentence(0.2, [" alpha", " bravo", " Charlie,", " delta", " echo"], 0.4)] });

describe("opinionWords", () => {
  it("gives each span the other reading's words whose middle falls inside it", () => {
    // Words at 0.2, 0.6, 1.0, 1.4, 1.8, each 0.4 s: their middles are 0.4, 0.8, 1.2, 1.6, 2.0 (the last ends at the sentence's end, 2.2).
    expect(opinionWords(OTHER, [{ start: 0.2, end: 1.3 }, { start: 1.3, end: 2.4 }])).toEqual([
      ["alpha", "bravo", "Charlie,"],
      ["delta", "echo"],
    ]);
  });
});

describe("opinionWords, placement", () => {
  it("places a word by its middle, not by where it starts", () => {
    // Words at 0, 1, 2, each 1 s: "q" starts at 1.0, before the boundary at 1.3, but its middle (1.5) is after it.
    const other = read({ audio: "a", model: "m", sentences: [sentence(0, [" p", " q", " r"], 1)] });
    expect(opinionWords(other, [{ start: 0, end: 1.3 }, { start: 1.3, end: 3 }])).toEqual([["p"], ["q", "r"]]);
  });

  it("gives a word whose middle is in a pause between two spans to the nearer span", () => {
    // The other engine stretched its last word into the silence after the sentence.
    const stretched = (end: number, second: number): Sentence => ({
      start: 0,
      end,
      text: " one two",
      tokens: [{ t: 0, w: " one" }, { t: second, w: " two" }],
    });
    const spans = [{ start: 0, end: 1.0 }, { start: 1.2, end: 2 }];
    // "two" spans 0.5 to 1.6, middle 1.05: 0.05 s after the first span, 0.15 s before the second.
    expect(opinionWords(read({ audio: "a", model: "m", sentences: [stretched(1.6, 0.5)] }), spans)).toEqual([["one", "two"], []]);
    // "two" spans 0.9 to 1.4, middle 1.15: 0.15 s after the first span, 0.05 s before the second.
    expect(opinionWords(read({ audio: "a", model: "m", sentences: [stretched(1.4, 0.9)] }), spans)).toEqual([["one"], ["two"]]);
  });

  it("gives a word just before the first span to it, and one just after the last to that, so Ctrl+G loses neither (Task 12 M9)", () => {
    // Words at 0 to 5, each 1 s, middles 0.5 to 5.5. The span runs 2.2 to 3.4:
    // w1 (middle 1.5) is 0.7 s before it and w3 (middle 3.5) 0.1 s after it, both within EDGE_S.
    const other = read({ audio: "a", model: "m", sentences: [sentence(0, [" w0", " w1", " w2", " w3", " w4", " w5"], 1)] });
    expect(opinionWords(other, [{ start: 2.2, end: 3.4 }])).toEqual([["w1", "w2", "w3"]]);
  });

  it("leaves out a word further than EDGE_S from the first or last span", () => {
    // w0 (middle 0.5) is 1.7 s before the span, w4 (4.5) 1.1 s after it: a stretch only the other engine heard.
    const other = read({ audio: "a", model: "m", sentences: [sentence(0, [" w0", " w1", " w2", " w3", " w4", " w5"], 1)] });
    expect(opinionWords(other, [{ start: 2.2, end: 3.4 }])[0]).not.toContain("w0");
    expect(opinionWords(other, [{ start: 2.2, end: 3.4 }])[0]).not.toContain("w4");
  });
});

describe("differing", () => {
  it("marks the other's words that are not in the longest run of equal words, case and punctuation aside", () => {
    expect(differing(["alpha", "bravo", "charlie"], ["alpha", "brave", "Charlie,"])).toEqual([false, true, false]);
    expect(differing(["a", "b"], ["a", "x", "b"])).toEqual([false, true, false]);
  });

  it("folds Arabic letter variants and short vowels, so one Urdu word in two spellings is the same word", () => {
    expect(normalize("كيا")).toBe(normalize("کیا"));
    expect(normalize("کَیا")).toBe(normalize("کیا"));
    expect(normalize("ھے")).not.toBe("");
    expect(normalize("نہیں،")).toBe(normalize("نهیں"));
  });
});

describe("sameScript", () => {
  it("compares only readings in one script: Roman Urdu against Urdu script underlines nothing", () => {
    expect(sameScript("kya hua", "کیا ہوا")).toBe(false);
    expect(sameScript("kya hua", "kia hua")).toBe(true);
    expect(sameScript("क्या हुआ", "کیا ہوا")).toBe(false);
    expect(sameScript("", "kia")).toBe(false);
  });
});

describe("secondOpinion", () => {
  it("underlines only where both are in one script, and counts a disagreement", () => {
    const opinions = secondOpinion(OTHER, [{ start: 0.2, end: 1.3 }, { start: 1.3, end: 2.4 }], ["alpha bravo charlie", "دیلٹا ایکو"]);
    expect(opinions.differs).toEqual([[false, false, false], null]);
    expect([...opinions.disagree]).toEqual([]);
    expect(secondOpinion(null, [{ start: 0, end: 1 }], ["x"]).words).toEqual([[]]);
  });
});

describe("secondOpinion, disagree", () => {
  const SPANS = [{ start: 0.2, end: 1.3 }, { start: 1.3, end: 2.4 }];

  it("holds the index of a span where the other reading has a word the draft lacks", () => {
    const opinions = secondOpinion(OTHER, SPANS, ["alpha brave charlie", "delta echo"]);
    expect(opinions.differs).toEqual([[false, true, false], [false, false]]);
    expect([...opinions.disagree]).toEqual([0]);
  });

  it("holds the index of a span where the draft has a word the other reading lacks", () => {
    // A repetition loop or an invented word: nothing of the other reading is marked, the span still disagrees.
    const loop = secondOpinion(OTHER, SPANS, ["alpha bravo charlie", "delta echo echo"]);
    expect(loop.differs).toEqual([[false, false, false], [false, false]]);
    expect([...loop.disagree]).toEqual([1]);
    const short = read({ audio: "a", model: "m", sentences: [sentence(0, [" a", " c"], 0.4)] });
    const opinions = secondOpinion(short, [{ start: 0, end: 1 }], ["a b c"]);
    expect(opinions.differs).toEqual([[false, false]]);
    expect([...opinions.disagree]).toEqual([0]);
  });

  it("holds the index of a span the other reading has no words in, while the draft has", () => {
    const opinions = secondOpinion(OTHER, [{ start: 0.2, end: 2.4 }, { start: 5, end: 6 }, { start: 7, end: 8 }], ["alpha bravo charlie delta echo", "hello world", ""]);
    expect(opinions.differs[1]).toBeNull();
    expect([...opinions.disagree]).toEqual([1]);
  });

  it("leaves out a span where the scripts differ, and one where the readings match", () => {
    const opinions = secondOpinion(OTHER, SPANS, ["ALPHA bravo, charlie", "دیلٹا ایکو"]);
    expect([...opinions.disagree]).toEqual([]);
  });
});

describe("rememberedOpinion", () => {
  // Three spans over OTHER's five words: the edit list's text of each changes one at a time.
  const spans = [{ start: 0.2, end: 1.0 }, { start: 1.0, end: 1.7 }, { start: 1.7, end: 2.4 }];
  const before = ["alpha bravo", "Charlie, delta", "echo"];

  it("gives what secondOpinion gives, edit after edit, and after a split", () => {
    const opinion = rememberedOpinion();
    const edits = [before, ["alpha bravo", "Charles delta", "echo"], ["alpha bravo", "Charles delta", "echo foxtrot"], before];
    for (const mine of edits) expect(opinion(OTHER, spans, mine)).toEqual(secondOpinion(OTHER, spans, mine));
    const split = [{ start: 0.2, end: 0.6 }, { start: 0.6, end: 1.0 }, ...spans.slice(1)];
    const mine = ["alpha", "bravo", "Charlie, delta", "echo"];
    expect(opinion(OTHER, split, mine)).toEqual(secondOpinion(OTHER, split, mine));
    expect(opinion(null, split, mine)).toEqual(secondOpinion(null, split, mine));
    // Merged back, then read against another reading of the same audio.
    expect(opinion(OTHER, spans, before)).toEqual(secondOpinion(OTHER, spans, before));
    const another = read({ audio: "a", model: "m", sentences: [sentence(0.2, [" alpha", " bravo", " Charles", " delta", " echo"], 0.4)] });
    expect(opinion(another, spans, before)).toEqual(secondOpinion(another, spans, before));
  });

  it("works out again only the span whose words changed: an edit costs one sentence, not 1,500 (Task 15)", () => {
    const opinion = rememberedOpinion();
    const first = opinion(OTHER, spans, before);
    const next = opinion(OTHER, spans, ["alpha bravo", "Charles delta", "echo"]);
    // The same arrays, not equal ones: nothing was compared again for spans 0 and 2.
    expect(next.words).toBe(first.words);
    expect(next.differs[0]).toBe(first.differs[0]);
    expect(next.differs[2]).toBe(first.differs[2]);
    expect(next.differs[1]).not.toBe(first.differs[1]);
    expect(next.differs[1]).toEqual([true, false]);
  });
});

describe("otherTranscript", () => {
  const t = (id: number): TranscriptRow =>
    ({ id, finished_at: "x", engine: "whisper", model: "m", diarized: null, speaker_count: null, mark_count: null, language: null, last_edited_at: null, language_tag: null, review_checked: null, review_total: null });
  it("is the newest other transcript of the same recording, or none", () => {
    const row = { transcripts: [t(9), t(7), t(3)] } as unknown as RecordingRow;
    expect(otherTranscript(row, 7)?.id).toBe(9);
    expect(otherTranscript(row, 9)?.id).toBe(7);
    expect(otherTranscript({ transcripts: [t(7)] } as unknown as RecordingRow, 7)).toBeNull();
  });
});
