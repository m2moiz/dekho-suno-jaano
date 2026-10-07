// Urdu text as a comparison sees it, shared by the library's search and the
// Review second opinion, so the two never disagree about what one word is.
//
// Letters typed one way and stored another: an Arabic keyboard's yeh, kaf
// and heh against the Urdu letters a title is written in (ي ى to ی, ك to ک,
// ه to ہ), and the short-vowel marks, which a comparison never needs to match.
const VARIANTS: Record<string, string> = { "ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ" };
const MARKS = /[ً-ٰٟ]/g;

/** `text` as a comparison reads it: one form of each Urdu letter, no vowel marks, any case. */
export function fold(text: string): string {
  return text
    .replace(MARKS, "")
    .replace(/[يىكه]/g, (ch) => VARIANTS[ch] ?? ch)
    .toLocaleLowerCase();
}
