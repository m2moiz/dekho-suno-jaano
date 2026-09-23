---
name: dsj
description: >
  Use when a screen recording, meeting video, lecture or voice note has to become a
  timestamped transcript; when someone asks what was said, or what was on screen, at a
  moment in a recording; when a frame has to be pulled out of a video by timestamp; or
  when a `dsj suno`, `dsj dekho` or `dsj dikhao` run needs polling, resuming, or
  reading after it failed. Also when a long recording must be made answerable without
  feeding the whole video to a vision model, when a transcript has to become SRT, VTT
  or text, or when an existing caption file has to stand in for a transcript.
metadata:
  version: 0.1.0
  tier: portable
  owner: moiz
  requires_bins: dsj, ffmpeg, jq, uv
  provenance: written in-repo alongside the CLI it documents, m2moiz/dekho-suno-jaano
  upstream: m2moiz/dekho-suno-jaano (.agents/skills/dsj)
---

# dsj

`dsj` turns a recording into a timestamped transcript that acts as an **index into the
video**. You read cheap text, notice a moment that only makes sense visually, and pull
that one frame. A 74-minute recording is about 444,000 tokens on a native-video model
against about 10,000 for its transcript.

Three verbs, in the order the tool works: `suno` (listen), `dekho` (look), `dikhao`
(show me). Two more work on the transcript alone: `likho` (write) turns a finished one
into subtitles or text for tools that are not dsj, and `parho` (read) turns a caption
file those tools made into a transcript, in place of `suno`.

## Before the first command

```bash
dsj --version
dsj --help
```

`dsj --version` prints `dsj` and the version of the build in front of you. This skill
was written against the `version` in its own header above. If the two differ, a flag
named below may not exist in that build, and using one fails as `No such option`, which
reads like a typo and is not one.

`dsj --help` lists the three verbs. There is no `dsj doctor`, and no way to ask the tool
which engine it has until you try to use one.

**From a clone, every command below needs a `uv run` prefix**, because `uv sync`
installs the command at `.venv/bin/dsj` and links it nowhere. An installed copy has
`dsj` on `PATH` and needs no prefix. Check which situation you are in before assuming a
missing command means a missing install.

`ffmpeg` must be on `PATH` for anything that is not already a 16 kHz mono wav.

## The three verbs

### suno

Transcribe. The only verb that checkpoints, so the only one worth interrupting rather
than restarting. Most of its wall clock on a default run is the speaker-labelling pass,
not the ASR: measured on 3:45 of meeting audio, ASR ran at 32x and diarization at 9.6x.

```bash
dsj suno recording.mov -o transcript.json
```

| Flag | |
|---|---|
| `-o, --out PATH` | **required.** Where the transcript JSON goes |
| `--status PATH` | write a JSON heartbeat, for runs you detach from |
| `--no-resume` | ignore any checkpoint and start over |
| `--no-diarize` | skip speaker labelling, which is the slow optional pass |
| `--require-diarize` | fail rather than degrade if labelling cannot run |
| `--model ID` | override the ASR model. The default follows `--engine` |
| `--engine ENGINE` | `parakeet` (default), `whisper`, or `sherpa` |
| `--language CODE` | whisper only. ISO code, for example `ur`. Detected if omitted |
| `--prompt TEXT` | whisper only. Seeds the decoder, biasing spelling and script |
| `--roman-urdu` | whisper only. Urdu written in Latin. Sets the two flags above |

Progress renders on stderr. **Nothing goes to stdout**, so empty stdout says nothing
about whether it worked.

parakeet runs at about 13x realtime and covers 25 languages, all European. For Urdu, or
anything else outside that set, use whisper, which is about 1.4x realtime, writes no
checkpoint, and reports no progress between start and finish:

```bash
dsj suno voice-note.m4a -o transcript.json --roman-urdu
```

Engine choice, the install bundles, and the extra step `--engine sherpa` needs are in
[references/engines.md](references/engines.md).

### dekho

Add the timestamps where the picture changed most. A second pass, because the
transcript arrives at about 13x realtime and this decodes every sampled frame at about
10x, so coupling them would make the fast half wait.

```bash
dsj dekho recording.mov -t transcript.json
```

| Flag | |
|---|---|
| `-t, --transcript PATH` | **required.** The transcript to add marks to |
| `-o, --out PATH` | write elsewhere instead of overwriting `--transcript` |
| `--budget N` | how many marks to keep (default 150) |
| `--min-gap SECONDS` | how far apart they must be (default 5) |
| `--fps N` | frames sampled per second of video (default 1) |
| `--delta N` | grey levels a tile must move to count (default 8) |

`--budget` rather than a sensitivity threshold, because during an active session the
screen changes most seconds, so "the screen changed" is not a rare event and cannot be
an index. Ranking under a fixed budget needs no per-video tuning.

### dikhao

Write one frame to an image file. Nothing is precomputed and nothing is cached, because
the video is already on disk and seeking into it is cheap.

```bash
dsj dikhao recording.mov 431.5 -o frame.jpg
```

