# The four documents dsj writes

## Contents

- The transcript, written by `suno`
- Speaker labels, added in place by the same run
- Marks, added by `dekho`
- Querying a transcript with jq
- The status heartbeat, written by `--status`
- The checkpoint, written beside `--out`

Every time value in every one of these documents is **seconds, as a float**, measured
from the start of the media. The single exception is `next_start` in the checkpoint,
which is a sample index. There are no milliseconds anywhere.

---

## The transcript, written by `suno`

Five keys, always, in this order:

```json
{
  "audio": "/path/to/recording.mov",
  "model": "mlx-community/parakeet-tdt-0.6b-v3",
  "text": "the whole transcript as one string",
  "unclear": [{"start": 134.1, "end": 161.8, "reason": "repetition loop", "words": 223}],
  "sentences": [
    {
      "start": 12.34,
      "end": 15.02,
      "text": " See this column here.",
      "tokens": [{"t": 12.34, "w": " See", "e": 12.43, "c": 0.998, "charOffset": 0},
                 {"t": 12.51, "w": " this", "e": 12.67, "c": 0.941, "charOffset": 4}]
    }
  ]
}
```

| Key | Type | Notes |
|---|---|---|
| `audio` | string | The path you passed, verbatim. Not resolved, and never the temporary wav. The transcript is an index into that file, so it has to keep pointing at it. |
| `model` | string | The resolved model id. There is no separate `engine` key; the model id names the engine. |
| `text` | string | Whole transcript, one string: every sentence's `text` joined, outer whitespace stripped. |
| `unclear` | array | Stretches dsj took out of `sentences` because what the engine returned there is not a transcript, earliest first. `[]` when there were none. Below. |
| `sentences` | array | Can be `[]` for silent media. That is a valid transcript, not a failure. |

Inside an `unclear` entry:

| Field | Type | Notes |
|---|---|---|
| `start`, `end` | float seconds | For a loop, the span of the sentence that was taken out, in whole milliseconds like a sentence's. For no speech, the silent stretch, to the 0.1 s frame. |
| `reason` | string | Why: `repetition loop` or `no speech`. |
| `words` | int | How many words the engine wrote there. The words themselves are not kept. |

**A repetition loop** is a sentence of more than six words, at most a third of them
distinct: whisper writing one letter or a short phrase over and over, up to about 220
times in one window. On four of the owner's recordings loops covered 133 to 752 seconds a
file, over audio as loud as the speech around them, so most mark speech whisper failed to
read, not silence. The text is no guide to what was said there, so it is left out of
`sentences` and `text`, and the span stays here so the gap is not read as a pause. Under
whisper each loop span is first decoded again on its own, with 2 s either side, once
without the prompt at temperature 0 and, if that loops too, once with the run's prompt at
temperature 0.4. Only the part of the span no other sentence covers is read again, and a
loop with no such part is left as it is. The first attempt
with no loop and more than five words in that part replaces the loop in `sentences`, cut
to it, so no word is written twice; a loop that survives both is recorded here. On four of the owner's transcripts the two attempts recovered 26 of the 37 loop
spans they tried, 551 of 787 loop seconds, at 42 to 129 s of extra wall time a file. The
second attempt samples, so a rerun can recover a different set. A
recovered span reads like any other sentence, and whether its words are right is not yet
measured. To know what was said in a span listed here, listen to it. On the five whisper transcripts
the rule was measured on, every sentence it matched was a loop. It runs under every
engine; on a parakeet transcript of a 17-minute English call it matched nothing.

**No speech** is a stretch of at least 5 s where every 0.1 s frame of the audio is quieter
than -55 dBFS, with words in it anyway: whisper wrote about 220 over a silent minute of the
public fixture. The level is read from the input file decoded to mono float, where ffmpeg
mixes a stereo recording at 0.707 of each channel, the scale the threshold was measured on. Every word that starts more than 1 s inside the stretch is taken out, and
the stretch is recorded with how many there were. A word within 1 s of its edge stays,
because whisper starts a real word up to half a second before its speech. Unlike a loop,
there is nothing to listen to: the audio is silent. The check runs before the loop check,
so a loop written over silence is reported as `no speech`. It runs under every engine. On
the measured set it found silence only on the fixture's three gaps and in one near-silent
passage of one of the owner's recordings, and nowhere in speech; the thresholds and their
measurement sit beside `SILENCE_DB` in `dsj/suno.py`.

