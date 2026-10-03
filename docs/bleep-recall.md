# Do the engines write swear words down? (#152)

**Measured 3 Oct 2026 on synthetic speech, not yet on a real voice.** Every
word in dsj's shipped bleep lists was spoken by text-to-speech, alone and inside
short sentences, and transcribed by all three engine settings. Then `dsj hatao`
ran on each transcript.

Three answers:

1. **No engine censors.** Not one of 1,035 spoken words (345 per setting) came
   back with asterisks. When an engine hears an English swear word, it writes it
   down plainly.
2. **English is mostly written down; Urdu, Punjabi and Hindi mostly are not.**
   whisper writes 177 of 195 English words spoken alone as a list spelling,
   whisper `--roman-urdu` 182, parakeet 116. Of the Urdu, Punjabi and Hindi
   words spoken alone, no setting writes down more than 1 of 36, 1 of 30 or 2
   of 54. Most of those misses are another spelling or another word rather than
   nothing, and part of that is the synthetic voice: read "What this does not
   show" below.
3. **A word written down is not always a word muted.** Under `--roman-urdu`,
   182 English words were written down and matched, and `dsj hatao` silenced all
   of the spoken word for only 7 of them. The word's times in the transcript
   start about 1.6 s early, in the silence before it, and the 1.4 s cap on a
   muted word (`MAX_WORD_S`, #212) then cuts the mute off before the word is
   said. The bleep log lists every one as muted. #222 tracks it.

## The table

Each spoken word is put in exactly one class:

| class | means |
|---|---|
| written as listed | a spelling from the shipped lists, of that same word's entry, matched a word written at the time it was spoken |
| censored | a word written there carries asterisks, and no spelling matched |
| other word | something else is written there. In brackets: how many of those are within 2 letter edits of one of that entry's spellings (4 letters or more), so likely a spelling the list lacks |
| dropped | nothing is written there. In brackets: how many of those fall inside a stretch dsj took out as `unclear` |
| `dsj hatao` mutes all (part) | the render's muted spans cover 90% or more of the spoken word's audio; in brackets, some of it but less |

"Language" is the list the word comes from. "In a sentence" is one listed word
inside a short sentence, most of them switching language (an English sentence
with an Urdu word, an Urdu sentence with an English word, and so on).

| engine | language | spoken as | units | written as listed | censored | other word (near a spelling) | dropped | `dsj hatao` mutes all (part) |
|---|---|---|---|---|---|---|---|---|
| parakeet | en | in a sentence | 13 | 10 | 0 | 3 (0) | 0 | 9 (1) |
| parakeet | en | word alone | 195 | 116 | 0 | 60 (1) | 19 | 99 (17) |
| parakeet | ur | in a sentence | 10 | 0 | 0 | 5 (0) | 5 | 0 (0) |
| parakeet | ur | word alone | 36 | 0 | 0 | 29 (0) | 7 | 0 (0) |
| parakeet | pa | in a sentence | 5 | 1 | 0 | 2 (0) | 2 | 1 (0) |
| parakeet | pa | word alone | 30 | 1 | 0 | 19 (1) | 10 | 1 (0) |
| parakeet | hi | in a sentence | 2 | 0 | 0 | 0 (0) | 2 | 0 (0) |
| parakeet | hi | word alone | 54 | 2 | 0 | 25 (0) | 27 | 2 (0) |
| whisper | en | in a sentence | 13 | 11 | 0 | 1 (0) | 1 | 9 (2) |
| whisper | en | word alone | 195 | 177 | 0 | 13 (6) | 5 | 151 (18) |
| whisper | ur | in a sentence | 10 | 2 | 0 | 8 (1) | 0 | 2 (0) |
| whisper | ur | word alone | 36 | 1 | 0 | 35 (9) | 0 | 0 (1) |
| whisper | pa | in a sentence | 5 | 0 | 0 | 0 (0) | 5 | 0 (0) |
| whisper | pa | word alone | 30 | 0 | 0 | 25 (3) | 5 (3 inside `unclear`) | 0 (0) |
| whisper | hi | in a sentence | 2 | 0 | 0 | 2 (0) | 0 | 0 (0) |
| whisper | hi | word alone | 54 | 0 | 0 | 49 (0) | 5 | 0 (0) |
| whisper `--roman-urdu` | en | in a sentence | 13 | 12 | 0 | 1 (1) | 0 | 9 (3) |
| whisper `--roman-urdu` | en | word alone | 195 | 182 | 0 | 13 (9) | 0 | 7 (166) |
| whisper `--roman-urdu` | ur | in a sentence | 10 | 0 | 0 | 10 (2) | 0 | 0 (0) |
| whisper `--roman-urdu` | ur | word alone | 36 | 1 | 0 | 35 (9) | 0 | 0 (1) |
| whisper `--roman-urdu` | pa | in a sentence | 5 | 1 | 0 | 4 (1) | 0 | 0 (1) |
| whisper `--roman-urdu` | pa | word alone | 30 | 1 | 0 | 29 (8) | 0 | 0 (1) |
| whisper `--roman-urdu` | hi | in a sentence | 2 | 1 | 0 | 1 (0) | 0 | 1 (0) |
| whisper `--roman-urdu` | hi | word alone | 54 | 2 | 0 | 49 (21) | 3 | 0 (1) |

English words alone, by voice (65 each):

| engine | voice | written as listed | censored | other word | dropped |
|---|---|---|---|---|---|
| parakeet | Daniel (en_GB) | 44 | 0 | 15 | 6 |
| parakeet | Rishi (en_IN) | 33 | 0 | 26 | 6 |
| parakeet | Samantha (en_US) | 39 | 0 | 19 | 7 |
| whisper | Daniel | 58 | 0 | 2 | 5 |
| whisper | Rishi | 59 | 0 | 6 | 0 |
| whisper | Samantha | 60 | 0 | 5 | 0 |
| whisper `--roman-urdu` | Daniel | 58 | 0 | 7 | 0 |
| whisper `--roman-urdu` | Rishi | 60 | 0 | 5 | 0 |
| whisper `--roman-urdu` | Samantha | 64 | 0 | 1 | 0 |

Muted spans that cover no spoken listed word at all: parakeet 0, whisper 3,
`--roman-urdu` 2. Four sit in the silence after the last word of a file, where
whisper wrote an earlier listed word again; the fifth (`--roman-urdu`, mixed)
starts the same way but reaches back 0.26 s into the last sentence's closing
ordinary words.

## What was spoken

| set | what | voice | units | length |
|---|---|---|---|---|
| en_samantha, en_daniel, en_rishi | every `roman` spelling in `en.toml`, alone | macOS `say`: Samantha, Daniel, Rishi | 65 each | 133 to 138 s |
| ur | every `script` spelling in `ur.toml`, alone | `facebook/mms-tts-urd-script_arabic` | 36 | 75 s |
| pa | every `script` spelling in `pa.toml`, alone: Gurmukhi by `facebook/mms-tts-pan`, Shahmukhi by the Urdu model | MMS-TTS | 30 | 61 s |
| hi | every `script` spelling in `hi.toml`, alone | `facebook/mms-tts-hin` | 54 | 110 s |
| mixed | 30 short sentences with one listed word each: 9 English with an Urdu word, 7 Urdu with an English word, 3 English with a Punjabi word, 2 Punjabi with an English word, 1 Hindi with an English word, 2 English with a Hindi word, 1 Urdu, 2 Punjabi, 3 English | both, joined | 30 | 115 s |

A phrase spelling ("bhen chod") whose run-together form is also listed was spoken
once, run together. Disguised spellings ("f**k") cannot be spoken and were not.
Words alone sit 1.5 s apart; a sentence is its pieces spoken separately and
joined 60 ms apart, so where the listed word sits is known exactly. All audio is
16 kHz mono with a noise floor near -60 dBFS.

The MMS-TTS models are CC-BY-NC 4.0, at revisions `4c4f53d` (urd), `45d7962`
(pan) and `1d83b22` (hin), run through transformers 4.57.1 and torch 2.9.0 in a
throwaway environment, never added to dsj. The `say` voices are the ones shipped
with macOS 27.0.1. No public dataset was used.

## What was run

dsj 0.4.0 at `90a5259`, on a 16 GB M2, one model run at a time, every run with
`--no-diarize`. parakeet is `mlx-community/parakeet-tdt-0.6b-v3`; whisper and
`--roman-urdu` are both `mlx-community/whisper-large-v3-turbo`, the second with
language `ur` and dsj's Roman Urdu prompt.

```bash
uv run --no-project --python 3.12 --with transformers==4.57.1 --with torch==2.9.0 \
    --with numpy scratch/bleep_recall/make_audio.py
uv run python scratch/bleep_recall/score.py transcribe   # 21 runs of dsj suno
uv run python scratch/bleep_recall/score.py hatao        # 21 runs of dsj hatao
uv run python scratch/bleep_recall/score.py table
```

`transcribe` runs, for each set:

```bash
uv run dsj suno <set>.wav -o <out>.json --engine parakeet --no-diarize
uv run dsj suno <set>.wav -o <out>.json --engine whisper --no-diarize
uv run dsj suno <set>.wav -o <out>.json --roman-urdu --no-diarize
```

and `hatao` runs `uv run dsj hatao <set>.wav -t <out>.json -o <render>.wav` with
`DSJ_WORDS` pointed at a file that does not exist, so only the shipped lists
count. The audio, transcripts and renders stay under `scratch/bleep_recall/`,
which git ignores; the two scripts are tracked.

## What this does not show

1. **The Urdu, Punjabi and Hindi numbers are about the synthetic voice as much as
   the engine.** MMS-TTS reads a word from its spelling, one word with no
   sentence around it, and nobody has listened to check that it says each
   swear word the way a person does. The Urdu and Punjabi sentence frames did
   come back from `--roman-urdu` as recognisable Roman Urdu and Punjabi (read,
   not scored), so the voice is intelligible on ordinary words; whether it is
   on these words is unknown. A low count here is not yet evidence the engine drops the word.
2. **What the misses are.** Most Urdu, Punjabi and Hindi misses are "other
   word". Under `--roman-urdu`, 9 of 35 Urdu, 8 of 29 Punjabi and 21 of 49 Hindi
   ones are within 2 edits of a listed spelling: a Roman spelling the list does
   not hold, or a near-miss Urdu-script one. The rest are unrelated words, or a
   script the lists do not expect: plain whisper, with no language set, wrote
   Latin letters for the Urdu set, Devanagari for the Gurmukhi set and mostly
   Urdu script for the Devanagari set; `--roman-urdu` wrote Urdu script, not
   Roman, for the Devanagari set.
3. **Single words in silence are the hard case.** A recogniser leans on the
   words around a word. The sentence rows are the closer test, and they are
   small (30).
4. **`dsj hatao` was judged by numbers, not by ear.** "Mutes all" means the
   render's muted spans cover the word's audio; nobody listened to a render.

## What a person should confirm

1. Whether MMS-TTS says the Urdu and Punjabi words recognisably. Run
   `make_audio.py` (it writes the same audio again) and listen to
   `scratch/bleep_recall/audio/ur.wav` at 1.0 s (madarchod), 3.3 s and 5.3 s
   (behenchod), and `pa.wav` at 1.0 s and 3.1 s (penchod). The manifest beside
   them gives every word's time.
2. That the `--roman-urdu` render leaves words audible:
   `scratch/bleep_recall/renders/roman-urdu/en_samantha.wav` at 2.88 s to
   3.38 s, where the bleep log says a word is muted and the muted spans leave
   2.7 s to 3.24 s open (#222).
3. The real measurement: the owner's own recording (#152's Done-when). It
   replaces rows 2 and 3 of the first list above with a real voice.

`dsj hatao` still prints "unmeasured" for every engine: `RECALL` in
`dsj/hatao.py` stays empty until the owner's recording is measured, because
these Urdu numbers describe the synthetic voice as much as the engines.
