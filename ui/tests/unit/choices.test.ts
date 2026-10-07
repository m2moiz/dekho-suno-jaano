import { describe, expect, it } from "vitest";

import {
  type Advanced,
  CHOICES,
  costLabel,
  expectedLabel,
  requestFor,
  speedFor,
} from "../../src/features/transcribe/choices";

const PLAIN: Advanced = { engine: null, model: "", prompt: "", diarize: true, requireDiarize: false, startOver: false };
const pick = (id: string) => CHOICES.find((c) => c.id === id) ?? (CHOICES[0] as (typeof CHOICES)[number]);

describe("what each answer runs", () => {
  it("runs mixed Urdu and English, and not sure, as whisper with Roman Urdu", () => {
    for (const id of ["mixed", "unsure"]) {
      expect(requestFor(pick(id), PLAIN)).toMatchObject({ engine: "whisper", roman_urdu: true, language: null });
    }
  });

  it("runs mostly Urdu as whisper in Urdu, and English as parakeet", () => {
    expect(requestFor(pick("urdu"), PLAIN)).toMatchObject({ engine: "whisper", roman_urdu: false, language: "ur" });
    expect(requestFor(pick("english"), PLAIN)).toMatchObject({ engine: "parakeet", roman_urdu: false, language: null, prompt: null });
  });

  it("lets an engine picked by hand override the answer, without the answer's whisper settings", () => {
    expect(requestFor(pick("mixed"), { ...PLAIN, engine: "parakeet" })).toMatchObject({ engine: "parakeet", roman_urdu: false, language: null });
  });

  it("carries the advanced options into the request", () => {
    expect(requestFor(pick("mixed"), { ...PLAIN, model: " m ", prompt: " p ", diarize: false, requireDiarize: true, startOver: true })).toMatchObject({
      model: "m",
      prompt: "p",
      diarize: false,
      require_diarize: false,
      start_over: true,
    });
  });
});

describe("expectedLabel", () => {
  it("says how long from the file's length and the engine's measured speed", () => {
    expect(expectedLabel(2520, 1.71)).toBe("About 25 minutes for this 42-minute recording");
    expect(expectedLabel(2520, 13)).toBe("About 3 minutes for this 42-minute recording");
    expect(expectedLabel(30, 13)).toBe("About 1 minute for this 1-minute recording");
    expect(expectedLabel(null, 13)).toBeNull();
  });
});

describe("speedFor", () => {
  it("is the answer's own measured speed while its engine runs, and the engine's own when picked by hand", () => {
    expect(speedFor(pick("mixed"), PLAIN)).toBe(pick("mixed").speed);
    expect(speedFor(pick("mixed"), { ...PLAIN, engine: "parakeet" })).toBe(pick("english").speed);
    // Picking the answer's own engine by hand is the answer.
    expect(speedFor(pick("urdu"), { ...PLAIN, engine: "whisper" })).toBe(pick("urdu").speed);
    expect(speedFor(pick("mixed"), { ...PLAIN, engine: "sherpa" })).toBeNull();
  });

  it("errs long: not sure is never quicker than mixed", () => {
    expect(pick("unsure").speed).toBeLessThanOrEqual(pick("mixed").speed);
  });
});

describe("costLabel", () => {
  it("prices the recording on an engine that charges, and says nothing for one that does not", () => {
    expect(costLabel(2520, 1.2)).toBe("About $0.84 for this recording");
    expect(costLabel(null, 1.2)).toBe("$1.20 an hour of audio");
    expect(costLabel(2520, null)).toBeNull();
  });
});
