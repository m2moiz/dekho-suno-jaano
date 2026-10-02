# How dsj fails, and what to do about it

## Contents

- Exit codes
- The one rule: read the last line of stderr
- Usage errors, exit 2
- Engine and install failures
- Media and ffmpeg failures
- Diarization, which fails soft
- Transcript and argument failures
- Detecting failure from a `--status` file

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success | |
| 1 | `suno`: a mistake you can put right, printed as one line, `dsj: <message>`. A missing input, an `-o` or `--status` in a directory that does not exist, an unknown `--engine`, whisper's options on parakeet, an engine or ffmpeg that is not installed | Read the line. It carries the remedy. |
| 1 | Anything else, printed as a Python traceback on stderr. On `suno` that is a bug in dsj | Read the last line. It names the class and carries the remedy. |
| 1 | `hatao`: a mistake you can put right, one line, `dsj: <message>`. A missing file, a transcript with no word end times, a broken user word list, a recording with no sound, an output that exists without `--overwrite` | Read the line. It carries the remedy. |
| 2 | A usage error from the argument parser | You got the flags wrong. Run `dsj <verb> --help`. |
| 3 | `hatao` only: no word in the transcript matched a word list. Nothing was written | If a word you can hear should have matched, add its spelling to the user word list the warning names. If the recogniser never wrote it down, no list will find it. |
| 75 | `suno` only: another `suno` is already running on this machine. Nothing was started | Wait for the pid stderr names to finish, then run it again. |
| 130 | Interrupted with Ctrl-C or SIGINT | For `suno` on parakeet or sherpa this is safe and resumable. Re-run the same command. |
| 143 | Stopped by `kill` | The same as 130. |

`--help` exits 0 on every command, `dsj --version` exits 0, and a bare `dsj` with no
arguments prints help and exits 2.

## The one rule: read the last line of stderr

