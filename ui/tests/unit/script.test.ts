// Which script a paragraph opens in decides its direction, its face and its
// lang (Hashiya spec, Type). The sentences are made up for this test.
import { describe, expect, it } from "vitest";

import { firstStrong, langOf, urduShare } from "../../src/lib/script";

describe("firstStrong", () => {
  it.each([
    ["an Urdu sentence", " آج صبح ہم نے نیا منصوبہ دیکھا۔", "arabic"],
    // Review Focus 1: a number and an English word inside Urdu do not move the paragraph.
    ["Urdu with a number and English inside", "میں نے 3 بجے meeting رکھی ہے۔", "arabic"],
    ["English with Urdu inside", " I said کیا ہوا", "latin"],
    ["Roman Urdu", " Yaar, kal ki meeting 10 baje hai.", "latin"],
    ["a number first, then English", " 3, 4 then ok", "latin"],
    ["a number first, then Urdu", " 3 بجے", "arabic"],
    ["Devanagari", "नमस्ते", "other"],
    ["digits and Urdu punctuation only", " 123 ۔،", "none"],
    ["nothing", "", "none"],
  ] as const)("%s opens in %s", (_, text, script) => {
    expect(firstStrong(text)).toBe(script);
  });
});

describe("langOf", () => {
  it("tags a paragraph that opens in Urdu script as Urdu and leaves the rest untagged", () => {
    expect(langOf("میں نے 3 بجے meeting رکھی ہے۔")).toBe("ur");
    expect(langOf(" I said کیا ہوا")).toBeUndefined();
    expect(langOf("नमस्ते")).toBeUndefined();
  });
});

describe("urduShare", () => {
  it("is the share of letters in Urdu script, digits and spaces left out", () => {
    expect(urduShare("ab پ 12")).toBeCloseTo(1 / 3, 5);
    expect(urduShare(" آج")).toBe(1);
    expect(urduShare(" 12 ")).toBe(0);
  });
});
