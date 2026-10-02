// A synthetic transcript with the shape of the private one the 60fps number
// was first measured on (#108), and nothing private in it: nonsense syllables,
// from a fixed seed, so every machine generates the same bytes.
//
// The shape it copies, counted from scratch/perf_fixture_1038.json (gitignored,
// numbers only) on 2026-10-02: 1,038 sentences, 21,847 tokens, 238 speaker
// turns between 2 speakers, tokens per sentence median 14 and mean 21.0 (max
// 412), 12,465 tokens (57%) opening a word with a space, 2.96 characters per
// token. Tokens are sub-word pieces, as parakeet writes them.
//
//   node ui/tests/perf/fixture.ts > /tmp/synthetic.json   # the fixture as a file

export const SHAPE = { sentences: 1038, tokens: 21847, turns: 238, speakers: 2 } as const;

const SEED = 108;
const SECONDS_PER_TOKEN = 0.2886; // 6,304.7 s over 21,847 tokens in the original
const WORD_START = 0.57;

export interface Token {
  t: number;
  w: string;
}

export interface Sentence {
  start: number;
  end: number;
  text: string;
  speaker: number;
  tokens: Token[];
}

export interface Transcript {
  audio: string;
  model: string;
  speakers: string[];
  diarization: string;
  text: string;
  unclear: never[];
  sentences: Sentence[];
}

// mulberry32: small, seedable, the same sequence in every JS engine.
function random(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(rand: () => number, items: readonly T[]): T {
  const item = items[Math.floor(rand() * items.length)];
  if (item === undefined) throw new Error("pick from an empty list");
  return item;
}

const ONSETS = ["b", "d", "f", "g", "k", "l", "m", "n", "p", "r", "s", "t", "v", "z"] as const;
const VOWELS = ["a", "e", "i", "o", "u"] as const;
const CODAS = ["", "", "", "", "n", "r", "s"] as const;

// Tokens per sentence: skewed like speech, most short, a few very long. A
// log-normal with median 14 and mean 21, then nudged to the exact total.
function sentenceLengths(rand: () => number): number[] {
  const lengths = Array.from({ length: SHAPE.sentences }, () => {
    const gauss = Math.sqrt(-2 * Math.log(1 - rand())) * Math.cos(2 * Math.PI * rand());
    return Math.min(412, Math.max(2, Math.round(Math.exp(Math.log(14) + 0.9 * gauss))));
  });
  let excess = lengths.reduce((a, b) => a + b, 0) - SHAPE.tokens;
  for (let i = 0; excess !== 0; i = (i + 1) % lengths.length) {
    const length = lengths[i] ?? 0;
    if (excess > 0 && length > 2) {
      lengths[i] = length - 1;
      excess -= 1;
    } else if (excess < 0) {
      lengths[i] = length + 1;
      excess += 1;
    }
  }
  return lengths;
}

// Which sentences open a new speaker turn: the first, and 237 others.
function turnStarts(rand: () => number): Set<number> {
  const starts = new Set<number>([0]);
  while (starts.size < SHAPE.turns) starts.add(1 + Math.floor(rand() * (SHAPE.sentences - 1)));
  return starts;
}

export function syntheticTranscript(): Transcript {
  const rand = random(SEED);
  const lengths = sentenceLengths(rand);
  const starts = turnStarts(rand);
  const sentences: Sentence[] = [];
  let index = 0;
  let speaker = 0;
  for (const [i, length] of lengths.entries()) {
    if (i > 0 && starts.has(i)) speaker = (speaker + 1) % SHAPE.speakers;
    const tokens: Token[] = [];
    for (let k = 0; k < length; k += 1) {
      const syllable = pick(rand, ONSETS) + pick(rand, VOWELS) + pick(rand, CODAS);
      const opensWord = k === 0 || rand() < WORD_START;
      tokens.push({ t: +(index * SECONDS_PER_TOKEN).toFixed(2), w: opensWord ? ` ${syllable}` : syllable });
      index += 1;
    }
    const start = tokens[0]?.t ?? 0;
    sentences.push({
      start,
      end: +(index * SECONDS_PER_TOKEN).toFixed(2),
      text: tokens.map((token) => token.w).join(""),
      speaker,
      tokens,
    });
  }
  return {
    audio: "synthetic-perf.wav",
    model: "synthetic",
    speakers: ["SPEAKER_00", "SPEAKER_01"],
    diarization: "synthetic",
    text: sentences.map((sentence) => sentence.text).join(""),
    unclear: [],
    sentences,
  };
}

if (import.meta.main) {
  process.stdout.write(`${JSON.stringify(syntheticTranscript())}\n`);
}
