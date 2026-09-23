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

Four keys, always, in this order:

```json
{
  "audio": "/path/to/recording.mov",
  "model": "mlx-community/parakeet-tdt-0.6b-v3",
  "text": "the whole transcript as one string",
  "sentences": [
    {
      "start": 12.34,
      "end": 15.02,
      "text": " See this column here.",
      "tokens": [{"t": 12.34, "w": " See", "e": 12.43, "c": 0.998},
                 {"t": 12.51, "w": " this", "e": 12.67, "c": 0.941}]
    }
  ]
}
```

| Key | Type | Notes |
|---|---|---|
| `audio` | string | The path you passed, verbatim. Not resolved, and never the temporary wav. The transcript is an index into that file, so it has to keep pointing at it. |
| `model` | string | The resolved model id. There is no separate `engine` key; the model id names the engine. |
| `text` | string | Whole transcript, one string: every sentence's `text` joined, outer whitespace stripped. |
| `sentences` | array | Can be `[]` for silent media. That is a valid transcript, not a failure. |

Inside a sentence:

| Field | Type | Notes |
|---|---|---|
| `start`, `end` | float seconds | |
| `text` | string | Its tokens' `w` joined, in their time order, leading space included, under every engine. At a chunk seam a word the stitch mistimed reads out of place here too, about 1 sentence in 100. |
| `tokens` | array of objects | One per word piece, below. Can be `[]` for a whisper segment with no words. |

Inside a token:

| Field | Type | Notes |
|---|---|---|
| `t` | float seconds | When the token starts. Always present. |
| `w` | string | The token's text, leading space kept. `"".join(t.w)` over a sentence's tokens is exactly its `text`. Always present. |
| `e` | float seconds | When the token ends, as the decoder timed it. Cut a word on `e`, never on the next token's `t`, which is wrong across every pause. Rounded to 3 places. |
| `c` | float, 0 to 1 | The decoder's confidence in the token: one minus the normalised entropy of its distribution at that step. Rounded to 3 places, so about half of parakeet's tokens read `1.0`. |

**`e` and `c` are parakeet's only.** Test for the key, never assume it. They are absent
under sherpa, whose end is the next token's start and whose confidence is a default, so
writing either would present a guess as a measurement. They are absent under whisper,
which does not carry them through yet. And they are absent from every transcript written
before they existed. `t` and `w` are in all of them.

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

Diarization is fail-soft. If senko cannot run, the transcript is still written, still
correct, and simply carries no labels, and a `diarization skipped: ...` line goes to
stderr. `--require-diarize` turns that into a failure instead.

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
```

**Do not assume `sentences` is sorted.** It is very nearly in ascending `start` order and
never guaranteed to be: 4 of 480 consecutive pairs came back out of order in a real
multi-chunk transcript, at chunk boundaries. Filter the whole list rather than scanning
until the first `start` past your window, or `sort_by(.start)` first if order matters.

## The status heartbeat, written by `--status`

One JSON object, rewritten in full on every update, replaced atomically so a reader never
sees half of one. It is not a log and not JSONL.

```json
{"audio_done_s": 1872.0, "audio_total_s": 4447.0, "elapsed_s": 89.4,
 "resumed_from_s": 0.0, "state": "running", "fraction": 0.4209,
 "speed": 20.94, "eta_s": 122.9}
```

| Field | Type | Notes |
|---|---|---|
| `state` | string | `extracting`, `running`, `diarizing`, `done`, or `failed`. **This is the only reliable completion signal.** |
| `audio_done_s`, `audio_total_s` | float seconds | Of audio, not wall clock. |
| `elapsed_s` | float seconds | Wall clock **for the current phase**, not for the run. Extraction and transcription each restart it, because one runs at about 1000x realtime and the other at about 13x, so a shared clock would make both speeds meaningless. |
| `resumed_from_s` | float seconds | Audio a previous run already transcribed. `0.0` otherwise. |
| `fraction` | float | Rounded to 4 places. Not clamped, and see the warning below. |
| `speed` | float | Realtime multiple over this run's own work only. |
| `eta_s` | float or **null** | `null` whenever `speed` is 0, which includes the first frame of every run. |

**Poll `state`. Do not use `fraction` to detect completion.** On the final `done` frame,
`audio_done_s` and `audio_total_s` are rebuilt from the end of the last sentence rather
than the duration of the audio, so `fraction` is `1.0` when the transcript has sentences
and `0.0` when it has none. Both mean finished. A four-minute recording with no speech
ends with `{"state": "done", "fraction": 0.0}`.

**The failure document is a different shape.** Two keys, and none of the progress fields:

```json
{"state": "failed", "error": "FileNotFoundError: /nope.mov"}
```

Anything reading `.fraction` unconditionally crashes on it, jq included: `.fraction * 100`
against this document is `null (null) and number (100) cannot be multiplied`, and jq exits
5. Branch on `state` first and default the rest:

```bash
jq -r 'if .state == "failed" then "failed: \(.error)" else "\(.state) \((.fraction // 0) * 100 | floor)%" end' run.json
```

`error` is `"<ExceptionClassName>: <message>"`.

How often each state is written:

| State | Cadence |
|---|---|
| `extracting` | About twice a second, and only when the input is not already a 16 kHz mono wav |
| `running` (parakeet, sherpa) | Once per chunk, so once per 105 seconds of audio |
| `running` (whisper) | **Once, at 0%**, then nothing until the end. Whisper owns its own window loop and exposes no hook |
| `diarizing` | **Exactly twice**, at the start and the end. Senko has no per-chunk callback and inventing a bar would be a lie |
| `done` | Once |

With no `--status`, no file is created anywhere.

## The checkpoint, written beside `--out`

Path is `--out` plus `.ckpt`, so `-o transcript.json` gives `transcript.json.ckpt`. It is
a sibling of the output because a later process has nothing else to find it by.

```json
{"fingerprint": {"schema": 1, "media": "/recordings/golden.m4a", "media_size": 48213977,
                 "media_mtime_ns": 1755087412000000000, "total_samples": 71424000,
                 "model_id": "mlx-community/parakeet-tdt-0.6b-v3",
                 "parakeet_version": "0.5.2", "chunk_s": 120.0, "overlap_s": 15.0},
 "next_start": 1680000,
 "tokens": [{"id": 0, "text": " the", "start": 0.08, "duration": 0.24, "confidence": 1.0}]}
```

`next_start` is a **sample index**, not seconds. Divide by the engine's sample rate to
read it as a time. That rate comes from the loaded model rather than from a constant, and
is 16000 for the parakeet and sherpa defaults, so `1680000` there is 105 seconds.

Written once per chunk, fsynced, and always through a temporary file plus a rename, so an
interrupt can only ever leave a whole one. It is removed once the transcript is on disk.

Every field of the fingerprint must match for the checkpoint to be used. Any of these
invalidates it, silently and correctly, and the run starts over: moving or renaming the
source, editing it, touching it, a different `--model`, an upgraded engine package, a
schema bump, or an ffmpeg upgrade that decodes the same untouched file to a different
number of samples. A mismatch is not an error. The stored tokens simply describe
something else.

There is no content hash. Invalidation is resolved path, size, mtime in nanoseconds, and
decoded sample count.

`sherpa` contributes `sherpa_onnx_version` where parakeet contributes `parakeet_version`,
so a checkpoint cannot cross engines even if every shared value matched.
