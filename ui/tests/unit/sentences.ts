// A synthetic sentence for the unit tests that read word times: `words` are
// the tokens (a leading space opens a word), `step` seconds apart from `start`.
import type { Sentence } from "../../src/features/transcript/document";

export function sentence(start: number, words: string[], step = 0.5): Sentence {
  const tokens = words.map((w, i) => ({ t: +(start + i * step).toFixed(2), w }));
  return { start, end: +(start + words.length * step).toFixed(2), text: words.join(""), tokens };
}
