<p align="center">
  <img src="assets/banner.png" alt="Dekho Suno Jaano" width="800">
</p>

<p align="center">
<a href="https://github.com/m2moiz/dekho-suno-jaano/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/m2moiz/dekho-suno-jaano/actions/workflows/ci.yml/badge.svg"></a>
<a href="pyproject.toml"><img alt="python" src="https://img.shields.io/badge/python-3.12+-blue"></a>
<a href="#requirements"><img alt="platform" src="https://img.shields.io/badge/platform-Apple%20Silicon-lightgrey"></a>
<a href="docs/generalisation.md"><img alt="validated" src="https://img.shields.io/badge/validated-834%20recordings%20%C2%B7%20p%3D3.5e--94-brightgreen"></a>
<a href="docs/do-marks-help.md"><img alt="blind graded" src="https://img.shields.io/badge/blind%20graded-16%2F16-brightgreen"></a>
</p>

---

> **Driving dsj from an agent?** Read [.agents/skills/dsj/SKILL.md](.agents/skills/dsj/SKILL.md)
> first. The transcript format is in [.agents/skills/dsj/references/payload.md](.agents/skills/dsj/references/payload.md).

**An hour of screen recording, made answerable.** `dsj` turns a recording into
a timestamped transcript that acts as an *index into the video* — so an agent
reads cheap text, notices a moment that only makes sense visually, and pulls
that exact frame.

```bash
dsj suno   meeting.mov -o transcript.json        # suno   -- listen
dsj dekho  meeting.mov -t transcript.json        # dekho  -- look
dsj dikhao meeting.mov 431.5 -o frame.jpg        # dikhao -- show me
```

Three Urdu imperatives, in the order the tool works:

| | | |
|---|---|---|
| <div dir="rtl">سنو</div> | `suno` | *listen* — what was said, and when |
| <div dir="rtl">دیکھو</div> | `dekho` | *look* — when the picture changed |
| <div dir="rtl">دکھاؤ</div> | `dikhao` | *show me* — the picture itself |
| <div dir="rtl">ہٹاؤ</div> | `hatao` | *remove it*: a copy with the swear words bleeped |
| <div dir="rtl">جانو</div> | `dsj` | *know* — what you get from all three, and so the command |

<p align="center">
  <img src="assets/pipeline.svg" alt="A recording becomes a transcript and a list of marks; frames are seeked out of the original on demand" width="900">
</p>

## The problem

> *"See **this** column **here**?"*

That is the most information-dense sentence in the meeting, and as text it is
worthless. The referent was on screen and the transcript threw it away. Words
that only mean something in context are the exact failure mode of an audio-only
transcript of a screen-share.

Feeding the whole video to a vision model is the other extreme: a 74-minute
recording is **444,000 tokens** on a native-video model against **10,000** for
its transcript — 44× the cost to answer a question that is usually about one
second of it.

`dsj` keeps the video on disk as a random-access resource and spends tokens
only where the transcript says something visual happened.

## Does it work? Measured, not asserted

| Question | Answer | Evidence |
|---|---|---|
| Does frame retrieval help an agent? | **5/16 → 16/16** on blind-graded questions | [do-marks-help.md](docs/do-marks-help.md) |
| Do the change marks beat chance? | **701/834** third-party recordings, p = 3.5e-94 | [generalisation.md](docs/generalisation.md) |
| On hour-long recordings? | **81%** of slide changes caught within 2s, vs 42% random | [generalisation.md](docs/generalisation.md) |
| Can a small local VLM read a screen? | **86%** recall on the second model tried, at 156 s/frame | [vlm-legibility.md](docs/vlm-legibility.md) |
| Where does it fail? | A camera pointed at a screen. Documented, not hidden | [generalisation.md](docs/generalisation.md) |

Every number came from a command. Three change detectors were built, measured
and thrown away before the one that shipped — [that history is written
down](docs/visual-marks.md), because the ones that looked like they worked are
the interesting part.

---

## Status

