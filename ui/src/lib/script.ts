// Which script a stretch of text is in, for setting it (Hashiya spec, Type).
//
// A paragraph is set by its first letter that has a direction, the rule both
// `dir="auto"` and `unicode-bidi: plaintext` follow (Unicode bidi rules P2 and
// P3). So the page picks the face and the `lang` by the very letter the
// browser picks the direction by: "میں نے 3 بجے meeting رکھی" opens in Urdu
// script and is set right to left in Nastaliq, with "3" and "meeting" kept in
// their own order inside it; "I said کیا ہوا" opens in Latin and is set left
// to right. Digits and punctuation have no direction of their own (bidi
// classes EN, AN, CS, ON) and are skipped, which is why a line opening with
// "3 بجے" is still Urdu.
//
// No imports, so node and the unit test can run it on its own.

export type Script = "arabic" | "latin" | "other" | "none";

// The blocks Urdu is written in: Arabic (U+0600 to U+06FF), Arabic Supplement
// (U+0750 to U+077F), Arabic Extended-A (U+08A0 to U+08FF), and the two
// Presentation Forms blocks (U+FB50 to U+FDFF, U+FE70 to U+FEFF). Letters
// only: the Arabic-Indic digits in U+0660 to U+0669 and U+06F0 to U+06F9 are
// not \p{L}.
const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/u;
const LETTER = /\p{L}/u;
const LATIN = /\p{Script=Latin}/u;

/** The script of the first letter in `text`, or "none" when it has no letter. */
export function firstStrong(text: string): Script {
  for (const ch of text) {
    if (!LETTER.test(ch)) continue;
    if (ARABIC.test(ch)) return "arabic";
    return LATIN.test(ch) ? "latin" : "other";
  }
  return "none";
}

/** The share of `text`'s letters that are in Urdu script, 0 when it has no letters. */
export function urduShare(text: string): number {
  let letters = 0;
  let urdu = 0;
  for (const ch of text) {
    if (!LETTER.test(ch)) continue;
    letters += 1;
    if (ARABIC.test(ch)) urdu += 1;
  }
  return letters === 0 ? 0 : urdu / letters;
}

/**
 * "ur" for a paragraph that opens in Urdu script, else nothing: the page's
 * own `lang="en"` stands. Roman Urdu is Latin script and is set as English
 * text is, which is what its letters need.
 */
export function langOf(text: string): "ur" | undefined {
  return firstStrong(text) === "arabic" ? "ur" : undefined;
}
