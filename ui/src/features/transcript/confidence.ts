// Which words the recogniser was unsure of (#62), painted as one Highlight
// holding one range per word: no element per word, so the text stays plain.
//
// `c` means a different thing under each engine (payload.md, "Every engine
// writes e and c"), so the cut-off is per engine. Measured 3 Oct 2026 (#62)
// with scratch/accuracy/score.py against three public hand-checked
// references (#148's mixed Urdu-English podcast, 34 min of UrduSpeech's Urdu
// set, 30 min of an Earnings-22 call; #184 has the datasets): a word is wrong
// when the alignment does not pair it with the same reference word. Numbers
// are per mode, pooled over two runs, "tinted" being the share of words under
// the cut-off and "wrong" the share of those that are wrong.
//
// - whisper: 0.3. Under --roman-urdu (the owner's mode, 120 or 30 s windows)
//   on the mixed and the Urdu sets 20 to 35% of words are wrong; 0.3 tints 13
//   to 18% of them and 53 to 55% of what it tints is wrong, about twice the
//   base rate. 0.5, the earlier value (set from one
//   --language ur run), tints 26 to 41% under --roman-urdu and under half of
//   that is wrong, so a third of the page lit up and most of it right. Under
//   --language ur on Urdu 0.3 tints 2% (40% wrong); on the English call every
//   whisper mode tints 1 to 3% (24 to 49% wrong, against 3 to 5% overall).
// - parakeet: 0.9, now measured. On the English call 4% of its words are
//   wrong; 0.9 tints 3% and a third of those are wrong, eight times the base
//   rate, catching a quarter of all wrong words. 0.95 tints 15% at 15%.
// - sherpa: 0.5, borrowed from whisper's earlier value and not measured:
//   sherpa's `c` is the probability of the emitted token, the same kind of
//   number as whisper's, but no sherpa run was scored.

import type { Reading } from "./document";

export const UNSURE = "dsj-unsure";

export const CUTOFFS = { whisper: 0.3, parakeet: 0.9, sherpa: 0.5 } as const;

/**
 * The cut-off for the engine a transcript's `model` names, or null when it
 * names none of them (an import carries no `c` at all).
 */
export function cutoffFor(model: string): number | null {
  const name = model.toLowerCase();
  // Before parakeet: sherpa's default model directory names parakeet too.
  if (name.includes("sherpa")) return CUTOFFS.sherpa;
  if (name.includes("whisper")) return CUTOFFS.whisper;
  if (name.includes("parakeet")) return CUTOFFS.parakeet;
  return null;
}

/** The indexes of the words whose confidence is under `cutoff`. */
export function unsureWords(reading: Reading, cutoff: number): number[] {
  const out: number[] = [];
  const { confidence } = reading.words;
  for (let i = 0; i < confidence.length; i += 1) {
    // NaN, a word with no `c`, is never under anything.
    if ((confidence[i] ?? Number.NaN) < cutoff) out.push(i);
  }
  return out;
}

/** One Highlight with a range over each word in `words`, leading space left out. */
export function unsureHighlight(reading: Reading, words: number[], texts: Text[]): Highlight {
  const highlight = new Highlight();
  const { turn, offset, length } = reading.words;
  for (const word of words) {
    const text = texts[turn[word] ?? -1];
    if (text === undefined) continue;
    const from = offset[word] ?? 0;
    const to = from + (length[word] ?? 0);
    const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
    const range = new Range();
    range.setStart(text, from + lead);
    range.setEnd(text, to);
    highlight.add(range);
  }
  return highlight;
}
