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

There are four, and no others. dsj defines no exit-code enum, so every domain failure
lands in the same bucket.

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success | |
| 1 | Any uncaught exception, printed as a Python traceback on stderr | Read the last line. It names the class and carries the remedy. |
| 2 | A usage error from the argument parser | You got the flags wrong. Run `dsj <verb> --help`. |
| 130 | Interrupted with Ctrl-C or SIGINT | For `suno` on parakeet or sherpa this is safe and resumable. Re-run the same command. |

`--help` exits 0 on every command, and a bare `dsj` with no arguments prints help and
exits 2.

## The one rule: read the last line of stderr

A failure is a traceback, so the useful sentence is at the **bottom**, not the top. When
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
| `No such option: --version` | There is no version flag. See `dsj --help` for the whole surface |

`--engine` is **not** validated by the parser. A bad engine name reaches the application
and exits 1, not 2:

```
ValueError: unknown engine 'bogus', expected one of parakeet, whisper, sherpa
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
| whisper | `mlx-whisper is not installed. Install it with uv tool install "dsj[whisper] @ git+https://github.com/m2moiz/dekho-suno-jaano" (or uv sync --extra whisper from a clone).` |
| sherpa | `sherpa-onnx will not import here: <import error>. Install it with pip install sherpa-onnx (manylinux wheels only, inside a proot/glibc container on Android, not Termux itself).` |

A bare install carries no engine at all, on purpose, so that the package can install on a
phone. The first `suno` then names the extra to add. See `engines.md`.

`--engine sherpa` has a separate failure that is not about installation:

```
FileNotFoundError: sherpa model directory not found: mlx-community/parakeet-tdt-0.6b-v3
```

That is the known defect described in `engines.md`. Pass `--model <directory>` explicitly.

## Media and ffmpeg failures

| Class | Message and remedy |
|---|---|
| `FFmpegNotFound` | `ffmpeg is not on PATH. dsj reads video through ffmpeg; install it with brew install ffmpeg.` |
| `NoAudioStream` | `<file> has no audio stream, so there is nothing to transcribe. If this is a silent screen capture, re-record with audio enabled.` |
| `NoVideoStream` | The file has no picture, so `dekho` and `dikhao` have nothing to scan or seek. |
| `MediaError` on extraction | Carries ffmpeg's own log plus the exact command to reproduce it by hand. |
| `MediaError` on a frame | Either `<t>s is past the end of this <duration>s recording.` or, when the timestamp was in range, `ffmpeg read the file but produced no frame; its log is above.` |
| `FileNotFoundError` | The path does not exist. It is a bare path with no other text. |

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

If a labelled transcript is the requirement rather than a bonus, pass `--require-diarize`
and the same condition becomes an exit 1. If labels are irrelevant, `--no-diarize` skips
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
| `ValueError` | `--language` or `--prompt` passed with parakeet: `--language and --prompt are whisper's; parakeet takes neither. Add --engine whisper, or drop them.` |
| `ValueError` | `--fps` not positive, or `--budget`, `--min-gap` or `--delta` negative |
| `ValueError` | A negative timestamp or a `--width` of less than zero on `dikhao` |

## Detecting failure from a `--status` file

The failure document has only two keys:

```json
{"state": "failed", "error": "FileNotFoundError: /nope.mov"}
```

No `fraction`, no `audio_done_s`, no `eta_s`. A poller that reads those unconditionally
crashes exactly when the run it is watching has failed. Read `state` first, every time.

The document is only written when the failure passes through the command line. A library
caller using `dsj.suno.transcribe(...)` directly gets no failure document, and the last
frame written stays whatever it was.