**Test for the key.** Transcripts written before it existed have no `unclear`, and their
loops are still in `sentences`. Imports from SRT and VTT have none either: nothing checked
them.

Inside a sentence:

| Field | Type | Notes |
|---|---|---|
| `start`, `end` | float seconds | In whole milliseconds, like the token times, and never narrower than the sentence's own words: `start` is at or before the first token's `t`, `end` at or after the last `e`. Under whisper a sentence ends at or before the next one's `start`; under parakeet and sherpa one can overlap the next at a chunk seam (below). |
| `text` | string | Its tokens' `w` joined, in their time order, leading space included, under every engine. At a chunk seam a word the stitch mistimed reads out of place here too, about 1 sentence in 100. |
| `tokens` | array of objects | One per word piece, below. Can be `[]` for a whisper segment with no words. |

Inside a token:

| Field | Type | Notes |
|---|---|---|
| `t` | float seconds | When the token starts, in whole milliseconds: rounded to 3 places, as `e` is. Always present. |
| `w` | string | The token's text, leading space kept. `"".join(t.w)` over a sentence's tokens is exactly its `text`. Always present. |
| `e` | float seconds | When the token ends. Cut a word on `e`, never on the next token's `t`, which is wrong across every pause. In whole milliseconds like `t`, and never less than it, so `e - t` is a length and can be `0`. Measured by the decoder or inferred after it, depending on the engine: see below. |
| `c` | float, 0 to 1 | How sure the model was of the token; higher is surer. Rounded to 3 places. What it is computed from depends on the engine, below, so a threshold tuned on one engine does not carry to another. |
| `charOffset` | int | Where `w` starts in the sentence's `text`, so `text[charOffset:charOffset + len(w)]` is `w`. It maps a click or a selection on rendered text back to a token. Counted in code points, as Python's `len` counts; JavaScript counts UTF-16 units, and the two differ for any character outside the Basic Multilingual Plane, such as an emoji. Written under every engine, and absent from transcripts written before it existed. |

**Every engine writes `e` and `c`, and they mean different things under each.** There is
no `engine` key; `model` names the engine, and this table says what its token times and
confidences are:

| Engine | `model` | `t` and `e` | `c` |
|---|---|---|---|
| parakeet | a hub id, `mlx-community/parakeet-tdt-0.6b-v3` by default | **Measured.** The decoder emits each token at an encoder frame, with a duration of whole 0.08 s frames. | One minus the normalised entropy of the decoder's whole distribution at that step. About half its tokens read `1.0`. |
| sherpa | a local model directory, `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` by default | **Measured**, the same way: the same TDT model and the same duration head. | The probability the decoder gave the token it emitted, exp of its log-probability. sherpa exposes only that, not the distribution parakeet's entropy is taken over. |
| whisper | a hub id naming whisper, `mlx-community/whisper-large-v3-turbo` by default | **Inferred.** whisper times each word after decoding it, by aligning its cross-attention to the audio, then shortens words it judges too long. How far that lands from the real boundary is not yet measured here, so pad a cut rather than trusting it to the frame. | The mean of the probabilities the model gave the word's sub-word tokens. |
| `dsj parho`, from SRT | `import:srt` | **The file's.** One token per sentence, spanning the cue: `t` and `e` are the cue's start and end, and nothing finer is known. | **Absent.** Nothing measured it. |
| `dsj parho`, from WebVTT | `import:vtt` | **The file's.** A cue with timestamp tags splits into word tokens, `t` from each tag, and **no `e`**: a tag marks where a word starts, not where it ends. An untagged cue is one token with `t` and `e`, as for SRT. | **Absent.** |

Test for the key, never assume it. `e` and `c` are absent from every transcript written
before they existed: parakeet's before #56, sherpa's and whisper's before #77. An import
never has `c`, and has `e` only on a token that spans its whole cue. `t` and `w` are in
all of them.

Transcripts written before #174 have an unrounded `t`, `107.60000000000001` for instance,
and on a zero-length token that can sit a hair above its rounded `e`. Clamp `e - t` at
zero when reading one of those.

