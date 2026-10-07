---
name: dsj
description: >
  Use when a screen recording, meeting video, lecture or voice note has to become a
  timestamped transcript; when someone asks what was said, or what was on screen, at a
  moment in a recording; when a frame has to be pulled out of a video by timestamp; or
  when a `dsj suno`, `dsj dekho` or `dsj dikhao` run needs polling, resuming, or
  reading after it failed. Also when a long recording must be made answerable without
  feeding the whole video to a vision model, when a transcript has to become SRT, VTT
  or text, when an existing caption file has to stand in for a transcript, or when
  swear words or other listed words have to be bleeped out of a recording.
metadata:
  version: 0.4.2
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
file those tools made into a transcript, in place of `suno`. `hatao` (remove it) writes a
copy of the recording with the words a word list flags muted. The seventh, `ui`, is for a
person rather than an agent: it opens the app in a browser.

The transcript is one JSON object. Its top-level keys are `audio`, `engine`, `model`,
`text`, `unclear` and `sentences`, plus `speakers` and `diarization` when speaker labelling ran
and `marks` once `dekho` has run. Each entry in `sentences` has `start`, `end`, `text`
and `tokens`, plus `speaker` when labelled. There is no `segments` or `chunks` key. Every
field is in [references/payload.md](references/payload.md).

## Before the first command

**On a Mac, run dsj in the Mac's own shell.** If your shell is a Linux sandbox or VM with
a Mac checkout mounted into it, `uname -s` prints `Linux` rather than `Darwin`: stop, and
do not run `uv run`, `uv sync` or `just` against that checkout. uv finds a `.venv` whose
interpreter link points at a macOS path it cannot see, deletes the whole `.venv`, and
rebuilds it for Linux. That breaks the Mac's install, including a job already running
there, and the Linux rebuild cannot run the Mac engines anyway. The phone bundle is a
separate install inside its own proot container; see
[references/engines.md](references/engines.md).

```bash
uname -s        # Darwin, on the Mac a clone of this repo was made for
dsj --version
dsj --help
```

`dsj --version` prints `dsj` and the version of the build in front of you. This skill
was written against the `version` in its own header above. If the two differ, a flag
named below may not exist in that build, and using one fails as `No such option`, which
reads like a typo and is not one.

`dsj --help` lists the seven verbs. There is no `dsj doctor`, and no way to ask the tool
which engine it has until you try to use one.

**From a clone, every command below needs a `uv run` prefix**, because `uv sync`
installs the command at `.venv/bin/dsj` and links it nowhere. An installed copy has
`dsj` on `PATH` and needs no prefix. Check which situation you are in before assuming a
missing command means a missing install.

`ffmpeg` must be on `PATH` for anything that is not already a 16 kHz mono wav.

**The checkout may not be yours alone.** Another session may be running dsj, or editing
it, from the same clone. Run `git status` before you start and before you stop, and never
touch a file it already shows as modified. Stop only a job you started, by its pid: `$!`
when you started it with `&`, or the `pid` its `--status` file records. Never
`pkill -f 'dsj suno'`, which matches every dsj run on the machine, another session's
included.

