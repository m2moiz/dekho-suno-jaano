// Which script a stretch of text is in, for setting it (Hashiya spec, Type).
//
// A paragraph is set by its first character with a strong direction, the rule
// both `dir="auto"` and `unicode-bidi: plaintext` follow (Unicode bidi rules P2
// and P3). So the page picks the face and the `lang` by the very character the
// browser picks the direction by: "میں نے 3 بجے meeting رکھی" opens in Urdu
// script and is set right to left in Nastaliq, with "3" and "meeting" kept in
// their own order inside it; "I said کیا ہوا" opens in Latin and is set left
// to right. Digits and most punctuation have no direction of their own (bidi
// classes EN, AN, CS, ON, ET) and are skipped, which is why a line opening
// with "3 بجے" or with the Arabic comma "،" (CS) is decided by what follows.
// Arabic-script punctuation of bidi class AL is different: the full stop "۔"
// (U+06D4), the question mark "؟" (U+061F), the semicolon "؛" (U+061B) and the
// rest listed in ARABIC_MARK are strong right to left, as the browser treats
// them, so a paragraph opening with one is Urdu.
//
// No imports, so node and the unit test can run it on its own.

export type Script = "arabic" | "latin" | "other" | "none";

// The blocks Urdu is written in: Arabic (U+0600 to U+06FF), Arabic Supplement
// (U+0750 to U+077F), Arabic Extended-A (U+08A0 to U+08FF), and the two
// Presentation Forms blocks (U+FB50 to U+FDFF, U+FE70 to U+FEFF). Letters
// only: the Arabic-Indic digits in U+0660 to U+0669 and U+06F0 to U+06F9 are
// not \p{L}.
const ARABIC = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/u;
// Characters in those blocks that are not letters but have bidi class AL (or
// are the Arabic letter mark): U+0608, U+060B, U+060D, U+061B to U+061F except
// the Arabic comma U+060C (class CS, not strong), U+066D, U+06D4, U+06FD,
// U+06FE, U+FBB2 to U+FBC2 and U+FDFC. Listed from Python's unicodedata
// (Unicode 16.0): [c for c in range if bidirectional(c) in ("AL", "R") and
// category(c)[0] != "L"]. In Chromium, `dir="auto"` on "<char>a" agreed with
// this file for 1,229 of the 1,232 code points in the five blocks; the other
// three, U+FE75, U+FEFD and U+FEFE, are unassigned. tests/e2e/reader.spec.ts
// keeps the full stop and the Arabic comma honest in both engines.
const ARABIC_MARK = /[\u0608\u060B\u060D\u061B-\u061F\u066D\u06D4\u06FD\u06FE\uFBB2-\uFBC2\uFDFC]/u;
const LETTER = /\p{L}/u;
const LATIN = /\p{Script=Latin}/u;

/** The script of the first strongly directional character in `text`, or "none" when it has none. */
export function firstStrong(text: string): Script {
  for (const ch of text) {
    if (ARABIC_MARK.test(ch)) return "arabic";
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