Zero-length tokens are real, not an error: parakeet emits them for some subword
continuations, and whisper times nearly one word in four that way on mixed English and
Urdu (159 of 686 on a 3-minute clip). A zero-length word cannot be muted by its own span.

An imported transcript that names speakers (VTT voice tags, or SRT's `SPEAKER_01: `
prefix) carries `speakers` and a `speaker` per sentence like a labelled one, with
`diarization` set to the same `import:vtt` or `import:srt` as `model`. A JSON import is a
dsj transcript and keeps its own `model`: only `audio` changes.

`tokens` is the load-bearing half. Speaker labelling votes tokens against the diarizer's
turns, so an engine that could only give sentence boundaries could be transcribed but not
attributed.

## Speaker labels, added in place by the same run

When diarization ran, two keys appear **immediately after `model`**, and every sentence
gains one field after its `end`:

```json
{
  "audio": "...",
  "model": "...",
  "speakers": ["SPEAKER_00", "SPEAKER_01"],
  "diarization": "senko 0.1.0",
  "text": "...",
  "sentences": [{"start": 12.34, "end": 15.02, "speaker": 0, "text": "...", "tokens": []}]
}
```

`speaker` is an **integer index into `speakers`**, never a name. It is an arbitrary
per-file cluster id: `SPEAKER_01` in one recording has nothing to do with `SPEAKER_01` in
another. It can be `null` for a sentence whose tokens fell outside every turn.

**The absence of `speakers` and `diarization` is information.** Without them you cannot
tell "diarization did not run" from "diarization ran and found one speaker". Test for the
key, not for the length of the list:

```bash
jq 'has("diarization")' transcript.json
```

Diarization is fail-soft. If senko cannot run, or crashes while it runs, the transcript
is still written, still correct, and simply carries no labels, and a `diarization
skipped: ...` or `speaker labelling failed, ...` line goes to stderr. `--require-diarize`
turns that into a failure instead.

## Marks, added by `dekho`

Two keys land beside `sentences`, never inside it, and a re-run replaces both wholesale:

```json
{
  "marks": [{"t": 417.0, "score": 2841, "look": 431.5}],
  "marks_meta": {"source": "/path/to/recording.mov", "fps": 1.0, "grid": [128, 84],
                 "delta": 8, "budget": 150, "min_gap_s": 5.0, "frames_sampled": 1997}
}
```

| Field | Type | Meaning |
|---|---|---|
| `t` | float seconds | When the picture changed. The boundary. |
| `score` | int | How many tiles of the 128x84 grid moved, so at most 10752. It ranks the size of the transition, and says nothing about whether the content matters. |
| `look` | float seconds | The middle of the stretch that screen was up. |

**Feed `look` to `dikhao`, never `t`.** A mark is by construction the moment of maximum
change, which is the moment the screen is halfway between two states: mid-load skeletons,
half-drawn window switches. Measured, a frame at `t` differs from its neighbours in 9.9%
of tiles against 2.2% at `look`. Use `t` to know when, `look` to know where to point.

`marks` is in ascending time order, not ranked order. It can be `[]`.

`marks_meta` travels with the marks because marks from a budget of 150 and marks from a
budget of 20 are different documents.

## Querying a transcript with jq

The transcript is an index into the video. Query it. Never re-run `suno` to answer a
question about a recording you have already transcribed.

```bash
# what was said between 400s and 460s
jq -r '.sentences[] | select(.start >= 400 and .start <= 460) | "\(.start)  \(.text)"' t.json

# the sentence covering one moment, 431.5s here
jq -r '.sentences[] | select(.start <= 431.5 and .end >= 431.5) | .text' t.json

# the five biggest visual changes, with the second to extract a frame from
jq -r '.marks | sort_by(-.score)[:5][] | "score \(.score)  change \(.t)s  look \(.look)s"' t.json

# every mark with the line being spoken at its look time
jq -r '. as $d | $d.marks[] | . as $m
       | ($d.sentences[] | select(.start <= $m.look and .end >= $m.look) | .text) // ""
       | "\($m.look)\t\(.)"' t.json

# who spoke, if labels exist
jq -r 'if has("speakers") then [.sentences[].speaker] | group_by(.) | map({s: .[0], n: length})
       else "unlabelled" end' t.json

# plain text, no timings
jq -r '.text' t.json

# where the transcript has nothing usable, and why
jq -r '(.unclear // [])[] | "\(.start)-\(.end)  \(.reason)  \(.words) words"' t.json
```

