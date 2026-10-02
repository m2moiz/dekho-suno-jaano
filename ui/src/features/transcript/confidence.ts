// Which words the recogniser was unsure of (#62), painted as one Highlight
// holding one range per word: no element per word, so the text stays plain.
//
// `c` means a different thing under each engine (payload.md, "Every engine
// writes e and c"), so the cut-off is per engine. Measured 2026-10-02 with
// scratch/confidence_cutoff.py, numbers only:
//
// - whisper: 0.5. Scored against the public Urdu-English fixture's
//   hand-checked transcript (scratch/urdu_cs, #148; whisper-large-v3-turbo run
//   scratch/real_bench/runs/m33-turbo-ur): 346 of 1,158 words wrong (30%).
//   Words under 0.5 are 9% of all words, and 62% of them are wrong, twice the
//   base rate; 0.7 flags 17% at 67%, 0.3 flags 4% at 62%. 0.5 is where about a
//   tenth of the page lights up and most of what lights up is wrong.
// - parakeet: 0.9. Its `c` (one minus the normalised entropy) is compressed
//   near 1: on a 6-minute real English parakeet transcript (935 words) no word
//   is under 0.7, 4 are under 0.8 and 85 (9.1%) under 0.9. So 0.9 flags the
//   same tenth as whisper's 0.5. No ground truth exists for it yet, so whether
//   those are the wrong words is NOT measured.
// - sherpa: 0.5, borrowed from whisper and not measured: sherpa's `c` is the
//   probability of the emitted token, the same kind of number as whisper's.
//
// #62 asked for this on a real 74-minute transcript; none with `c` exists yet.

import type { Reading } from "./document";

export const UNSURE = "dsj-unsure";

export const CUTOFFS = { whisper: 0.5, parakeet: 0.9, sherpa: 0.5 } as const;

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