**If a usage task turns into changing dsj**, even when you were asked to, file an issue
for the change before running the patched tool, and put a measurement, with the command
that produced it, behind any constant you introduce. Then gate it as
[Changing dsj itself](#changing-dsj-itself) says.

## The seven verbs

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

A run that finishes also adds its recording and transcript to the library `dsj ui`
lists (`$DSJ_LIBRARY` when set), with no `ui` extra needed. If the library cannot be
written, stderr says `transcript not added to the library at <path>` with the error's
class, the transcript is kept, and the exit code is still 0.

parakeet runs at about 13x realtime and covers 25 languages, all European. For Urdu, or
anything else outside that set, use whisper, which is about 1.7 to 3x realtime on Urdu with
`--roman-urdu` and about 5 to 6x on English (measured per file in
[references/engines.md](references/engines.md#whisper-speed)) and banks nothing until it has decoded the whole recording. A `--roman-urdu` run reports progress once per speech clip of up to 30 s;
any other whisper run reports 0% and then nothing until transcription ends:

```bash
dsj suno voice-note.m4a -o transcript.json --roman-urdu
```

`--roman-urdu` is for Urdu and English mixed in one sentence. For speech that is mostly
Urdu, `--engine whisper --language ur` makes about half the errors (21 to 23% of words
against 41 to 43% on a public Urdu set), written in Urdu script. Measured per mode in
[references/engines.md](references/engines.md#which-mode-by-error-rate).

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

### hatao

Bleep: write a copy of the recording with every word a word list flags muted. It reads
the transcript `suno` wrote, runs no model, and never writes to the recording.

```bash
dsj hatao recording.mov -t transcript.json -o clean.mov
```

| Flag | |
|---|---|
| `-t, --transcript PATH` | **required.** The recording's transcript, as `suno` wrote it |
| `-o, --out PATH` | **required.** The bleeped copy. Same container as the input, so the same suffix |
| `--overwrite` | replace `--out` and the two files beside it if they exist; refused otherwise, exit 1 |

The shipped word lists cover English, Urdu, Hindi and Punjabi, in Roman and in their own
scripts, and every word is looked up in every list, so a sentence that mixes languages
is covered. Add a word by adding its spellings to the user's own list, the file
`$DSJ_WORDS` names, else `words.toml` in dsj's data folder
(`~/Library/Application Support/dsj/` on a Mac). Matching is exact after folding case
and punctuation, so list every spelling you want caught. A spelling may be a phrase of
up to three words (`"bhen chod"`), which matches that many words in a row inside one
sentence, never across a sentence's end, and mutes them together with the pauses
between them; written run together (`bhenchod`) it matches too:

```toml
[[entry]]
name = "yaar"
roman = ["yaar", "yar"]
script = ["یار"]
```

Each muted word is silenced from 0.1 s before its start to 0.1 s after its end, for at
most 1.4 s and never past the start of the next word, since whisper can run a word's end
on through the pause after it; stderr says when it cut one, and the log lists each. The
picture is copied untouched, the sound re-encoded in its own codec (Vorbis as Opus: ffmpeg
has no usable Vorbis encoder). Beside `--out` goes
`<stem>.bleeps.json`, listing every muted word with its `start`, `end` and the list
`entry` that matched it, and the merged `spans` that were silenced. Read it to check
the result, and listen at those times. Beside it too goes `<stem>.source.txt`, the content
id of the recording the copy came from (its size, a dash, and a SHA-256 of its first and
last MiB), and the copy carries the same id as the file tag `com.jaano.source`
(`xattr -p com.jaano.source clean.mov`), except in a cloud-synced folder, where the
sidecar alone holds it and stderr says so.

Two things it says on stderr every run, and both matter:

- `recall:` a recogniser can leave a swear word out of the transcript altogether, and a
  word that was never written down cannot be muted. How often each engine does this is
  not measured yet, and the line says so.
- When nothing matched, `warning: nothing to mute`, naming the transcript and the lists
  searched. **Nothing is written and the exit code is 3**, so a run that muted nothing
  can never pass for a cleaned file.

A transcript without word end times (`e`), written before v0.2.0 or imported by
`parho`, is refused with exit 1 rather than guessed at: transcribe the recording again.
A plain `kill` stops a render and leaves no output behind, exit 143.

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

Speakers come back from VTT voice tags, and from SRT only as `SPEAKER_01: ` (the form
`likho` writes) or `Speaker 2: ` ahead of the words. Any other capitals and a colon
(`NOTE: `, `OK: `) stay in the text as words. A file with no labels imports with no `speakers` and
no `diarization`, exactly like a transcript that was never labelled.

### ui

Open the app in a browser. It is for a person reading transcripts, not for an agent:
everything it shows comes from the files the other verbs write, so query those instead.

```bash
dsj ui
dsj ui --print-url
dsj ui --tailnet --print-url
```

| Flag | |
|---|---|
| `--print-url` | print the URL and serve, without opening a browser |
| `--tailnet` | also serve it to the owner's own Tailscale devices, and print the phone URL |

It listens on `127.0.0.1` only, on a port the kernel picks, and prints the URL, alone,
on stdout: `http://127.0.0.1:<port>/#t=<token>`. Every `/api` and `/media` request needs
that token as `Authorization: Bearer <token>`, and a request whose `Host` is not that
loopback address is refused with 403, token or not. The page itself needs no token.

It serves until Ctrl-C or `kill`, or until no page is open: the page sends
`POST /api/heartbeat` every 15 s (about once a minute while its tab is hidden), and
`POST /api/bye` as it goes away; the server stops 10 s after the last open page's
goodbye unless a page beats, or after three minutes with no request at all, so a server
nobody opens stops on its own. A transcription started from the page holds it up.
Start it with `&` if you need the shell back. A second `dsj ui` while one is running
prints the running one's URL and exits 0 without binding a port; the running one's
details are in `ui.lock` beside the library (`$DSJ_LIBRARY`'s folder when that is set).
The page lists the library, which holds every finished `dsj suno` run and every job
started from the page (`GET /api/recordings`: every recording, newest first, each
with its transcripts' `finished_at`, `engine`, `model`, `diarized`, `speaker_count`,
`mark_count`, `language`) and serves one transcript's JSON unchanged at
`GET /api/transcripts/<id>`. For an agent the JSON files are still the thing to read.

A review made in the app leaves two files beside the transcript JSON:
`<name>.reference.json` (`format: "dsj-reference"`, `version: 1`, the transcript's file
name, `engine`, `model`, `complete`, and `segments`, each with `start`, `end`,
`speaker`, `text`, `flags` and `checked`) and `<name>.reference.txt`, one
`[m:ss] Speaker: words (flags)` line a sentence. They are a person's checked reading of
the recording: prefer them to the transcript where they exist, and read `complete`
first, since a key saved part way through marks its unchecked sentences
`checked: false`. `flags` holds `unclear`, `not_speech`, `overlap` and `cut_off`. The
review itself, and each transcript's edit list (`dsj hatao`'s file, with an optional
`names` map from speaker label to the name a person gave it), live beside the library in
`reviews/` and `edits/`.

Review is the owner's, by hand: sentence by sentence against the audio, in one of two
passes, every sentence in order (for an answer key) or only the likely errors
(unsure words, flags, or where another transcript of the same recording, shown as a
second opinion, reads the span differently). On the Mac it is keyboard-first; on a
phone or tablet each sentence is a card, swiped left for checked and right for back.
The keys, for answering the owner's questions about them:

| Key | Does |
|---|---|
| Enter / Shift+Enter | checked and next / previous |
| Tab / Shift+Tab | play or pause / replay the sentence |
| Ctrl+, / Ctrl+. | slower / faster (0.75x to 1.5x) |
| Ctrl+1 to Ctrl+9 | said by speaker n |
| Ctrl+G | take the second opinion's reading |
| Ctrl+U / Ctrl+F | flag can't make it out / flag menu |
| Ctrl+S / Ctrl+M | split at the cursor / merge with the previous |
| Ctrl+J / Ctrl+Shift+J | next / previous likely error |
| Ctrl+/ / Esc | key sheet / leave (progress is saved) |

With `--tailnet` (for a phone or tablet, #250) it still listens on `127.0.0.1`, and
runs `tailscale serve --bg --https=<https> http://127.0.0.1:<port>` in front of it, so
only devices on the owner's tailnet reach it. `<https>` is the first of 8443, 8444, 8445
and 10000 that serves nothing yet; a port already serving something is skipped, never
replaced, and 443 is never used. It prints `https://<mac>.<tailnet>.ts.net:<https>/#t=<token>`
on stdout instead, and a QR code of it on stderr; the token is still required, and
`<mac>.<tailnet>.ts.net:<https>` is the one extra `Host` let in. The lock file records
which port the run took, and only that entry is removed when it stops: on Ctrl-C,
`kill`, a closed Terminal window (SIGHUP), the idle stop or an error. `kill -9` and a
power cut cannot clean up; the lock file keeps the record, and the next `dsj ui`, with
or without `--tailnet`, removes the entry first, only if it still points at that dead
run's port. A record stays until its entry is confirmed gone.
It waits 30 minutes for a page instead of three, and a page's goodbye does not stop it,
because a phone sends one on every app switch or screen lock. It exits 1 with one line,
changing nothing, when `tailscale` is not on PATH, when Tailscale is not running (it
never starts it), when MagicDNS is off (the Mac has no tailnet name), when all four ports
already serve something (it names each), or when a `dsj ui` without `--tailnet` is
already running. A `tailscale` command that hangs is given up after 30 s, with what it
printed: with HTTPS certificates off for the tailnet, `serve --bg` prints the URL that
turns them on, and that line carries it. A start that finds a recorded entry says so on
stderr before it asks tailscale. It never runs `tailscale funnel`, so
nothing is on the public internet. An agent should not run it: the phone check belongs
to the owner, and has not been observed yet (Tailscale was stopped while #250 was built;
the tests drive a stand-in `tailscale`).

It needs the `ui` extra, which the `mac` bundle carries. Without it the command fails
in a second with `UIUnavailable`, whose message is the line that installs it.

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
pieces, and a word at a seam can be mistimed by a few seconds, measured worst case
5.72 s, and is written where its time puts it. No two sentences overlap, under every
engine: whisper merges two that would (#190), parakeet and sherpa re-cut them so the
fewest tokens change sentence, never merging two speakers into one (#192).

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
jq -r 'if .state == "failed" then "failed (pid \(.pid // "?")): \(.error)"
  elif .state == "interrupted" then "interrupted by \(.signal) (pid \(.pid))"
    + if .during then " during \(.during) at \(.audio_done_s | floor)s of \(.audio_total_s | floor)s" else " before its first frame" end
  else "\(.state) \((.fraction // 0) * 100 | floor)% eta \(.eta_s // "?")s (pid \(.pid // "?"))"
    + if .stalled_s then ", stalled for \(.stalled_s | floor)s" else "" end
  end' run.json
```

It names the writer's `pid` on every line, says which signal stopped an `interrupted`
run and how far it had got (never a made-up `0%`: that document has no `fraction`), and
adds `stalled for Ns` while extraction stands still. Example lines:
`running 42% eta 122.9s (pid 48213)`,
`interrupted by SIGTERM (pid 48213) during running at 105s of 300s`,
`failed (pid 48213): FileNotFoundError: /nope.mov`.

`state` moves `extracting` to `running` to `diarizing` to `done`, or becomes `failed`, or
`interrupted` when Ctrl-C or `kill` stopped it.
A whisper run that wrote a repetition loop passes through `retrying` after `running`,
while each loop span is decoded again.
The file is one JSON object rewritten in full and replaced atomically, so a reader never
sees half of one.

Two things will break a poller that assumes otherwise:

- **Branch on `state`, never on `fraction`.** `fraction` is not monotonic. It reaches
  1.0 when the audio is decoded, drops back to 0.0 for the `diarizing` frames, and is 1.0
  again on the final frame, whose totals are the length of the audio. Observed across
  three separate runs: a poller that stops at `fraction == 1` calls it done before the
  speaker labels exist.
- **The failure document is a different shape**, three keys and no progress fields:
  `{"state": "failed", "pid": 48213, "error": "FileNotFoundError: /nope.mov"}`. Read
  `state` first.

**A `running` frame is not proof of a running job.** A run killed with `kill -9`, or by
the system under memory pressure, cannot write anything, so its file says `running`
forever. Every frame carries the writer's `pid`: `kill -0 "$(jq -r .pid run.json)"`
failing means the run is dead, not slow. To stop a run, `kill` that pid, never
`pkill -f 'dsj suno'`, which stops every run on the machine. An `extracting` frame that
carries `stalled_s` is alive but has not moved for that many seconds: report it, do not
kill it. Details in [references/payload.md](references/payload.md).

`eta_s` is `null` whenever speed is 0, which includes the first frame of every run.

**One `dsj suno` at a time, per machine.** A second one started while another runs exits
75 at once, before it loads a model and without touching its own `--status` file, and
names the running job's pid and `--out` on stderr. Two at once froze the owner's Mac on
2026-09-19, which is why it refuses rather than queues. Wait until `kill -0 <pid>` fails,
or stop that job with `kill <pid>`, then run the command again. A run that died, even by
`kill -9`, frees the lock as it dies. The lock is `~/.cache/dsj/suno.lock`; deleting it
frees nothing and lets a second run start beside the first.

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

`--no-resume` deletes the checkpoint rather than ignoring it.

**What survives an interrupt depends on the engine and the state it stopped in.** whisper
has no chunk loop of dsj's to bank from, so it banks its whole result once, at the same
path, the moment its decode ends, and keeps it until labelling is over. A different
`--model`, `--prompt`, `--language` or `--roman-urdu` on the rerun invalidates it, and
stderr says which.

| Stopped in | parakeet, sherpa: the rerun | whisper: the rerun |
|---|---|---|
| `extracting`, or before the first frame | has nothing new banked | has nothing new banked |
| `running` | resumes from the last chunk banked, at most 105 s back | starts over: the decode is lost |
| `retrying` | (never retries) | decodes nothing; retries its loops again |
| `diarizing` | decodes nothing; labels again | decodes nothing; retries its loops and labels again |

**Never delete a transcript to force a re-run.** dsj replaces `--out` atomically and
only once transcription has finished, so a run that stops earlier leaves the old file
exactly as it was. The only way to lose it is to delete it first: on 2026-09-22 a
script removed a finished transcript, started a whisper re-run, and the run was stopped
14 minutes in, leaving neither. Write the retry to a new path, and replace the old file
yourself once the new one exists:

```bash
dsj suno rec.m4a -o rec.retry.json --status rec.retry.status.json --roman-urdu
# only after rec.retry.json exists and looks right:
mv rec.retry.json rec.json
```

This matters most under whisper, which `--roman-urdu` uses: a retry stopped before its
decode ends leaves nothing behind.

## When something fails

| Exit | Meaning |
|---|---|
| 0 | Success |
| 1 | `suno` and `hatao`: a mistake you can put right (a missing input or output directory, a bad `--engine`, an engine not installed, a transcript with no word ends, an output that exists), printed as one line, `dsj: <message>`. Anything else: an uncaught exception, printed as a traceback on stderr |
| 2 | A usage error, including a `likho` format it cannot name or a `hatao` output in another container. Run `dsj <verb> --help` |
| 3 | `hatao` only: no word matched a word list, so nothing was muted and nothing written |
| 130 | Interrupted by Ctrl-C. For `suno`, re-run to resume; under whisper only a run stopped after its decode resumes |
| 143 | Stopped by `kill`. The same as 130 otherwise; a `hatao` render leaves no file |
| 75 | `suno` only: another `suno` is already running on this machine. Nothing was started; stderr names its pid |

**Read the last line of stderr, not the first.** A failure you caused is that one
line; any other failure is a traceback, and when
ffmpeg is involved its own log prints above the exception, so the useful sentence can be
twenty lines down:

```
[out#0/image2 @ 0x...] Nothing was written into output file ...
99999.0s is past the end of this 230.7s recording.
```

Diarization is the one pass that fails soft: if it cannot run or crashes, the transcript
is still written and still correct, a `diarization skipped:` or `speaker labelling
failed` warning goes to stderr, and the exit code is 0. Detect it in the payload rather than the log, because `speakers` and
`diarization` are absent when the pass did not run. `--require-diarize` turns that into
a failure instead.

Every error class, its message, and its remedy are in
[references/failures.md](references/failures.md).

## Changing dsj itself

From a clone, the check that a change works is `uv run just check`, never `uv run
pytest` alone. `just check` runs the type checker, ruff and the fast tests; pytest skips
the type checker, so a green pytest is no evidence. Paste the line `just check` ends
with before calling the change done.

**Working on the UI** (`ui/` and `dsj/ui/`, the code behind `dsj ui`). The same five rules
as the repo's `AGENTS.md`:

1. Commands: `just ui-dev` to develop; `just ui-build` before any commit that touches
   `ui/`, committing what it writes to `dsj/ui/static/`; `just api` after changing
   `dsj/ui/schemas.py` or a route; `just check` before calling anything done. A fresh
   clone needs `(cd ui && npm ci)` first, because `just check` fails rather than skips
   without `ui/node_modules`.
2. Where files go: frontend source in `ui/src/`, its tests in `ui/tests/`, the server in
   `dsj/ui/`. The built page `dsj/ui/static/` and the generated types
   `ui/src/api/schema.d.ts` are never hand-edited.
3. TypeScript is pinned to 6.0.3; do not install 7.x. `typescript-eslint@8.70.1` declares
   `"typescript": ">=4.8.4 <6.1.0"`, and 6.0.3 is the newest version inside it.
4. The package is `@base-ui/react`, not `@base-ui-components/react`. It was renamed; the
   old name is frozen at `1.0.0-rc.0` and its import resolves to nothing.
5. Never hand-write a UI primitive or type a `@base-ui/react/*` import from memory. Run
   `npx shadcn@4.21.0 add <name>` from `ui/` and let it write the import.

## References

- [references/payload.md](references/payload.md): the transcript, marks, heartbeat and
  checkpoint documents, field by field, and how to query them.
- [references/engines.md](references/engines.md): install bundles, choosing between
  parakeet, whisper and sherpa, Urdu, and the Android and proot constraints.
- [references/failures.md](references/failures.md): exit codes, every error class, and
  what each one wants you to do.
