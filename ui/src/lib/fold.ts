// Urdu text as a comparison sees it, shared by the library's search and the
// Review second opinion, so the two never disagree about what one word is.
//
// Letters typed one way and stored another: an Arabic keyboard's yeh, kaf
// and heh against the Urdu letters a title is written in (ي ى to ی, ك to ک,
// ه to ہ), and the short-vowel marks, which a comparison never needs to match.
const VARIANTS: Record<string, string> = { "\u064A": "\u06CC", "\u0649": "\u06CC", "\u0643": "\u06A9", "\u0647": "\u06C1" };
const MARKS = /[\u064B-\u065F\u0670]/g;

/** `text` as a comparison reads it: one form of each Urdu letter, no vowel marks, any case. */
export function fold(text: string): string {
  return text
    .replace(MARKS, "")
    .replace(/[\u064A\u0649\u0643\u0647]/g, (ch) => VARIANTS[ch] ?? ch)
    .toLocaleLowerCase();
}