A `suno` failure you caused is one line that starts `dsj: ` (#200), and nothing else:

```
dsj: cannot write /tmp/nope-dir/x.json: the directory /tmp/nope-dir does not exist. Create it first (mkdir -p /tmp/nope-dir) or pass another -o.
```

Anything else is a traceback, so the useful sentence is at the **bottom**, not the top. When
ffmpeg is involved its own log is printed above the exception, which can be twenty lines
of noise ahead of the one line that tells you what happened:

```
[out#0/image2 @ 0x...] Nothing was written into output file, because at least one of its
streams received no packets.
99999.0s is past the end of this 230.7s recording.
```

The second line is the answer. Nothing above it is.

`suno` and `dekho` print **nothing at all on stdout**, so a captured stdout that is empty
says nothing about success. `dikhao` prints the output path on stdout and nothing else,
which is what makes `open "$(dsj dikhao rec.mov 431.5 -o /tmp/f.jpg)"` work.

Progress bars, warnings and the closing summary all go to stderr, which means stderr is
never empty on a successful `suno` either. Branch on the exit code, then read stderr.

## Usage errors, exit 2

| Symptom | Cause |
|---|---|
| `Missing option '--out' / '-o'.` | `-o` is required on `suno` and `dikhao` |
| `Missing option '--transcript' / '-t'.` | `-t` is required on `dekho` |
| `No such command 'transcribe'.` | The verbs are `suno`, `dekho`, `dikhao` |
| `No such option`, for a flag a document names | The document describes another build. Compare `dsj --version` with the version the document was written against |

`--engine` is **not** validated by the parser. A bad engine name reaches the application
and exits 1, not 2:

```
dsj: unknown engine 'bogus', expected one of parakeet, whisper, sherpa
```

## Engine and install failures

`EngineUnavailable` means nothing was transcribed. There is deliberately no fallback to a
different engine, because a transcript quietly produced by another model at another
quality under a different `model` key is worse than failing in one second.

The message is always `the <name> engine cannot run here: <reason>`, and the reason
carries the remedy:

| Engine | Reason, and what to do |
|---|---|
| parakeet | `parakeet-mlx is not installed. It requires Apple Silicon and Metal; this machine is <machine> <system>.` Install the mac bundle, or pick another engine. |
| whisper | `mlx-whisper is not installed. Install it with uv tool install "dsj[whisper] @ git+https://github.com/m2moiz/dekho-suno-jaano", or from a clone add --extra whisper to the uv sync line you already use (uv sync uninstalls every extra it is not given).` |
| sherpa | `sherpa-onnx will not import here: <import error>. Install it with uv tool install "dsj[sherpa] @ git+https://github.com/m2moiz/dekho-suno-jaano", or from a clone add --extra sherpa to the uv sync line you already use (uv sync uninstalls every extra it is not given). On Android that install goes inside a proot glibc container, not Termux itself, which is bionic.` |

A bare install carries no engine at all, on purpose, so that the package can install on a
phone. The first `suno` then names the extra to add. See `engines.md`.

`--engine sherpa` has a separate failure that is not about installation:

```
FileNotFoundError: sherpa model directory not found: mlx-community/parakeet-tdt-0.6b-v3
```

That is the known defect described in `engines.md`. Pass `--model <directory>` explicitly.

`UIUnavailable` means `dsj ui` started nothing: the `ui` extra, fastapi and uvicorn, is not
installed. The message names the import that failed and the remedy:

```text
dsj ui needs the `ui` extra, which is not installed here (No module named 'fastapi'). Install it with `uv tool install "dsj[mac,ui] @ git+https://github.com/m2moiz/dekho-suno-jaano"`, or from a clone add `--extra ui` to the `uv sync` line you already use (`uv sync` uninstalls every extra it is not given).
```

From a clone, `UIUnavailable` can also say `the built page is missing`: `dsj/ui/static/`
has no `index.html`. `just ui-build` writes it, and needs Node; an install never does.

## Media and ffmpeg failures

| Class | Message and remedy |
|---|---|
| `FFmpegNotFound` | `ffmpeg is not on PATH. dsj reads video through ffmpeg; install it with brew install ffmpeg.` |
| `NoAudioStream` | `<file> has no audio stream, so there is nothing to transcribe. If this is a silent screen capture, re-record with audio enabled.` |
| `NoVideoStream` | The file has no picture, so `dekho` and `dikhao` have nothing to scan or seek. |
| `MediaError` on extraction | Carries ffmpeg's own log plus the exact command to reproduce it by hand. |
| `MediaError` on a frame | Either `<t>s is past the end of this <duration>s recording.` or, when the timestamp was in range, `ffmpeg read the file but produced no frame; its log is above.` |
| `FileNotFoundError` | The path does not exist. `suno` says so in one line, `dsj: <path> does not exist.`, before any model loads; `dekho` and `dikhao` raise it with the bare path as its whole text. |

One inconsistency worth knowing: the sherpa engine calls ffmpeg directly rather than
through the shared boundary, so on a machine with no ffmpeg that path raises a bare
`FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'` with no remedy
attached. That is issue #49 in this repository, not a mystery.

## Diarization, which fails soft

`DiarizationUnavailable` does **not** fail the run. The ASR work is already paid for and
already on disk, so the transcript is written without labels, a warning goes to stderr,
and the exit code is 0:

```
diarization skipped: senko is not installed, so sentences cannot be labelled with who spoke.
```

A crash inside the diarizer itself is treated the same way: the transcript is kept
unlabelled, the exit code is 0, and the warning names the exception. The one seen in
practice is numba's compile cache failing to save while senko clusters (#186):

```
speaker labelling failed, transcript left unlabelled: ReferenceError: underlying object has vanished
```

To keep it from happening, dsj gives numba a cache directory of its own per run,
removed when the run exits. That costs about 9 s of compiling per labelled run, and no
run shares a cache another process wrote, which is where the crash was observed.

If a labelled transcript is the requirement rather than a bonus, pass `--require-diarize`
and either condition becomes an exit 1. If labels are irrelevant, `--no-diarize` skips
the pass and saves the time.

Detect the outcome in the payload, not in the log: `speakers` and `diarization` are
absent when the pass did not run.

The other variant is worth recognising because the remedy differs. Senko installed but
refusing to import means a native dependency was built from source for an interpreter it
has no wheel for, and the fix is a reinstall pinned to Python 3.12.

## Transcript and argument failures

| Class | Trigger |
|---|---|
| `MarkError` | `dekho -t` was pointed at a file that is not a JSON object: `<path> is not a transcript: expected a JSON object, found list. Pass the file dsj suno wrote.` |
| `BadOption`, a `ValueError` | `--language` or `--prompt` passed with parakeet, printed as `dsj: --language and --prompt are whisper's; parakeet takes neither. Add --engine whisper, or drop them.` |
| `MissingPath`, a `FileNotFoundError` | `suno`'s input is not there, or its `-o` or `--status` is in a directory that does not exist. One line, `dsj: ...`, naming the `mkdir -p` that fixes it. |
| `ValueError` | `--fps` not positive, or `--budget`, `--min-gap` or `--delta` negative |
| `ValueError` | A negative timestamp or a `--width` of less than zero on `dikhao` |
| `TranscriptUnusable`, a `ValueError` | `hatao`'s transcript has a token with no `e`, or tokens running backwards: written before v0.2.0, imported by `parho`, or written before v0.2.3 and overlapping at a seam. Muting it would mean guessing where a word is, so it is refused. Transcribe the recording again |
| `WordListError`, a `ValueError` | The user word list is not TOML, or an entry has no `name`, no spellings, a key other than `roman`, `script` and `disguised`, or a spelling that is all punctuation. Named with its file |

## Detecting failure from a `--status` file

The failure document has only three keys:

```json
{"state": "failed", "pid": 4242, "error": "MissingPath: /nope.mov does not exist."}
```

No `fraction`, no `audio_done_s`, no `eta_s`. A poller that reads those unconditionally
crashes exactly when the run it is watching has failed. Read `state` first, every time.

`dsj.suno.transcribe(...)` writes it itself (#103), so a library caller that passes a
`status_path` gets it too, not only the command line.