**`sentences` runs earliest first, and so do the `tokens` inside each one**, under every
engine: sentences by `start`, tokens by `t`. A reader may walk the list from the top and
stop at the first `start` past its window; there is nothing to re-sort. The order is
promised; the times are not exact. A recording over 120 s is transcribed in overlapping
pieces, and a word at a seam can be mistimed by a few seconds, measured worst case 5.72 s,
which pulls its whole sentence that far earlier in the list.

**Under whisper no two sentences overlap**: each ends at or before the next one's
`start`. Each of the 6 s two of whisper's two-minute windows share is written by one of
them, its own half by default or all of it by the one that did not loop there, so the same
speech is not written twice at a seam (#190); two whisper sentences that still overlap are
written as one, every word and time as decoded. **Under parakeet and sherpa they can
overlap** at a chunk seam: a word timed seconds early starts its sentence inside the one
before, 1 pair on a 6-minute parakeet run. They are left apart, because one merged
sentence would put two speakers under one label (#192).

## The status heartbeat, written by `--status`

One JSON object, rewritten in full on every update, replaced atomically so a reader never
sees half of one. It is not a log and not JSONL.

```json
{"audio_done_s": 1872.0, "audio_total_s": 4447.0, "elapsed_s": 89.4,
 "resumed_from_s": 0.0, "state": "running", "pid": 48213, "fraction": 0.4209,
 "speed": 20.94, "eta_s": 122.9}
```

| Field | Type | Notes |
|---|---|---|
| `state` | string | `extracting`, `running`, `retrying`, `diarizing`, `done`, `failed`, or `interrupted`. **This is the only reliable completion signal.** |
| `pid` | int | The process that wrote the document. In every document, the failure and interrupted ones included. Below: how to tell a dead run from a slow one with it. |
| `audio_done_s`, `audio_total_s` | float seconds | Of audio, not wall clock. |
| `elapsed_s` | float seconds | Wall clock **for the current phase**, not for the run. Extraction and transcription each restart it, because one runs at about 1000x realtime and the other at about 13x, so a shared clock would make both speeds meaningless. |
| `resumed_from_s` | float seconds | Audio a previous run already transcribed. `0.0` otherwise. |
| `fraction` | float | Rounded to 4 places. Not clamped, and see the warning below. |
| `speed` | float | Realtime multiple over this run's own work only. |
| `eta_s` | float or **null** | `null` whenever `speed` is 0, which includes the first frame of every run. |
| `stalled_s` | float seconds | `extracting` frames only, and **only while** ffmpeg's position has not moved for 60 s or more: how long it has stood still. Absent otherwise, so test for the key. Below. |

**Poll `state`. Do not use `fraction` to detect completion.** `fraction` reaches `1.0`
when the audio is decoded, which is before the speaker labels exist, then starts over at
`0.0` for the `diarizing` frames. The final `done` frame reports the length of the audio
as both `audio_done_s` and `audio_total_s`, the same total the `running` frames used, so
it ends at `1.0` whether or not anyone spoke: a four-minute recording with no speech ends
with `{"audio_done_s": 240.0, "audio_total_s": 240.0, "state": "done", "fraction": 1.0}`.

**The failure document is a different shape.** Three keys, and none of the progress fields:

```json
{"state": "failed", "pid": 48213, "error": "FileNotFoundError: /nope.mov"}
```

Anything reading `.fraction` unconditionally crashes on it, jq included: `.fraction * 100`
against this document is `null (null) and number (100) cannot be multiplied`, and jq exits
5. Branch on `state` first and default the rest. This is SKILL.md's polling recipe, and it
reads all three shapes:

```bash
jq -r 'if .state == "failed" then "failed (pid \(.pid // "?")): \(.error)"
  elif .state == "interrupted" then "interrupted by \(.signal) (pid \(.pid))"
    + if .during then " during \(.during) at \(.audio_done_s | floor)s of \(.audio_total_s | floor)s" else " before its first frame" end
  else "\(.state) \((.fraction // 0) * 100 | floor)% eta \(.eta_s // "?")s (pid \(.pid // "?"))"
    + if .stalled_s then ", stalled for \(.stalled_s | floor)s" else "" end
  end' run.json
```

`error` is `"<ExceptionClassName>: <message>"`.

**A stopped run says so.** Ctrl-C (SIGINT) and a plain `kill` (SIGTERM) write a third
shape before the process exits, 130 and 143 respectively:

```json
{"state": "interrupted", "pid": 48213, "signal": "SIGTERM", "during": "running",
 "audio_done_s": 105.0, "audio_total_s": 300.0}
```

`signal` is `SIGINT` or `SIGTERM`. `during` is the state of the last frame written before
the signal, and `audio_done_s` and `audio_total_s` are that frame's, so they count
extraction if `during` is `extracting`. `during`, `audio_done_s` and `audio_total_s` are
absent when the signal arrived before the first frame, while the model was loading. `interrupted` is terminal: nothing
writes to the file again. Do not wait on it. A parakeet or sherpa run resumes from its
checkpoint when the same command is run again. A whisper run resumes only if `during` is
`retrying` or `diarizing`, past its decode; stopped while `running`, it starts over. `kill -9`
cannot be caught, so it writes nothing and the file keeps its last frame.

**Dead or slow: ask the process table, not the clock.** A run ended by `kill -9`, by the
system under memory pressure, or by a crash of the machine writes nothing, so its file
keeps saying `running` forever. Before trusting a frame whose `state` is not `done`,
`failed` or `interrupted`, check its `pid`:

```bash
pid=$(jq -r '.pid' run.json)
if kill -0 "$pid" 2>/dev/null; then echo alive; else echo "gone: the run died"; fi
```

Alive means alive, however long since the last frame: a plain whisper run writes one
frame at 0% and nothing more until it ends. Gone, on a non-terminal frame, means the run
died without a word; the same command resumes it on parakeet and sherpa, and on whisper
once its decode had ended. Three limits.
The check only works on the machine that ran the job, not on a status file read from
another. A pid is reused eventually, so on a frame hours old confirm it is still dsj with
`ps -p "$pid" -o command=`. And a status file written before `pid` existed has none, so
the only signal there is the file's mtime against the cadence table below.

**A stalled extraction says so, and is not stopped.** On 2026-09-22 ffmpeg sat at 4:20 of
a 27:52 recording for over 15 minutes, still reporting, and then finished. The process
was alive throughout, so `pid` reads alive, and every frame was fresh, so the file's
mtime looked healthy; only `audio_done_s` had stopped. Now an `extracting` frame carries
`stalled_s` once the position has stood still for a minute, and loses it as soon as it
moves:

```json
{"audio_done_s": 260.0, "audio_total_s": 1672.0, "elapsed_s": 923.0, "resumed_from_s": 0.0,
 "state": "extracting", "pid": 48213, "fraction": 0.1555, "speed": 0.28, "eta_s": 5012.6,
 "stalled_s": 903.4}
```

Report it; do not kill the job for it. Why that extraction stalled is not known, and
killing a run that would have finished costs the whole run. A machine short of memory
(`memory_pressure`) or a recording that is still downloading from a cloud drive are the
two suspects, neither reproduced. `stalled_s` is computed when ffmpeg reports, about
twice a second; an ffmpeg that stops reporting altogether stops the frames too, and then
the file's mtime is what goes stale.

**Stop the job you started, and only that one:** `kill "$(jq -r .pid run.json)"`. Never
`pkill -f 'dsj suno'`, which stops every run on the machine, another session's included.
The pid is the Python process doing the work, so this holds under `uv run` too, where `$!`
is uv's wrapper.

How often each state is written:

| State | Cadence |
|---|---|
| `extracting` | About twice a second, and only when the input is not already a 16 kHz mono wav |
| `running` (parakeet, sherpa) | Once per chunk, so once per 105 seconds of audio |
| `running` (whisper) | With `--roman-urdu`, once per window of about two minutes: dsj cuts the windows itself. Any other whisper run, **once, at 0%**, then nothing until transcription ends: mlx-whisper takes no progress callback |
| `retrying` | whisper only, and only when it wrote a repetition loop over audio that is not silent: once before the first loop span is decoded again, then once after each. `audio_done_s` and `audio_total_s` count the seconds of those loop spans, not the recording, so `fraction` and `eta_s` describe the retry |
| `diarizing` | **Exactly twice**, at the start and the end. Senko has no per-chunk callback and inventing a bar would be a lie |
| `done` | Once |

With no `--status`, no file is created anywhere.

## The checkpoint, written beside `--out`

Path is `--out` plus `.ckpt`, so `-o transcript.json` gives `transcript.json.ckpt`. It is
a sibling of the output because a later process has nothing else to find it by.

```json
{"media": "/recordings/golden.m4a",
 "fingerprint": {"schema": 2,
                 "content_id": "48213977-23b1481c23935d480d899ec7fdf8f6074570e4bfce9b729e770c7de22d39a65a",
                 "total_samples": 71424000, "model_id": "mlx-community/parakeet-tdt-0.6b-v3",
                 "chunk_s": 120.0, "overlap_s": 15.0, "parakeet_version": "0.5.2"},
 "next_start": 1680000,
 "tokens": [{"id": 0, "text": " the", "start": 0.08, "duration": 0.24, "confidence": 1.0}]}
```

`next_start` is a **sample index**, not seconds. Divide by the engine's sample rate to
read it as a time. That rate comes from the loaded model rather than from a constant, and
is 16000 for the parakeet and sherpa defaults, so `1680000` there is 105 seconds.

Written once per chunk, fsynced, and always through a temporary file plus a rename, so an
interrupt can only ever leave a whole one. It is removed once the transcript is on disk
**and** speaker labelling is over, not before. While labelling runs it holds every token
through the end of the audio, so a run interrupted then resumes past the last chunk,
transcribes nothing, and goes straight back to labelling.

Every field of the fingerprint must match for the checkpoint to be used. Any of these
invalidates it, and the run starts over: editing the source, a different `--model`, an
upgraded engine package, a schema bump, or an ffmpeg upgrade that decodes the same
untouched file to a different number of samples. A mismatch is not an error. The stored
tokens simply describe something else.

It is not silent either. A checkpoint that exists and is not used prints one line on
stderr naming the field that failed, which is how it differs from having no checkpoint:

```
checkpoint ignored, transcribing from the start: the recording's contents changed (content_id)
```

`content_id` names the recording by its contents: its size in bytes, a dash, then a
SHA-256 of its first and last MiB. Renaming, moving or copying the recording between two
runs changes none of that, so the run resumes. `media` is the resolved path the run read,
kept beside the fingerprint for a person and never compared. There is no mtime: a plain
`cp` changes it, and the content id already catches an edit. The one edit it cannot see
is a change confined to the middle of the file that keeps its size exactly.

Checkpoints written before `content_id` existed are schema 1, keyed on path, size and
mtime. They cannot match, so a run interrupted on an older dsj starts over once, and says
`it was written by another version of dsj, checkpoint schema 1 where this one reads 2`.

`sherpa` contributes `sherpa_onnx_version` where parakeet contributes `parakeet_version`,
so a checkpoint cannot cross engines even if every shared value matched.

### whisper's banked result

whisper decodes the whole recording in one call, so there is no chunk to bank while it
runs. The moment the call returns, before loops are decoded again and before speakers are
labelled, its result is banked at the same path, fsynced, and kept until labelling is
over. A run stopped in `retrying` or `diarizing` therefore decodes nothing on the rerun:
it retries the loops and labels again from the banked result. A run stopped in `running`
has banked nothing and starts over.

```json
{"media": "/recordings/voice-note.m4a",
 "fingerprint": {"schema": 2,
                 "content_id": "1048576-5a1b0c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
                 "model_id": "mlx-community/whisper-large-v3-turbo",
                 "mlx_whisper_version": "0.4.3", "language": "ur",
                 "prompt": "Yeh Roman Urdu transcript hai.", "anchor_s": "120.0",
                 "anchor_overlap_s": "6.0", "hallucination_silence_s": "None"},
 "transcription": {"text": "...", "sentences": []}}
```

`transcription` is whisper's text and sentences as it returned them, in the transcript's
own sentence shape. Every fingerprint field must match. `language`, `prompt` and the two
`anchor_` fields are what `--language`, `--prompt` and `--roman-urdu` set, and each
changes what whisper writes, so a rerun with another of any of them decodes again and
says so: `checkpoint ignored, transcribing from the start: the prompt changed (prompt)`.
Values are strings, and `"None"` means the setting was not given. `--no-resume` deletes
the file as it deletes a chunk checkpoint.