| | |
|---|---|
| **Suno — transcript** | working. Chunked ASR, resume, optional speaker labels, ~13× realtime |
| **Dekho — change marks** | working. [Validated on 834 recordings and five hour-long lectures](docs/generalisation.md) — though [worth little on their own](docs/do-marks-help.md) for answering questions |
| **Dikhao — frame retrieval** | working. The step that actually makes a recording answerable |
| **Likho: export** | working. SRT, WebVTT and plain text from a finished transcript |
| **Parho: import** | working. An SRT, WebVTT or dsj JSON transcript in place of ASR |
| **Hatao: bleep** | working from the terminal. Word lists for English, Urdu, Hindi and Punjabi; how often each engine leaves a swear word out of its transcript is not yet measured (#152) |
| **Frame description** | **not built**, blocked on a *measured* finding rather than a guess. See [Roadmap](#roadmap) |

---

## Requirements

- **A platform with an engine bundle.** The core is portable Python, but the
  speech engines are not. Of the three, the two Mac engines run through Metal
  ([`parakeet-mlx`][pmlx] and `mlx-whisper`), which is Apple Silicon only. The
  third, `sherpa`, runs the same parakeet weights through ONNX wherever
  sherpa-onnx publishes wheels, which is what lets dsj run on a phone.
  Installing dsj means choosing a bundle -- there is deliberately no default,
  because a dsj with no engine transcribes nothing.
- **Python 3.12 or 3.13.** Capped deliberately. The diarize extra reaches
  coremltools, which publishes no wheel above 3.13 and no `requires-python` of
  its own; on 3.14 it builds from source into a pure-Python wheel with the
  CoreML extensions missing. That imports cleanly and then cannot diarize, so
  the failure arrives as a transcript with no speaker labels rather than as an
  error. `tests/test_install_gate.py` runs the install below and checks it.
- **ffmpeg** on `PATH`, for anything that is not already a 16 kHz mono WAV.
- [`uv`][uv] for dependency management.
- **For `dsj ui` only: Safari 17.2, Chrome 105 or Firefox 140**, or newer. The
  reader paints the word being spoken with the CSS Custom Highlight API, which
  older browsers lack without any error; the app checks for it before it shows
  anything and names what is missing instead of loading a page that quietly
  does nothing. Floors from `@mdn/browser-compat-data` 8.1.2.

[pmlx]: https://github.com/senstella/parakeet-mlx
[uv]: https://docs.astral.sh/uv/

## Install

Pick the bundle for your machine. On a Mac:

```bash
uv tool install "dsj[mac] @ git+https://github.com/m2moiz/dekho-suno-jaano"
```

That puts `dsj` on your `PATH` with both Mac engines and the diarizer. There is no
bare install line on purpose: `uv tool install dsj` succeeds but carries no
engine, and the first `dsj suno` tells you which extra to add.

Model weights (~2.4 GB) download on first run and are cached by
`huggingface_hub`.

Off the Mac, the `android` bundle carries the third engine, `sherpa`, and nothing
else. It has no speaker labelling, because the diarizer is CoreML and has no
Android path:

```bash
uv tool install "dsj[android] @ git+https://github.com/m2moiz/dekho-suno-jaano"
```

Each bundle is a set of extras, and each extra installs alone when a bundle
carries more than you want:

| Extra | Pulls in | For |
|---|---|---|
| `dsj[mac]` | `parakeet`, `whisper`, `diarize`, `ui` | The working Mac setup |
| `dsj[android]` | `sherpa` | The phone |
| `dsj[parakeet]` | `parakeet-mlx` | The default engine. Apple Silicon and Metal only |
| `dsj[whisper]` | `mlx-whisper` | Urdu, and anything else parakeet cannot read. About 250 MB, because it pulls torch |
| `dsj[sherpa]` | `sherpa-onnx`, `sherpa-onnx-core` | The portable ONNX engine |
| `dsj[diarize]` | `senko` | Speaker labels. CoreML, so macOS only |
| `dsj[ui]` | `fastapi`, `uvicorn` | `dsj ui`, the app in a browser |

**To work on it instead**, clone and sync — but note that `uv sync` installs the
command at `.venv/bin/dsj` and links it nowhere, so from a clone every
invocation is prefixed with `uv run`:

```bash
git clone https://github.com/m2moiz/dekho-suno-jaano
cd dekho-suno-jaano
uv sync --dev --extra parakeet --extra diarize --extra whisper --extra sherpa --extra ui
uv run dsj suno recording.mov -o transcript.json
```

That sync line is the one CI runs. `uv sync` installs exactly the extras on its
line and **uninstalls every other one**, so keep one line and add to it: a bare
`uv sync`, or `uv sync --extra <one>`, takes away the engines you already had.

Every command below is written bare (`dsj ...`), which is what an installed
copy gives you. From a clone, prefix each one with `uv run`.

### On a phone: Termux and proot

sherpa-onnx ships manylinux wheels, which need glibc, and Termux is built on
Android's own C library, bionic. So the install does not go in Termux itself: it
goes inside a proot container running a glibc Linux on the phone, and the
`dsj[android]` line above runs there.

`--engine sherpa` then needs an explicit `--model <directory>`, because the
default it is handed is parakeet's Hugging Face id, not a directory ([#46](https://github.com/m2moiz/dekho-suno-jaano/issues/46)), and
nothing in this repo yet says where to download that directory ([#47](https://github.com/m2moiz/dekho-suno-jaano/issues/47)).

What has run on a phone, as of this writing: on 2026-08-26, at commit `eb6e06f`,
`dsj suno --engine sherpa` transcribed a five-minute recording on a OnePlus 15
inside proot-distro Ubuntu, and an interrupted run resumed from its checkpoint.
The `dsj[android]` install line as it stands now has not been run on a phone and
recorded, and neither has an hour-long recording ([#32](https://github.com/m2moiz/dekho-suno-jaano/issues/32)). CI cannot run Termux, so
this record is kept by hand.

## Usage

`dsj dikhao` prints the path it wrote and nothing else, so it composes:

```bash
open "$(dsj dikhao recording.mov 431.5 -o /tmp/f.jpg)"
```

**If you point an agent at a recording, tell it about `dsj dikhao`.** That one
verb is the difference between an agent reconstructing the screen from what was
said about it and an agent *looking*: measured 5/16 against 16/16 on a
blind-graded question set ([docs/do-marks-help.md](docs/do-marks-help.md)).

`python -m dsj.suno` and `python -m dsj.dekho` still work and are the same
code.

### Suno — transcription

```bash
dsj suno recording.mov -o transcript.json
```

Progress renders live on stderr:

```
    running [##########--------------] 42%  31:12/74:07 audio  elapsed 1:29  eta 2:01  35.4x
```

| Flag | |
|---|---|
| `-o, --out PATH` | where the transcript JSON goes (required) |
| `--status PATH` | write a JSON heartbeat, for runs you detach from |
| `--no-resume` | ignore any checkpoint and start over |
| `--no-diarize` | skip speaker labelling |
| `--require-diarize` | fail rather than degrade if labelling cannot run |
| `--model ID` | override the ASR model; the default follows `--engine` |
| `--engine parakeet\|whisper\|sherpa` | which ASR backend (default `parakeet`) |
| `--language CODE` | whisper only: ISO code, e.g. `ur`. Detected if omitted |
| `--prompt TEXT` | whisper only: seeds the decoder; biases spelling and script |
| `--roman-urdu` | whisper, Urdu, written in Latin. Sets the two flags above |

**Urdu, and anything else parakeet cannot read.** `parakeet-tdt-0.6b-v3` covers
25 languages and they are all European — `ur` is not among them, so an Urdu
voice note comes back as nothing usable. `--engine whisper` swaps in
`whisper-large-v3-turbo`, which reads it:

```bash
dsj suno voice-note.m4a -o transcript.json --roman-urdu
```

Roman Urdu is a **prompt**, not a setting. whisper writes Urdu in Urdu script by
default; seeding the decoder with a Roman Urdu example makes it emit Latin, and
whisper's own condition-on-previous-text carries that across windows, for as
long as the prompt survives. On the public fixture below, 3% of the text comes
back in Urdu script, with English words left in English where they were spoken
in English, which is the point, for speech that switches mid-sentence.
`--roman-urdu` is that prompt plus `--language ur`; `--prompt` takes your own.

On long recordings the prompt is pushed out of whisper's context after 22 to
105 seconds, so `--roman-urdu` re-seeds it every 120 seconds. Measured on the
owner's two recordings where it drifts most, whisper-large-v3-turbo
(m2moiz/dekho-suno-jaano#100):

| recording | window | runs | words | Urdu script | loop seconds |
|---|---|---:|---|---|---|
| 101117, 13.1 min | none (22 Sep) | 1 | 1,181 | 81% | 196 |
| | 120s | 3 | 1,427 · 1,332 · 1,460 | 59 · 47 · 47% | 174 · 166 · 164 |
| | 30s | 2 | 1,141 · 1,061 | 13 · 6% | 487 · 321 |
| 094234, 27.9 min | none (22 Sep) | 1 | 2,786 | 98% | 171 |
| | 120s | 2 | 3,251 · 3,102 | 39 · 44% | 86 · 343 |
| | 30s | 2 | 3,095 · 2,632 | 10 · 7% | 291 · 562 |

Each run is `dsj suno <file> --roman-urdu`, the 30s rows with `ANCHOR_CHUNK_S`
set to 30 by `scratch/whisper_sweep.py`. A shorter window keeps more of the text
in Latin and loses words, so the window stays at 120s: the goal is complete
text, and Urdu script in the output is accepted.

The model matters more than it looks. On the public Urdu-English fixture
(`just urdu-fixture`, 854s), one run each with `--roman-urdu`
(m2moiz/dekho-suno-jaano#33):

| model | English words recovered | Urdu script | speed |
|---|---:|---:|---:|
| `whisper-large-v3-turbo` | 89.6% | 3% | 3.41x realtime |
| `whisper-large-v3-mlx` (full) | 59.4% | 63% | 0.50x, with 23% of memory free |

```bash
dsj suno scratch/urdu_cs/podcast.wav --roman-urdu --no-diarize --model <id>
```

The full model writes most of its text in Urdu script whatever the prompt says.
Turbo is the default here for that reason, and changing it means re-measuring.

The whisper engine banks **nothing while it decodes**, so a run interrupted in
the `running` state starts over: it owns its own window loop and exposes no hook
to bank from. Its finished result is banked beside `-o` the moment the decode
ends and kept until speaker labelling is over, so a run stopped after that
decodes nothing on the rerun (#171). How much
progress it reports depends on the run. `--roman-urdu` cuts the audio into
two-minute windows itself and reports after each one. Any other whisper run,
`--prompt` and `--language` included, reports 0% and then **nothing until
transcription ends**, because mlx-whisper takes no progress callback. It runs
at about 1.7 to 3x realtime on Urdu with `--roman-urdu` and about 5 to 6x on
English, against parakeet's ~13x, on a 16 GB M2 running one whisper at a time.
The per-file numbers, with the command, commit and memory state of each, are in
[engines.md](.agents/skills/dsj/references/engines.md#whisper-speed). All
three cost more the longer the recording, which is why parakeet stays the
default.

**Never delete a transcript to force a re-run.** dsj replaces `-o` atomically
and only once transcription has finished, so a run that stops earlier leaves
the old file as it was. A whisper retry stopped before its decode ends leaves
nothing behind, so if the old file was deleted first, both are gone: that is how
a finished transcript was lost on 2026-09-22. Write the retry to a new path and
replace the old file yourself once the new one exists:

```bash
dsj suno rec.m4a -o rec.retry.json --status rec.retry.status.json --roman-urdu
# only after rec.retry.json exists and looks right:
mv rec.retry.json rec.json
```

It is part of the `mac` bundle; standalone installs can pick it alone
(mlx-whisper pulls torch, ~250 MB):

```bash
uv tool install "dsj[whisper] @ git+https://github.com/m2moiz/dekho-suno-jaano"
```

**sherpa, where MLX does not run.** `--engine sherpa` runs the same parakeet
weights through their ONNX export instead of MLX, so it works wherever
sherpa-onnx has wheels, which is how dsj transcribes on a phone (see
[On a phone](#on-a-phone-termux-and-proot)). Like parakeet it transcribes in
chunks and checkpoints each one, so an interrupted run resumes. It needs an
explicit `--model <directory>` ([#46](https://github.com/m2moiz/dekho-suno-jaano/issues/46), [#47](https://github.com/m2moiz/dekho-suno-jaano/issues/47)):

```bash
dsj suno recording.m4a -o transcript.json --engine sherpa --model /path/to/model-dir
```

No phone speed is published here yet; [#32](https://github.com/m2moiz/dekho-suno-jaano/issues/32) measures one properly, on an
hour-long recording.

**Long runs.** An hour of audio is not something you sit and watch, so detach it
and poll the heartbeat:

```bash
dsj suno meeting.mov -o out.json --status run.json &
jq -r 'if .state == "failed" then "failed (pid \(.pid // "?")): \(.error)"
  elif .state == "interrupted" then "interrupted by \(.signal) (pid \(.pid))"
    + if .during then " during \(.during) at \(.audio_done_s | floor)s of \(.audio_total_s | floor)s" else " before its first frame" end
  else "\(.state) \((.fraction // 0) * 100 | floor)% eta \(.eta_s // "?")s (pid \(.pid // "?"))"
    + if .stalled_s then ", stalled for \(.stalled_s | floor)s" else "" end
  end' run.json
```

`state` moves `extracting → running → diarizing → done`, or `failed` with an
`error`. A whisper run that wrote a repetition loop passes through `retrying`
while it decodes each loop span again. The file is written atomically, so a reader never sees half of one.

**Interruptions are cheap.** A checkpoint is written beside the output every
chunk. Re-running the same command resumes from it, even if the recording was
renamed, moved or copied in between: the checkpoint knows it by its contents,
not its path. An edited recording, a changed model, or a different chunk
geometry invalidates it, and the run starts over rather than reusing tokens
that describe something else, saying on stderr which of those it was.

**One `dsj suno` at a time, per machine.** A second one started while another
runs exits **75** at once, before it loads a model and without touching its own
`--status` file, and names the job it is waiting on:

```
another dsj suno is already running on this machine: pid 48213, writing /recordings/out.json.
```

Two at once froze the owner's Mac on 2026-09-19: one run is already sized
against the machine's memory, two are not. That is why the second refuses
rather than queues, and why the lock is one file for the whole machine rather
than one per output: the two runs that froze it wrote to different files. Wait
until `kill -0 <pid>` fails, or stop that job with `kill <pid>`, then run the
command again. A run that dies, even by `kill -9`, frees the lock as it dies.
The lock is `~/.cache/dsj/suno.lock`; deleting it frees nothing and lets a
second run start beside the first. `DSJ_SUNO_LOCK=<path>` moves it, which is
how the test suite keeps out of a real run's way; two runs under different
lock paths do not see each other.

**A copy of the transcript rides on the recording.** On a Mac, once the
transcript is written, the same bytes go into a hidden file tag on the
recording, `com.jaano.transcript`. The recording's contents, size and
modified time stay exactly as they were, so a checkpoint for it stays good.
`xattr -p com.jaano.transcript recording.mov` prints it. If the tag cannot be
written (a read-only recording, say), the run says so on stderr and finishes
anyway.

A recording in a cloud-synced folder is never tagged, and the run says so in
one line on stderr; the transcript JSON is its only copy (#202). What a sync
client does when a file it syncs gains a tag of several MB is not measured, and
it may upload the whole recording again. dsj counts a folder as synced when it
is under `~/Library/CloudStorage` (Google Drive, Dropbox, OneDrive) or
`~/Library/Mobile Documents` (iCloud Drive), or when a folder above the
recording carries macOS's `com.apple.file-provider-domain-id` tag, which is how
iCloud's Desktop & Documents sync would show itself in the ordinary `~/Desktop`
and `~/Documents` (that last signal is not yet seen on a real iCloud folder).
The app transcribes such files too, the same way.

From Python, `dsj.filetag.read_transcript(recording)` returns the transcript
from `<stem>.dsj.json` beside the recording, and from the tag only when that
file is missing. The JSON file is the real copy; the tag is a local safety net.
Three ordinary things drop the tag without a word, measured in #117: remuxing
with `ffmpeg -c copy`, saving through `avconvert` with `PresetPassthrough` (what
QuickTime Player uses), and a trip through Google Drive's servers. A `cp` or
`mv` on the Mac keeps it. Off a Mac nothing is tagged, and the JSON file is the
only copy.

### Dekho — change marks

A second pass adds the timestamps where the picture changed most. It is
separate because the transcript arrives at ~13x realtime and this decodes every
sampled frame at ~10x, so coupling them would make the fast half wait:

```bash
dsj dekho recording.mov -t transcript.json
```

| Flag | |
|---|---|
| `-t, --transcript PATH` | the transcript to add marks to (required) |
| `-o, --out PATH` | write elsewhere instead of overwriting `--transcript` |
| `--budget N` | how many marks to keep (default 150) |
| `--min-gap SECONDS` | how far apart they must be (default 5) |
| `--fps N` | frames sampled per second of video (default 1) |
| `--delta N` | grey levels a tile must move to count (default 8) |

`--budget` rather than a sensitivity threshold is the one design decision worth
knowing about, and it is not a preference — three threshold-based detectors were
built and measured against a real recording before this one, and all three
failed. [docs/visual-marks.md](docs/visual-marks.md) has the numbers.

### Dikhao — retrieving a frame

```bash
dsj dikhao recording.mov 431.5 -o frame.jpg [--width 1500]
```

| Flag | |
|---|---|
| `-o, --out PATH` | where the image goes; `.jpg` is what a vision model wants |
| `--width N` | scale to N pixels wide, aspect preserved (default 1500; `0` keeps source) |

Nothing is precomputed and nothing is cached — the video is already on disk, and
seeking into it is cheap. The 1500px default is a measured ceiling rather than a
taste: a full 2940px frame is ~776 KB as a JPEG, more than most vision APIs
want, and legibility stopped improving well below that — 700px to 1600px moved
recall by one string in fifteen ([docs/vlm-legibility.md](docs/vlm-legibility.md)).

Also available as `dsj.media.extract_frame(video, t, dest, width=...)`.

### Hatao: bleeping

`hatao` (remove it) writes a copy of the recording with every word a word list
flags muted, from the transcript `suno` already wrote. No model runs, no app or
server is needed, and the recording itself is never written to:

```bash
dsj hatao recording.mov -t transcript.json -o clean.mov
```

| Flag | |
|---|---|
| `-t, --transcript PATH` | the recording's transcript (required) |
| `-o, --out PATH` | the bleeped copy, in the input's container (required) |
| `--overwrite` | replace `--out` and the two files beside it if they exist |

The shipped lists in `dsj/words/` cover English, Urdu, Hindi and Punjabi, Roman
and own-script spellings, and every word is looked up in every list, so a
sentence that switches language halfway is covered. Matching is exact after
folding case and punctuation; Roman Urdu has no fixed spelling, so an entry
lists each spelling. Your own words go in `words.toml` in dsj's data folder
(`~/Library/Application Support/dsj/` on a Mac, or the file `$DSJ_WORDS`
names), which no update touches:

```toml
[[entry]]
name = "yaar"
roman = ["yaar", "yar"]
script = ["یار"]
```

Each word is muted from 0.1 s before it to 0.1 s after it; the picture is
copied untouched and the sound re-encoded in its own codec. `clean.bleeps.json`
beside the output lists every muted word with its start, end and the entry
that matched it. Listen at those times: whether the cut clicks, or clips the
word next to it, is a judgment for an ear. `clean.source.txt` holds the content
id of the recording it came from, and outside a cloud-synced folder the copy
carries it as the file tag `com.jaano.source` too, so a copy that leaves the
folder can still be matched to its source.

A run that matches nothing writes nothing, says so on stderr and exits 3, so it
cannot pass for a cleaned file. Every run also prints a `recall:` line, because
a recogniser can leave a swear word out of the transcript altogether, and how
often each engine does that is not measured yet (#152). A transcript without
word end times, from before v0.2.0 or from `parho`, is refused rather than
guessed at.

### Likho: exporting a transcript

The transcript is JSON, which nothing but dsj and `jq` reads. `likho` (write)
turns a finished one into SRT, WebVTT or plain text, running no model:

```bash
dsj likho transcript.json -o transcript.srt [--format srt|vtt|txt]
```

| Flag | |
|---|---|
| `-o, --out PATH` | where the file goes; its suffix picks the format |
| `--format FORMAT` | `srt`, `vtt` or `txt`, when the suffix does not say; wins over it |

SRT is one cue per sentence, prefixed `SPEAKER_01: ` when speaker labelling
ran. VTT is the same cues voiced with `<v SPEAKER_01>`, with a timestamp tag
ahead of every word that starts later than the one before it, the only word
timing a subtitle format has room for. TXT is for reading: a block per speaker
turn headed by its start time, or a timestamped line per sentence when there
are no labels.

The cues never overlap. A chunk seam can leave a sentence ending after the next
one starts, and MP4 timed text, like most players, keeps one cue at a time, so
exporting an early transcript and muxing it into its recording moved 22 of 480
cues. Each cue now ends no later than the next begins, and the same transcript
exported by `likho` muxes into the same recording and back with 0 of 480
changed (measured 2026-09-23).

Also available as `dsj.likho.to_srt(payload)`, `to_vtt` and `to_txt`.

### Parho: importing a transcript

When a caption file already exists (a YouTube VTT, a subtitle track, something
`likho` wrote), `parho` (read) makes it a transcript without running ASR, so
`dekho`, `dikhao` and `likho` work on it:

```bash
dsj parho recording.mov captions.vtt -o transcript.json
```

| Flag | |
|---|---|
| `-o, --out PATH` | where the transcript JSON goes (required) |

The format, SRT, WebVTT or a dsj transcript JSON, is read from the content,
not the file name. The recording must exist and is named in `audio`, not
opened. What the file cannot hold is not invented: `model` is `import:srt` or
`import:vtt`, an SRT sentence is one token spanning its cue, a VTT cue with
word timestamp tags becomes word tokens with starts but no ends, and no
imported token has a confidence. Speakers come back from VTT voice tags and,
in SRT, from the `SPEAKER_01: ` prefix `likho` writes or a `Speaker 2: ` one;
any other capitals and a colon (`NOTE: `) stay in the text as words.

### ui: the app

`dsj ui` opens the app in your browser: a page served from this machine, on
`127.0.0.1` and a port the kernel picks. It lists every recording in the
library ([below](#the-library)), newest first, and under each its transcripts:
when each finished, which engine and model made it, its speakers and its marks.
A transcript the library adopted rather than saw being made shows its engine
as "unknown"; one never labelled says "speakers not labelled", which is not
"1 speaker"; a recording whose file has moved stays listed, greyed, at the
path it was last seen. Importing, transcribing and reading arrive with the rest
of v0.3.0 ([#127](https://github.com/m2moiz/dekho-suno-jaano/issues/127)).

```bash
dsj ui                # opens the browser
dsj ui --print-url    # prints the URL and serves, without opening one
```

It needs the `ui` extra, which `dsj[mac]` carries. The page is built ahead of
time and ships inside the package, so an install needs no Node.

Only this Mac's own page can use it. The URL carries a key after `#`, which
the page takes and wipes from the address bar; every request has to bring it
back, and a request that names any host but this machine's is refused. Close
the window and the server stops about ten seconds later: the page says goodbye
as it closes (#206). A page that never gets to say so (a crashed tab) stops it
after three minutes of silence instead. A tab hidden behind another keeps it
running, and a transcription started from the page outlives the window. Run
`dsj ui` again while it is open and you get the running one's address, not a
second copy.

It follows the Mac's light or dark Appearance, live, until you pick Light or
Dark in the corner; the pick is kept in a cookie on `127.0.0.1`, which, unlike
the browser's per-port storage, survives the new port each launch gets.

## Output

```jsonc
{
  "audio": "/path/to/recording.mov",   // the SOURCE, absolute, not a temp wav
  "engine": "parakeet",                // parakeet, whisper or sherpa; absent before #172
  "model": "mlx-community/parakeet-tdt-0.6b-v3",
  "speakers": ["SPEAKER_00", "SPEAKER_01"],   // only when diarization ran
  "diarization": "senko 0.1.0",               // absent if it did not
  "text": "the whole transcript as one string",
  // stretches taken out of `sentences`: whisper looping on one letter or phrase
  // ("repetition loop"), or writing words over silence ("no speech").
  // [] when there were none; absent from transcripts written before it existed
  "unclear": [{"start": 134.1, "end": 161.8, "reason": "repetition loop", "words": 223}],
  "sentences": [
    {
      "start": 12.34,
      "end": 15.02,
      "speaker": 0,                     // index into `speakers`
      "text": " See this column here.",
      // e = token end, c = confidence: each engine's own, see payload.md
      // charOffset = where `w` starts in this sentence's `text`
      "tokens": [{"t": 12.34, "w": " See", "e": 12.43, "c": 0.998, "charOffset": 0},
                 {"t": 12.51, "w": " this", "e": 12.67, "c": 0.941, "charOffset": 4}]
    }
  ],

  // added by `python -m dsj.dekho`; absent until that pass has run
  // t    = when the picture changed (the boundary)
  // look = the frame worth extracting: the middle of the stretch that screen was up
  "marks": [{"t": 417.0, "score": 2841, "look": 431.5}],
  "marks_meta": {"budget": 150, "min_gap_s": 5.0, "fps": 1.0, "delta": 8,
                 "grid": [128, 84], "frames_sampled": 1997, "source": "..."}
}
```

**`sentences` runs earliest to latest, and so do the `tokens` inside each one.**
A reader may walk the list from the top and stop at the first `start` past the
window it cares about. That is a promise about *order*, not about *accuracy*: a
recording longer than 120 s is transcribed in overlapping pieces and stitched,
and the stitch can mistime a word at a seam by a few seconds. That word is
written where its time puts it, in the sentence its time falls inside if there
is one (#192), and otherwise its sentence sorts to where it claims. Measured
on three recordings: 8 sentences of 1038, 3 of 664 and 4 of 480 arrived out of
order before the sort, the worst by 5.72 s. Recordings short enough to need no
stitching were already in order.

**No two sentences overlap**: each ends at or before the next one's `start`,
under every engine. Each of the 6 s two of whisper's two-minute windows share
is written by one of them, its own half by default or all of it by the one that
did not loop there, so the same speech is not written twice at a seam (#190).
Under parakeet and sherpa a word timed seconds early at a chunk seam would
start its sentence inside the one before. The two are split rather than
merged, because one merged sentence would put two speakers under one label
(#192): the fewest tokens that must change sentence do, usually one full stop,
and no time changes.

**A sentence's `text` is its `tokens` joined**: every `w` in that time order,
leading space included, under every engine. The top-level `text` is the
sentences joined. So a word the stitch mistimed reads out of place in the text
too, instead of the text reading one order while a click plays another. On the
same three recordings 32 of 1038, 23 of 664 and 16 of 480 sentences read this
way, all at seams; most move only punctuation, and about 1 in 100 moves a word.

Two things about this shape are deliberate:

- **`speaker` is an integer index, not a name.** It costs 1.7% of file size
  where `"SPEAKER_01"` on every sentence costs 3.3% for no extra information —
  and an integer *looks* like the arbitrary cluster id it is, where a name
  invites you to treat it as an identity.
- **`diarization` is absent when the pass did not run.** Without that, "no
  diarization" and "diarization found one speaker" are the same document.
- **`marks` sits beside `sentences`, not inside them.** A mark is a fact about
  the video at a time, not about a sentence; nesting it in whichever sentence
  happens to span that second would invent a relationship nothing observed.
  `marks_meta` travels with it for the same reason `diarization` does — marks
  from a budget of 150 and marks from a budget of 20 are different documents.
- **`look` is not `t`, and a consumer wanting a frame should use `look`.** A
  mark is by construction the moment of maximum change, which is the moment the
  screen is halfway between two states — mid-load skeletons and half-drawn
  window switches. Measured: a frame at `t` differs from its neighbours in 9.9%
  of tiles against 2.2% at `look`. Use `t` to know *when*, `look` to know
  *where to point a camera*.

### The library

The app (`dsj ui`, v0.3.0) remembers every recording and transcript in one
SQLite file, created the first time it is opened. Every `dsj suno` run that
finishes adds its recording and its transcript to it, in the terminal as in the
app, so a transcript made with `dsj suno` is listed the next time the app opens.
That needs no `ui` extra. If the library cannot be written (a newer dsj made
it, say), the run says so in one line on stderr, keeps the transcript and still
exits 0. The file is:

- on a Mac, `~/Library/Application Support/dsj/library.db`
- elsewhere, `$XDG_DATA_HOME/dsj/library.db` (`~/.local/share/dsj/library.db`)
- anywhere, `DSJ_LIBRARY=<path>` instead, which is how the tests keep out of yours

It is an index and nothing more. The transcript JSON files stay the truth and
the library never writes to one, so deleting `library.db` loses the list, not a
transcript: every file still opens, and handing the same files to the library
again rebuilds it. A recording is known by its contents (#120), not its path, so
one that was renamed or moved shows as missing until it is pointed at the new
name, and then keeps every transcript it had. That new name lives only in the
library, so after a rebuild the recording reads missing again until it is
pointed at it a second time.

## Development

```bash
just test        # fast lane, ~10s
just typecheck   # pyright strict, package and tests
just check       # THE gate: types, lint, fast tests. What CI runs.
just verify      # everything incl. the end-to-end gates, with coverage
just mutate      # mutation testing over the pure modules
just ui-build    # rebuild the page dsj ui serves, from ui/ into dsj/ui/static/ (needs Node)
just ui-dev      # the API on :8721 and Vite on :5173, both reloading on save
```

`just verify` is the session-close gate and takes ~20 minutes: it runs real ASR
and diarization, including two end-to-end gates that deliberately re-prove they
can fail. That cost is the point — see [docs/tooling-gaps.md](docs/tooling-gaps.md).

| Doc | |
|---|---|
| [docs/tooling-gaps.md](docs/tooling-gaps.md) | the practices and tools this project is built to, written out of an audit where five defects shipped past a green suite |
| [docs/resume-gate-design.md](docs/resume-gate-design.md) | how you test a resume that silently restarts, given it produces byte-identical output |
| [docs/mutmut-triage.md](docs/mutmut-triage.md) | every surviving mutant and why it is accepted |
| [docs/visual-marks.md](docs/visual-marks.md) | the three change detectors that were built and measured before this one, and why each failed |
| [docs/generalisation.md](docs/generalisation.md) | two external benchmarks with human ground truth — 834 GUI recordings (p = 3.5e-94) and five hour-long lectures (81% of slide changes caught within 2s) |
| [docs/do-marks-help.md](docs/do-marks-help.md) | do the marks actually help an agent? Three arms, blind-graded: 5/16 → 7/16 → 16/16 |
| [docs/vlm-legibility.md](docs/vlm-legibility.md) | whether a small local VLM can read a screen frame. Two models, five prompts and budgets, one ground truth: 47% → 86%, and the blocker moves from legibility to speed |

---

## Why it is built this way

### The idea

Not "extract everything from the video." The video stays on disk as a
random-access resource, and the transcript is its index.

```
video ──► audio ──► timestamped transcript      (cheap, ~10k tokens, read fully)
  │
  └────── frames on demand, at timestamps the transcript justifies
```

An agent reads the transcript, hits a deictic moment, and asks for that instant.
Nothing else is ever extracted. Cost scales with what is *interesting*, not with
video length.

This inverts the usual pipeline. Scene-detect-then-OCR-everything is a **push**
design: extract all visual content upfront, pay for it whether or not any of it
mattered, then try to compress.

The false-positive half of that argument turned out to be **measurably true** —
a perceptual-hash detector fired on cursor movement alone on a real recording,
which is exactly what was predicted here before anyone had run one. The
conclusion drawn from it was too strong, though. Visual marks *do* enumerate the
video, and cheaply: ranking every sampled frame costs 33 ms of arithmetic on top
of a decode, and produces 150 timestamps and no descriptions. Enumerating is not
what makes the push design expensive; **describing** everything you enumerated
is. Marks are a table of contents, and the transcript still decides which
entries are worth opening.

### Decisions made so far

**ASR: Parakeet TDT 0.6b v3 via `parakeet-mlx`.**
Parakeet over Whisper for two structural reasons: it does not hallucinate on
silence — it predicts token *duration* and skips gaps rather than grinding every
frame — and that same mechanism makes its timestamps **native** rather than
recovered after the fact by DTW alignment the way Whisper's are. Native
timestamps are the whole product here: the transcript is only an index if its
times point at the right instants.

The MLX build was chosen over two other local copies of the same model. Handy
ships a NeMo ONNX export and FluidAudio a CoreML `.mlmodelc` of v2; same
weights, three incompatible formats. MLX wins on being Metal-native on the
target hardware and on `parakeet-mlx` exposing per-token alignment directly.

**Chunking is not optional at meeting length.** `parakeet-mlx` defaults
`chunk_duration` to `None`, which feeds the whole file to Metal in one buffer —
an hour of audio asks for ~14.5 GB against a ~9.5 GB max buffer and dies. dsj
drives the chunk loop itself at 120s with 15s overlap, which is also what makes
per-chunk progress and resume possible.

**Not OCR.** OCR flattens the frame to text and throws away everything that
carried the meaning — layout, table structure, what is highlighted, what the
cursor is resting on, the shape of a chart. Frames go to a vision model.

**Execution provider: CPU, not CoreML.** Measured on a 45s clip:

| Provider | Speed |
|---|---|
| `CPUExecutionProvider` | 45s audio in 2.3s — **19.7x realtime**, 1.1s load |
| CoreML | 45s audio in 33.9s — 1.3x realtime |

CoreML fragmented the encoder into 319 partitions across 3,249 nodes, supporting
only 1,528 of them; the marshalling cost swamped the compute. On a quantised int8
model the plain ONNX Runtime CPU kernels win outright. General lesson: a
triple-digit partition count in an EP load warning means the accelerator is
hurting you — benchmark against CPU before assuming otherwise.

**Ingestion: dsj runs ffmpeg itself, though it does not have to.**
`parakeet-mlx` already shells out to ffmpeg for any input, so a `.mov` would
load without a line of code here. It is done in `dsj/media.py` anyway for
two things that call cannot give: progress during the tens of seconds an
hour-long 4 GB recording takes to demux (~1000x realtime, measured on a
74-minute wav), and an error you can act on — parakeet's own failure surfaces
as the ffmpeg build banner with the diagnosis buried in it.

The extracted wav lives in a temp directory for the length of the run and is
not cached. Extraction is a small fraction of wall time, and caching would mean
inventing invalidation and leaving 135 MB files next to the user's recordings.
Anyone who wants the wav can extract it by hand and pass it — the conversion
step is skipped when the input is already mono `pcm_s16le` at the model's rate.

**Vision, not OCR — and the model is now chosen on measurement, not on
benchmarks.** The plan named Qwen2.5-VL-7B-Instruct on `mlx-vlm`, on the strength
of published DocVQA and ChartQA scores; it has still never been run here, and the
reason is now that it would be slower on the axis that blocks. Two models were
measured on five frames from a real recording against ground truth written down
first: `gemma-4-e2b-it-4bit` recalls 47% while fabricating 18 strings, and
`Qwen3-VL-4B-Instruct-4bit` recalls 86% on the identical prompt — but takes 156 s
per frame against gemma's 24. See
[docs/vlm-legibility.md](docs/vlm-legibility.md): the legibility question is
answered, and throughput replaced it as the open one.

**Speaker labels: senko, optional, and wrong in ways worth naming.**
Diarization is an extra — the `[diarize]` install above — not a dependency. It pulls
29 packages (scikit-learn, scipy, umap-learn, hdbscan, coremltools, numba) for
one optional pass, it is a source build, and on Darwin it forces
`device='coreml'` unconditionally, so a core dependency here would be a core
dependency that breaks `uv sync` for anyone not on Apple Silicon. Without it the
transcript is written exactly as before and the run exits 0.

senko over pyannote for one measured reason: it imports no torch, and on the
74-minute reference recording it diarized in **8.0s — 554x realtime**, plus **12.4s**
of warm model load. Against 149s of ASR that is **+14%**. The first run on a
machine pays **~51.5s** instead of 12.4s while CoreML compiles and persists its
embeddings cache; that is a one-off, and it is not the steady state a first-time
user should be shown as one.

Labels land on the *sentence*, as an integer index into a top-level `speakers`
array. Measured on the real transcript, that costs **1.7%** of file size; the
string `"SPEAKER_01"` on every sentence costs 3.3% to carry no extra
information, and a per-token label costs **20.4%** — 95 KB, ~24,000 tokens of
agent context — and was rejected. An integer also *looks* like the arbitrary
cluster id it is, where a name invites a reader to treat it as an identity. A
`diarization` provenance string sits beside `speakers`, and is **absent** when
the pass did not run: without it, "diarization was not run" and "diarization ran
and found one speaker" are the same document.

Sentences are labelled by counting **token votes** against turns, not by
intersecting the sentence's span with them. A span includes its internal
silences, so a speaker talking during a pause mid-sentence can hold more of the
span than the speaker who said the words. On the reference recording the two
approaches disagree on 6 of 664 sentences — this is a small correctness win, not
a large one, and it is kept because interval overlap fails worse the more
interleaved the speech gets.

What it gets wrong, all of it measured on a 74-minute reference recording
whose ground truth is two speakers:

- **Over-clustering.** senko found **three** speakers where there are two. The
  phantom holds 58.5s across 13 turns and **wins zero of the 664 sentences**
  under the token vote — the sentence-level schema absorbs it, where a
  per-token one would have put a nonexistent third speaker in front of the
  agent 13 times. senko exposes **no `num_speakers` knob**; clustering is
  unsupervised and the only parameter is `mer_cos`. A file where a phantom
  cluster *does* win sentences would produce a transcript with a speaker who
  does not exist.
- **Interruptions are misattributed.** parakeet segments on punctuation and
  pauses, not on voice, so one sentence can span a speaker change — 69 of 664,
  **10.4%**, do. The vote hands the whole sentence to whoever contributed more
  tokens, so a short interjection vanishes into the surrounding speaker and a
  long one takes their words with it. Splitting a sentence at a speaker change
  is the honest fix and is not in this tool.
- **Back-channels are invisible.** No turn on the reference file is shorter than
  1.01s, and senko's merged segments are non-overlapping, so the format cannot
  represent a "yeah" spoken over someone. It is attributed to whoever holds the
  floor. For an index whose job is to find *"see this column here"* — a
  floor-holder utterance — that is the right failure, but it is a failure.
- **Numbering is arbitrary and per-file.** `SPEAKER_01` in one recording has
  nothing to do with `SPEAKER_01` in another. It is a clustering artifact, not a
  speaking order and not a person.

---

## Roadmap

Frame *selection* is answered. Frame *description* is not.

**What the selection work settled** (numbers and method in
[docs/visual-marks.md](docs/visual-marks.md)):

- The pHash worry recorded here previously was right about the symptom and
  wrong about the direction. A 9x8 dHash did not under-trigger on "same doc,
  different cell" — it fired on **pointer movement alone** and missed a ticked
  checkbox, because 327x239-pixel cells resolve nothing smaller than a window
  switch. ffmpeg's `mpdecimate`, the standard duplicate dropper, failed the
  opposite way and kept 1997 of 1997 frames.
- The deeper finding is that **no threshold can work**, on any detector: during
  an active session the screen changes most seconds, so "the screen changed" is
  not a rare event and cannot be an index. Ranking under a fixed budget replaces
  it and needs no per-video tuning.
- **No eval set was needed.** The plan called for 50–100 hand-labelled frame
  pairs before anything could be trusted. A budget has no threshold to
  calibrate, so the thing the eval set existed to justify does not exist. Two
  synthetic controls — a static video that must yield nothing, a two-cut video
  that must yield exactly its two cuts — pin the behaviour instead.
- **DINOv2 was not needed either**, and the reason is cheaper than expected:
  mean-pooling on the way down to a 128x84 grid already suppresses smooth motion
  (webcam tiles, faces) while keeping the high-contrast edges of text and UI.

**What blocks description**, now measured rather than assumed
([docs/vlm-legibility.md](docs/vlm-legibility.md)):

- `gemma-4-e2b-it-4bit` recovered 33 of 70 hand-written ground-truth strings
  across five real frames (47%) while fabricating 18 — and the fabrications are
  fluent, plausible UI text (`Your GPS aren't the problem`, `OpenAI Browser`),
  which is the kind that poisons an index silently. Resolution is not the fix:
  700 → 1600 px moved recall by one string. Neither is the token budget: tripling
  it to 1200 returned the identical 33/70, string for string.
- `Qwen3-VL-4B-Instruct-4bit` on the same frames, same ground truth and same
  prompt recovers **60 of 70 (86%)**, including the matrix column headers and the
  message body that gemma missed entirely. Legibility is no longer what blocks.
- What blocks now is 156 s per frame — about 6.5 hours of description for a
  33-minute recording at 150 marks, on a fanless machine. Cutting the frame
  count, cropping to the changed region, or accepting an overnight batch are the
  levers, and none is measured yet.
- A terse "text only, no headings" prompt makes both models worse, not better:
  each degenerates into a repeat loop on the densest frame.
- **ColPali / ColQwen2** (late-interaction retrieval over page images, no OCR)
  remains the interesting alternative, but no MLX port exists and nobody reports
  running `colpali-engine` on Apple Silicon MPS. Experiment, not infrastructure.

### Prior art

Nothing does "long screen-recording in → deduped, VLM-described,
timestamp-queryable index out". `HKUDS/VideoRAG` is active and closest in spirit
but shaped for general long-video QA. The video-analysis MCP servers that exist
are OCR-based, which is the approach this tool rejects.

## Layout

```
dsj/            the package
  cli.py           the `dsj` command: suno | dekho | dikhao | hatao | likho | parho | ui
  suno.py          suno   -- ASR orchestration, chunking, resume
  dekho.py         dekho  -- the moments the picture changed, ranked under a budget
  media.py         ffmpeg: audio out, tile grids out, dikhao frames out, bleeps rendered
  hatao.py         hatao  -- the edit list, the word lists' matcher, what a render mutes
  words/           the shipped word lists, one TOML file a language
  chunking.py      the chunk loop parakeet-mlx does not provide
  likho.py         likho  -- a transcript out as SRT, WebVTT or text
  parho.py         parho  -- an SRT, WebVTT or JSON transcript in, in place of ASR
  checkpoint.py    resume, and the validated boundary that reads it
  identity.py      the content id a recording keeps through a rename, move or copy
  filetag.py       the transcript's copy as a hidden tag on the recording, macOS only
  merge.py         token-vote speaker labelling
  asr.py           the one shape every ASR engine returns
  parakeet.py      the parakeet engine, the default, on MLX
  whisper.py       the whisper engine, and why Roman Urdu is a prompt
  sherpa.py        the sherpa engine: parakeet's weights on ONNX, for the phone
  diarize.py       the fail-soft senko boundary
  atomic.py        write-or-do-not-write, for files a reader may be watching
  ui/              dsj ui: the local server, and static/, the built page it serves
  ui/store.py      the library: every recording and transcript, in one SQLite file
ui/                the page's source: Vite, React, TypeScript, Tailwind, shadcn
tests/             fast unit tests, plus the two slow end-to-end gates
scratch/           working probes; the data beside them is gitignored
docs/              the reasoning that did not fit here
```

## License

[GNU AGPL-3.0-only](LICENSE). Use it, change it, run it — but if you run a
modified version as a network service, its users get the source.