| Flag | |
|---|---|
| `-o, --out PATH` | **required.** `.jpg` is what a vision model wants |
| `--width N` | scale to N pixels wide, aspect preserved (default 1500, `0` keeps source) |

This is the only command that writes to stdout, and it writes the output path and
nothing else, so it composes:

```bash
open "$(dsj dikhao recording.mov 431.5 -o /tmp/f.jpg)"
```

The 1500 px default is a measured ceiling: a full 2940 px frame is about 776 KB as a
JPEG, more than most vision APIs want, and legibility stopped improving well below that.

### likho

Export a transcript as SRT, WebVTT or plain text. It reads the JSON `suno` wrote and
runs no model, so it takes a moment, not minutes. Never write your own converter.

```bash
dsj likho transcript.json -o transcript.srt
dsj likho transcript.json -o captions.vtt
dsj likho transcript.json -o notes.txt
```

| Flag | |
|---|---|
| `-o, --out PATH` | **required.** Where the file goes. Its suffix picks the format |
| `--format FORMAT` | `srt`, `vtt` or `txt`, when the suffix does not say. Wins over it |

Any other suffix and no `--format` is a usage error, exit 2, and nothing is written.

- **SRT** is one cue per sentence, with the speaker's label ahead of the words, as
  `SPEAKER_01: ...`, when labelling ran.
- **VTT** is the same cues, voiced with `<v SPEAKER_01>`, and a timestamp tag ahead of
  every word that starts later than the one before it. It is the only one of the three
  that carries word timing.
- **TXT** is for a person: one block per speaker turn, headed `[1:02] SPEAKER_01`, or
  one `[1:02] ...` line per sentence when labelling did not run.

Cues run in time order and **never overlap**: each one ends no later than the next
begins, and nothing else about the times changes. A seam can leave a sentence ending
after the next one starts, and a player or muxer that keeps one cue at a time would
rewrite it. Measured on a 480-sentence transcript: the exported SRT muxed into its
recording and back with 0 of 480 cues changed, where 22 moved before.

Writes nothing to stdout. Transcripts from older builds, with no speakers, no token
ends or sentences out of order, export too.

### parho

Import a transcript instead of running ASR: a YouTube VTT, a subtitle track, a file
`likho` wrote, or a dsj transcript JSON. The result is the same JSON `suno` writes, so
`dekho`, `dikhao` and `likho` take it as they take a native one.

```bash
dsj parho recording.mov captions.vtt -o transcript.json
```

| Flag | |
|---|---|
| `-o, --out PATH` | **required.** Where the transcript JSON goes |

The recording comes first, as for every verb that indexes one, and must exist; it is
named in `audio`, not opened. The format is read from the content, never the suffix.

What the file could not hold, the transcript does not claim. `model` says where the
times came from, `import:srt` or `import:vtt`, and no imported token has a `c`:

- **SRT**: one token per sentence, spanning the cue, `t` its start and `e` its end.
- **VTT**: a cue with word timestamp tags splits into word tokens with a `t` each and
  no `e`, because a tag marks a start only. An untagged cue is one token, as for SRT.
- **JSON** must be a dsj transcript. It passes through unchanged but for `audio`.

Speakers come back from VTT voice tags, and from SRT only in the form `likho` writes,
`SPEAKER_01: ` ahead of the words. A file with no labels imports with no `speakers` and
no `diarization`, exactly like a transcript that was never labelled.

## The transcript is the index

Once a recording is transcribed, **every question about it is a query against the JSON**.
Re-running `suno` to find out what was said costs minutes and produces the same file.

```bash
# what was said between 400s and 460s
jq -r '.sentences[] | select(.start >= 400 and .start <= 460) | "\(.start)  \(.text)"' transcript.json
```

`.sentences` runs earliest to latest, and so do the `tokens` inside each one, so a reader
may walk it from the top and stop at the first `start` past its window. The order is
promised; the times are not exact. A recording over 120 s is transcribed in overlapping
pieces, and a word at a seam can be mistimed by a few seconds — measured worst case
5.72 s — which pulls its whole sentence that far earlier in the list.

A sentence's `text` is its `tokens` joined, each `w` in that time order with its leading
space, under every engine, and the top-level `text` is the sentences joined. So at a seam
a mistimed word reads out of place in the text as well: about 1 sentence in 100 moves a
word, and about 2 more move only punctuation. What the text shows and what a click on it
plays always agree.

When a question is visual, find the mark, then pull the frame:

```bash
jq -r '.marks | sort_by(-.score)[:5][] | "\(.score)  look at \(.look)s"' transcript.json
dsj dikhao recording.mov 431.5 -o /tmp/frame.jpg
```

**Feed `look` to `dikhao`, never `t`.** A mark is by construction the moment of maximum
change, which is the moment the screen is halfway between two states. Measured, a frame
at `t` differs from its neighbours in 9.9% of tiles against 2.2% at `look`. `t` tells you
when; `look` tells you where to point.

The full schema of every document dsj writes, with more query recipes, is in
[references/payload.md](references/payload.md).

## Long runs you do not sit and watch

An hour of audio is not something to block on. Detach it and poll the heartbeat:

