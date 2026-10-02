// A transcript as the reader draws it: paragraphs of plain text, and a table
// of every word's place in that text and in time (#58, #60).
//
// The paragraph's text is its tokens' `w` joined, never `sentence.text` (#57
// section 7). The two disagreed in 16 of 480 sentences of a real transcript at
// chunk seams (#106); dsj now writes them equal, but older files on disk do
// not, and a click must land on the word that was drawn. Each word's offset is
// counted here, in JavaScript's own UTF-16 units, over the very string that is
// drawn, so it is exact by construction. The file's `charOffset` counts code
// points (#126) and would drift after the first emoji, so it is not read.
//
// Relative imports only, so `node` can run this file directly over a local
// transcript (the #58 check over scratch/eval/arm_a_transcript.json).

export type Token = { t: number; w: string; e?: number; c?: number };

export type Sentence = {
  start: number;
  end: number;
  text: string;
  speaker?: number | null;
  tokens: Token[];
};

export type TranscriptDoc = {
  audio: string;
  model: string;
  speakers?: string[];
  sentences: Sentence[];
};

/** One paragraph: consecutive sentences of one speaker turn, as one string. */
export type Turn = {
  speaker: number | null;
  /** Seconds, where its first word starts. */
  start: number;
  /** Its words' tokens, joined exactly as the file has them. */
  text: string;
  /** Index of its first word in `Reading.words`. */
  first: number;
  /** How many words it holds. */
  count: number;
};

/**
 * Every word in reading order, as parallel arrays, so the playhead's lookup on
 * every frame walks numbers and allocates nothing (#60).
 *
 * A word is a token that starts with whitespace plus the tokens after it that
 * do not: parakeet writes sub-word pieces (57% of tokens open a word, #108),
 * and a click or a highlight on half a word reads as a mistake.
 */
export type Words = {
  /** Seconds: the word's first token's `t`. */
  start: Float64Array;
  /** Seconds: the next word's start, or the sentence's end for its last word (#60 step 6). */
  end: Float64Array;
  /** Which paragraph it is in. */
  turn: Uint32Array;
  /** Where it starts in that paragraph's text, in UTF-16 units. */
  offset: Uint32Array;
  /** Its length in that text, in UTF-16 units. */
  length: Uint32Array;
};

export type Reading = { turns: Turn[]; words: Words; speakers: string[] };

// Without speaker labels a paragraph breaks at a pause longer than this, in
// seconds. Measured 2026-10-02 on the two local real transcripts (numbers
// only; both gitignored): the gap between consecutive sentences is exactly 0
// for 816 of 1,037 pairs in scratch/perf_fixture_1038.json and 400 of 479 in
// scratch/eval/arm_a_transcript.json, and a pause does not mark a change of
// speaker (25 of that fixture's 237 real changes have a gap over 0.5 s). So a
// gap rule can only find breathing points, and the question is how many: at
// 0.2 s it makes 148 paragraphs of 7.0 sentences on the fixture with its labels
// ignored, and 44 of 10.9 on the other, against real turns of median 2 and p90
// 9 sentences. 0.1 s gives 6.0 and 8.7 but is barely above one 0.08 s parakeet
// frame, so frame jitter alone would break a paragraph; 0.4 s gives 24
// sentences a paragraph on the second file, the wall of text #58 is about.
export const GAP_S = 0.2;

function fail(message: string): never {
  throw new TypeError(`This transcript cannot be read: ${message}`);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The JSON `/api/transcripts/{id}` sent, checked for what the reader reads. */
export function parseTranscript(json: unknown): TranscriptDoc {
  if (!isObject(json)) fail("it is not a JSON object.");
  const { sentences, speakers } = json;
  if (!Array.isArray(sentences)) fail("it has no `sentences` list.");
  for (const [i, s] of sentences.entries()) {
    if (!isObject(s) || typeof s.start !== "number" || typeof s.end !== "number") {
      fail(`sentence ${i} has no numeric start and end.`);
    }
    if (!Array.isArray(s.tokens)) fail(`sentence ${i} has no \`tokens\` list.`);
    for (const token of s.tokens) {
      if (!isObject(token) || typeof token.t !== "number" || typeof token.w !== "string") {
        fail(`a token of sentence ${i} has no numeric \`t\` and string \`w\`.`);
      }
    }
  }
  if (speakers !== undefined && !Array.isArray(speakers)) fail("`speakers` is not a list.");
  return json as unknown as TranscriptDoc;
}

/**
 * "Speaker 1" for the first name in `speakers` when it is a diarizer's cluster
 * id, any other name as it is. Numbered by place in the list, not by the id's
 * digits: senko named a real two-speaker clip's speakers SPEAKER_01 and
 * SPEAKER_02 (2026-10-02), and "Speaker 2" and "Speaker 3" would suggest a
 * third person.
 */
export function speakerName(speakers: string[], index: number | null): string | null {
  if (index === null) return null;
  const name = speakers[index];
  if (name === undefined) return null;
  return /^SPEAKER_\d+$/.test(name) ? `Speaker ${index + 1}` : name;
}

/** A sentence's tokens, or, for a sentence with none, its text as one token at its start. */
function tokensOf(sentence: Sentence): Token[] {
  if (sentence.tokens.length > 0) return sentence.tokens;
  return sentence.text === "" ? [] : [{ t: sentence.start, w: sentence.text }];
}

/** The paragraphs and the word table for one transcript. */
export function read(doc: TranscriptDoc): Reading {
  const labelled = Array.isArray(doc.speakers);
  const turns: Turn[] = [];
  const starts: number[] = [];
  const ends: number[] = [];
  const turnOf: number[] = [];
  const offsets: number[] = [];
  const lengths: number[] = [];
  let turn: Turn | undefined;
  let previous: Sentence | undefined;
  for (const sentence of doc.sentences) {
    const speaker = sentence.speaker ?? null;
    const breaks =
      turn === undefined ||
      previous === undefined ||
      (labelled ? speaker !== turn.speaker : sentence.start - previous.end > GAP_S);
    previous = sentence;
    const tokens = tokensOf(sentence);
    if (tokens.length === 0) continue;
    if (breaks || turn === undefined) {
      turn = { speaker: labelled ? speaker : null, start: tokens[0]?.t ?? sentence.start, text: "", first: starts.length, count: 0 };
      turns.push(turn);
    }
    const sentenceFirstWord = starts.length;
    for (const [k, token] of tokens.entries()) {
      // A word opens at the sentence's first token and at every token that
      // starts with whitespace; any other token continues the word before it.
      if (k === 0 || /^\s/.test(token.w)) {
        if (starts.length > sentenceFirstWord) ends[ends.length - 1] = token.t;
        starts.push(token.t);
        ends.push(sentence.end);
        turnOf.push(turns.length - 1);
        offsets.push(turn.text.length);
        lengths.push(0);
        turn.count += 1;
      }
      turn.text += token.w;
      lengths[lengths.length - 1] = turn.text.length - (offsets[offsets.length - 1] ?? 0);
    }
  }
  return {
    turns,
    speakers: doc.speakers ?? [],
    words: {
      start: Float64Array.from(starts),
      end: Float64Array.from(ends),
      turn: Uint32Array.from(turnOf),
      offset: Uint32Array.from(offsets),
      length: Uint32Array.from(lengths),
    },
  };
}
