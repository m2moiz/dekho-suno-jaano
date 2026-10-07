// The other transcript's reading of the same span (Hashiya spec, Review mode).
import { describe, expect, it } from "vitest";

import type { RecordingRow, TranscriptRow } from "../../src/features/library/types";
import { differing, normalize, opinionWords, otherTranscript, sameScript, secondOpinion } from "../../src/features/review/secondOpinion";
import { read } from "../../src/features/transcript/document";
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
