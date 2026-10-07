// "What's spoken?" (Hashiya spec, Transcribe; critique: "Transcribe asks for
// flags, not the question: defaults parakeet for Urdu"). Each answer runs
// what the measurements say is best for it (README, "Which mode, by error
// rate", #184 and #236, word error rate against public hand-checked sets):
//
//   mixed Urdu and English: whisper turbo --roman-urdu, which since v0.4.2
//     cuts the audio at speech with Silero first (#236): 30 to 33% on #148's
//     podcast, against 46 to 57% for --language ur;
//   mostly Urdu: whisper --language ur, 21 to 23% on UrduSpeech's set,
//     against 42 to 43% for --roman-urdu (#184, #236);
//   English or European: parakeet, 4.9% on an Earnings-22 call (whisper with
//     the language detected: 4.4 to 4.5%, at a quarter of parakeet's speed);
//   not sure: as mixed, the owner's usual speech.
//
// The speeds are times realtime, wall clock with model load, on the owner's
// 16 GB M2, one run at a time, the slower of each mode's two runs on the set
// that matches the answer, so the estimate errs long. Every one was measured
// by `uv run python scratch/accuracy/run.py --plan 184` (or `--plan 236`)
// and read back with `uv run --with uroman --with rapidfuzz --with num2words
// python scratch/accuracy/score.py wall`:
//
//   --roman-urdu cut at speech, #148's podcast (854 s): 3.76x (#236, 3.8 min);
//     on the Urdu set (2,045 s) 2.53x (#236, 13.5 min), the slowest of that
//     mode on any set, which is what "not sure" uses;
//   --language ur, the Urdu set: 4.10x (#184, 8.3 min);
//   parakeet, the podcast: 23.32x (#184, 0.6 min), its slowest;
//   whisper with the language detected, picked by hand: 2.49x on the Urdu
//     set (#184, 13.7 min), its slowest.
//
// Those runs were `--no-diarize`. Speaker labelling adds about 20 s whatever
// the length (README, "senko over pyannote": 8.0 s on 74 minutes plus 12.4 s
// of model load), inside the rounding of a recording over a few minutes.

import type { Engine, TranscribeRequest } from "./jobs";

type EngineName = Engine["name"];

export type ChoiceId = "mixed" | "urdu" | "english" | "unsure";

export type Choice = {
  id: ChoiceId;
  label: string;
  engine: EngineName;
  roman_urdu: boolean;
  language: string | null;
  /** Measured times realtime, the slower run. */
  speed: number;
  /** What the dialog says it will use. */
  says: string;
};

export const CHOICES: readonly Choice[] = [
  { id: "mixed", label: "Mixed Urdu and English", engine: "whisper", roman_urdu: true, language: null, speed: 3.76, says: "whisper, writing Urdu in Roman letters" },
  { id: "urdu", label: "Mostly Urdu", engine: "whisper", roman_urdu: false, language: "ur", speed: 4.1, says: "whisper, writing Urdu script" },
  { id: "english", label: "English or European languages", engine: "parakeet", roman_urdu: false, language: null, speed: 23.32, says: "parakeet" },
  { id: "unsure", label: "Not sure", engine: "whisper", roman_urdu: true, language: null, speed: 2.53, says: "whisper with Roman Urdu, which handles both" },
];

// An engine picked by hand runs with none of the answer's settings: parakeet
// as the English answer runs it, whisper with the language detected. Measured
// as above; an engine with no measured speed here gets no estimate.
const HAND_PICKED_SPEED: Partial<Record<EngineName, number>> = { parakeet: 23.32, whisper: 2.49 };

/**
 * The options beyond the answer: the engine, picked by hand from every engine
 * the server lists, and the folded ones (Hashiya spec, Transcribe: "model,
 * prompt, skip speaker labels, fail if labelling fails, start over").
 */
export type Advanced = {
  /** An engine picked by hand, or null to use the answer's. */
  engine: EngineName | null;
  model: string;
  prompt: string;
  diarize: boolean;
  requireDiarize: boolean;
  startOver: boolean;
};

export function requestFor(choice: Choice, advanced: Advanced): TranscribeRequest {
  const engine = advanced.engine ?? choice.engine;
  // An engine picked by hand runs as itself: the answer's Roman Urdu and
  // language belong to the answer's engine (--roman-urdu would turn parakeet
  // back into whisper, dsj/suno.py roman_urdu).
  const own = engine === choice.engine;
  return {
    engine,
    model: advanced.model.trim() || null,
    language: own ? choice.language : null,
    prompt: engine === "whisper" ? advanced.prompt.trim() || null : null,
    roman_urdu: own && choice.roman_urdu,
    diarize: advanced.diarize,
    require_diarize: advanced.diarize && advanced.requireDiarize,
    start_over: advanced.startOver,
  };
}

/** The measured speed of what will run, or null when nothing here measured it. */
export function speedFor(choice: Choice, advanced: Advanced): number | null {
  const engine = advanced.engine ?? choice.engine;
  if (engine === choice.engine) return choice.speed;
  return HAND_PICKED_SPEED[engine] ?? null;
}

/** "About 25 minutes for this 42-minute recording", or null when its length is not known. */
export function expectedLabel(durationS: number | null, speed: number): string | null {
  if (durationS === null || durationS <= 0 || speed <= 0) return null;
  const minutes = Math.max(1, Math.round(durationS / speed / 60));
  const length = Math.max(1, Math.round(durationS / 60));
  return `About ${minutes} ${minutes === 1 ? "minute" : "minutes"} for this ${length}-minute recording`;
}

const DOLLARS = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

/**
 * What a run costs on an engine that charges (#247, the seam for a cloud
 * engine): "About $0.84 for this recording", or the hourly price when the
 * length is not known, or null for an engine that costs nothing.
 */
export function costLabel(durationS: number | null, usdPerHour: number | null): string | null {
  if (usdPerHour === null) return null;
  if (durationS === null || durationS <= 0) return `${DOLLARS.format(usdPerHour)} an hour of audio`;
  return `About ${DOLLARS.format((durationS / 3600) * usdPerHour)} for this recording`;
}
