// The synthetic perf fixture (#108) is held here, in `just check`, even though
// the frame-time check that uses it runs only in `just verify`: a fixture that
// drifted from the shape the baseline was measured on would make the number
// mean something else without failing anything.
import { describe, expect, it } from "vitest";

import { SHAPE, syntheticTranscript } from "../perf/fixture.ts";

describe("the synthetic perf fixture", () => {
  const transcript = syntheticTranscript();
  const tokens = transcript.sentences.flatMap((sentence) => sentence.tokens);

  it("has the shape the 16.7 ms baseline was measured on", () => {
    expect(transcript.sentences).toHaveLength(SHAPE.sentences);
    expect(SHAPE).toEqual({ sentences: 1038, tokens: 21847, turns: 238, speakers: 2 });
    expect(tokens).toHaveLength(SHAPE.tokens);
    const turns = transcript.sentences.filter(
      (sentence, i) => i === 0 || sentence.speaker !== transcript.sentences[i - 1]?.speaker,
    );
    expect(turns).toHaveLength(SHAPE.turns);
    expect(new Set(transcript.sentences.map((sentence) => sentence.speaker)).size).toBe(SHAPE.speakers);
  });

  it("is the same on every run and every machine", () => {
    expect(syntheticTranscript()).toEqual(transcript);
  });

  it("is made of nonsense syllables and nothing else", () => {
    for (const token of tokens) expect(token.w).toMatch(/^ ?[a-z]{2,3}$/);
  });

  it("keeps a sentence's text equal to its tokens joined, as dsj writes it", () => {
    for (const sentence of transcript.sentences) {
      expect(sentence.text).toBe(sentence.tokens.map((token) => token.w).join(""));
    }
  });
});