```bash
dsj suno meeting.mov -o out.json --status run.json &
jq -r 'if .state == "failed" then "failed: \(.error)" else "\(.state) \((.fraction // 0) * 100 | floor)% eta \(.eta_s // "?")s" end' run.json
```

`state` moves `extracting` to `running` to `diarizing` to `done`, or becomes `failed`.
The file is one JSON object rewritten in full and replaced atomically, so a reader never
sees half of one.

Two things will break a poller that assumes otherwise:

- **Branch on `state`, never on `fraction`.** `fraction` is not monotonic. It reaches
  1.0 when the audio is decoded, drops back to 0.0 for the `diarizing` frames, and is 1.0
  again on the final frame, whose totals are the length of the audio. Observed across
  three separate runs: a poller that stops at `fraction == 1` calls it done before the
  speaker labels exist.
- **The failure document is a different shape**, two keys and no progress fields:
  `{"state": "failed", "error": "FileNotFoundError: /nope.mov"}`. Read `state` first.

`eta_s` is `null` whenever speed is 0, which includes the first frame of every run.

## Interrupting is cheap

A checkpoint is written beside the output every chunk, which is every 105 seconds of
audio, fsynced, and through a temporary file so an interrupt can only leave a whole one.
`-o transcript.json` gives `transcript.json.ckpt`.

**Re-running the same command resumes.** It prints `resuming from 1:45 (841 tokens
banked)` on stderr and picks up there. That holds during speaker labelling too: the
checkpoint is kept until labelling is over, so a run stopped in the `diarizing` state
transcribes nothing on the rerun and goes straight back to labelling.

Interrupting a run **you are watching in a terminal** is Ctrl-C. It exits 130.

Interrupting a run **you started in the background**, which is the normal case for an
agent, takes a plain `kill`:

```bash
dsj suno meeting.mov -o out.json --status run.json &
pid=$!
while [ ! -f out.json.ckpt ]; do sleep 0.5; done   # the first chunk has landed
kill "$pid"; wait "$pid"                           # exits 143, keeps the checkpoint
dsj suno meeting.mov -o out.json --status run.json # prints `resuming from 1:45`
```

Two things in that recipe are not decoration, and both were measured rather than assumed:

- **`kill`, not `kill -INT`.** A shell without job control, which is every non-interactive
  shell an agent runs in, starts a `&` job with SIGINT ignored. `kill -INT "$pid"` is
  swallowed silently: the run carries on to completion and `wait` returns 0. SIGTERM is
  not ignored, exits 143, and leaves the checkpoint exactly as SIGINT would.
- **Wait for the file, not for a `sleep`.** Nothing is banked until the first chunk
  finishes, so a kill before that throws the run away. A four-minute recording finishes in
  about ten seconds end to end, so a guessed delay either kills before the first bank or
  kills nothing at all.

From a clone the job is `uv run dsj suno ...`, and `uv run` starts the real process as a
child rather than replacing itself with it, so `$!` is the wrapper. `kill` still works,
because the signal reaches the child through it and the run exits 143. `kill -INT` on that
wrapper pid does nothing at all, which is the same dead end from the other direction.

The checkpoint knows the recording by its contents, not its name, so renaming, moving or
copying the file between the two runs still resumes. An edited recording, a changed
model or an upgraded engine invalidates it, and the run starts over rather than reusing
tokens that describe something else. That is correct, not an error, and it is not
silent: stderr says `checkpoint ignored, transcribing from the start:` and names the part
that changed. A checkpoint written by a dsj from before this rule is ignored the same
way, once.

`--no-resume` deletes the checkpoint rather than ignoring it. The whisper engine writes
none at all, so an interrupted whisper run always starts over.

## When something fails

| Exit | Meaning |
|---|---|
| 0 | Success |
| 1 | An uncaught exception, printed as a traceback on stderr |
| 2 | A usage error, including a `likho` format it cannot name. Run `dsj <verb> --help` |
| 130 | Interrupted. For `suno` on parakeet or sherpa, re-run to resume |

**Read the last line of stderr, not the first.** A failure is a traceback, and when
ffmpeg is involved its own log prints above the exception, so the useful sentence can be
twenty lines down:

```
[out#0/image2 @ 0x...] Nothing was written into output file ...
99999.0s is past the end of this 230.7s recording.
```

Diarization is the one pass that fails soft: if it cannot run, the transcript is still
written and still correct, a `diarization skipped:` warning goes to stderr, and the exit
code is 0. Detect it in the payload rather than the log, because `speakers` and
`diarization` are absent when the pass did not run. `--require-diarize` turns that into
a failure instead.

Every error class, its message, and its remedy are in
[references/failures.md](references/failures.md).

## References

- [references/payload.md](references/payload.md): the transcript, marks, heartbeat and
  checkpoint documents, field by field, and how to query them.
- [references/engines.md](references/engines.md): install bundles, choosing between
  parakeet, whisper and sherpa, Urdu, and the Android and proot constraints.
- [references/failures.md](references/failures.md): exit codes, every error class, and
  what each one wants you to do.
