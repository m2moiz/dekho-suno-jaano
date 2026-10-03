# Bundles, engines, and how to install dsj

## Contents

- Install: pick a bundle
- Working from a clone
- What a bare install gives you
- Choosing an engine
- Urdu, and anything parakeet cannot read
- sherpa, Android, and the proot constraint
- Model defaults and where weights come from
- The Python version cap

## Install: pick a bundle

There is no default engine dependency and no bare install line, on purpose. A dsj with no
engine transcribes nothing, so installing it means choosing a bundle.

```bash
# macOS, Apple Silicon: both engines and the diarizer
uv tool install "dsj[mac] @ git+https://github.com/m2moiz/dekho-suno-jaano"

# the phone bundle: the sherpa ONNX engine only, no diarizer
uv tool install "dsj[android] @ git+https://github.com/m2moiz/dekho-suno-jaano"
```

Model weights, about 2.4 GB for parakeet, download on first run and are cached by
`huggingface_hub`.

The individual extras exist too, when a bundle carries more than you want:

| Extra | Pulls in | For |
|---|---|---|
| `mac` | `parakeet`, `whisper`, `diarize` | The working Mac setup |
| `android` | `sherpa` | The phone |
| `parakeet` | `parakeet-mlx` | The default engine. Apple Silicon and Metal only |
| `whisper` | `mlx-whisper` | Adds about 250 MB, because it pulls torch for its weight conversion path |
| `sherpa` | `sherpa-onnx` | The portable ONNX engine |
| `diarize` | `senko` | Speaker labels. CoreML, so macOS only |

The parakeet extra carries no environment markers deliberately, so asking for it on the
wrong machine fails loudly at resolve time rather than succeeding while installing
nothing.

`ffmpeg` must be on `PATH` for anything that is not already a 16 kHz mono wav, which in
practice means every `.mov`, `.mp4` and `.m4a`.

## Working from a clone

`uv sync` installs the command at `.venv/bin/dsj` and links it nowhere, so from a clone
every invocation needs a prefix:

```bash
uv sync --extra parakeet --extra whisper --extra diarize
uv run dsj suno recording.mov -o transcript.json
```

That is the `mac` bundle's set. `uv sync` installs exactly the extras on its line and
**uninstalls every other one**, so keep one sync line and add `--extra <name>` to it. A
bare `uv sync`, or `uv sync --extra <one>`, takes away the engines you already had.

`python -m dsj.suno` and `python -m dsj.dekho` are the same code and still work.
`python -m dsj` does not exist.

## What a bare install gives you

`uv tool install dsj` succeeds and gives you a core with no engine. That is what makes the
package installable on a phone before any backend is chosen. The first `suno` then refuses
with the name of the extra to add. See `failures.md` for the exact refusals.

## Choosing an engine

`--engine parakeet | whisper | sherpa`, default `parakeet`. There is no automatic
fallback: if the chosen engine cannot run, nothing is transcribed and the run exits 1.

| | parakeet | whisper | sherpa |
|---|---|---|---|
| Speed | About 13x realtime | About 1.7 to 3x on Urdu with `--roman-urdu`, about 5 to 6x on English. Per file in [whisper speed](#whisper-speed) | About 11.4x, measured on a OnePlus 15 in proot Ubuntu |
| Platform | Apple Silicon, Metal | Apple Silicon, Metal | Anywhere sherpa-onnx has wheels |
| Languages | 25, all European. No Urdu | Whatever whisper reads, including Urdu | Same weights as parakeet |
| Checkpoint and resume | Yes, per chunk | **Only after the decode.** Stopped while `running`, it starts over; stopped later, the rerun decodes nothing | Yes, per chunk |
| Progress reporting | Per chunk | With `--roman-urdu`, per window of about two minutes. Otherwise **one frame at 0%**, then nothing until transcription ends | Per chunk |
| Speaker labels | With the diarize extra | With the diarize extra | Not on the android bundle |
| Needs `--model` | No | No | **Yes**, see below |

parakeet is the default because it is roughly ten times faster and does not hallucinate
over silence. All three are fine for a voice note; only the chunked ones are right for an
hour of lecture.

### whisper speed

Every whisper speed figure in this repo, in one place. Wall clock from start to written
transcript, model load and audio extraction included, `whisper-large-v3-turbo`, on a 16 GB
M2 running one whisper at a time. Memory pressure alone has moved these threefold (issue
#139), so each carries the machine state it was measured in.

| audio | command | commit | speed | memory free at the low point |
|---|---|---|---|---|
| owner's 094234, Urdu, 27.9 min | `dsj suno <file> --roman-urdu` | `2f66fce` | 2.98x, 2.63x (two runs) | not logged |
| owner's 162033, Urdu, 22.0 min | `dsj suno <file> --roman-urdu` | `2f66fce` | 2.90x | 28 to 29% |
| owner's 171500, Urdu, 28.1 min | `dsj suno <file> --roman-urdu` | `9506685` | 2.19x | not logged |
| owner's 101117, Urdu and English, 13.1 min | `dsj suno <file> --roman-urdu` | `8ff5871` | 1.71x | 77% at the start, low point not logged |
| public fixture, Urdu and English, 854 s | `dsj suno scratch/urdu_cs/podcast.wav --roman-urdu --no-diarize` | `06d0576` | 3.41x (earlier 3.22x) | not logged |
| owner's 153458, English, 16.7 min | `dsj suno <file> --engine whisper` | `2f66fce` | 5.31x (earlier 6.37x) | 39% |

The owner's recordings are private and ran with speaker labelling, so their times include
it; the fixture ran with `--no-diarize`. `9506685` differs from `2f66fce` only in
`scratch/`, and `8ff5871` only in comments and docs, so the decode path is the same. `scratch/real_bench.py run --label <new> --only
<name>` re-measures an owner's file, and `scratch/real_bench.py fixture --label <new>` the
fixture.

## Urdu, and anything parakeet cannot read

`parakeet-tdt-0.6b-v3` covers 25 languages and they are all European, so an Urdu voice
note comes back as nothing usable. Whisper reads it:

```bash
dsj suno voice-note.m4a -o transcript.json --roman-urdu
```

`--roman-urdu` is `--language ur` plus a measured decoder prompt, and it upgrades
`--engine parakeet` to whisper for you. Roman Urdu is a **prompt**, not a setting: whisper
writes Urdu in Urdu script by default, and seeding the decoder with a Roman Urdu example
makes it emit Latin, which its own condition-on-previous-text then carries across
windows. On the public fixture below, 3% of the text comes back in Urdu script, with
English words left in English where they were spoken in English.

On long recordings the prompt is pushed out of whisper's context after 22 to 105 seconds,
so `--roman-urdu` cuts the audio into 120-second windows and re-seeds each one. That
window is measured, on the owner's two recordings that drift most (issue #100,
2026-10-02, turbo, `dsj suno <file> --roman-urdu`, the 30-second rows with
`ANCHOR_CHUNK_S` set to 30 by `scratch/whisper_sweep.py`):

| recording | window | runs | words | Urdu script | loop seconds |
|---|---|---:|---|---|---|
| 101117, 13.1 min | none (22 Sep) | 1 | 1,181 | 81% | 196 |
| | 120 s | 3 | 1,427 · 1,332 · 1,460 | 59 · 47 · 47% | 174 · 166 · 164 |
| | 30 s | 2 | 1,141 · 1,061 | 13 · 6% | 487 · 321 |
| 094234, 27.9 min | none (22 Sep) | 1 | 2,786 | 98% | 171 |
| | 120 s | 2 | 3,251 · 3,102 | 39 · 44% | 86 · 343 |
| | 30 s | 2 | 3,095 · 2,632 | 10 · 7% | 291 · 562 |

A shorter window keeps more text in Latin and loses words, so the window stays at 120
seconds. Expect some Urdu script in a long `--roman-urdu` transcript; the owner accepts it,
because the target is complete text, not Roman spelling.

`--prompt` takes your own text instead. `--language` and `--prompt` are whisper's alone;
passing either with parakeet is an error rather than a silent no-op.

The model matters more than it looks. Measured on the public Urdu-English fixture
(`just urdu-fixture`, 854 seconds, 1,293 English words in the hand-checked reference), one
run each, one whisper at a time on a 16 GB M2 (issue #33, 2026-10-02):

| model | flags | English words recovered | Urdu script | speed |
|---|---|---:|---:|---:|
| `whisper-large-v3-turbo` | `--roman-urdu` | 89.6% | 3% | 3.41x |
| `whisper-large-v3-turbo` | `--engine whisper --language ur` | 12.3% | 78% | 1.99x |
| `whisper-large-v3-mlx` (full) | `--roman-urdu` | 59.4% | 63% | 0.50x, 23% memory free |
| `whisper-large-v3-mlx` (full) | `--engine whisper --language ur` | 54.9% | 61% | 0.96x, 26% memory free |

```bash
dsj suno scratch/urdu_cs/podcast.wav --roman-urdu --no-diarize --model mlx-community/whisper-large-v3-mlx
```

Every run passed `--no-diarize`. The full model writes most of its text in Urdu script
whatever the prompt says, so `whisper-large-v3-turbo` is the default here and changing it
means re-measuring.

### Which mode, by error rate

Word error rate against three public hand-checked references, whisper-large-v3-turbo,
`--no-diarize`, two runs per whisper mode, 3 Oct 2026 (#184). The two figures are the two
runs; whisper does not give the same answer twice.

| speech | `--roman-urdu` | `--roman-urdu`, 30 s window | `--language ur` | whisper, language detected | parakeet |
|---|---:|---:|---:|---:|---:|
| Urdu and English in one sentence, #148's podcast, 14 min | 33.9 · 33.8% | 29.0 · 29.9% | 45.5 · 57.4% | 70.8 · 63.1% | 65.1% |
| Urdu, UrduSpeech's hand-checked set, 34 min | 40.8 · 42.7% | 47.1 · 48.7% | 20.7 · 23.3% | 25.8 · 25.2% | not run |
| English, an Earnings-22 call, 30 min | 29.1 · 15.8% | 19.3 · 15.3% | 18.9 · 7.9% | 4.5 · 4.4% | 10.2% |

Output and reference are both romanized with `uroman` and compared as consonant
skeletons, so the same word in Roman and in Urdu script, or English written in Urdu
letters, counts as a match. A hand check of 50 such pairs found the comparison wrong on
5, four of them two different words called the same, so it forgives slightly more than it
punishes. The scripts are in `scratch/accuracy/`.

1. **Urdu and English mixed:** `--roman-urdu`. `--language ur` gets 56 to 62% of the
   English words wrong, against 9 to 11% under `--roman-urdu`, and whisper left to detect
   the language writes the English and drops the Urdu.
2. **Mostly Urdu:** `--engine whisper --language ur`, about half the errors of
   `--roman-urdu` (21 to 23% against 41 to 43%), in Urdu script.
3. **The window stays at 120 s.** 30 s is 4 to 5 points better on the mixed recording
   and 6 points worse on Urdu, and on the owner's recordings it lost words (#100).
4. **English:** `--roman-urdu` and `--language ur` both loop on English, `--roman-urdu`
   for 140 to 284 s of the 30 minutes. parakeet skipped stretches of 11 to 46 s of the
   call's speech without marking them, which is most of its 10% (#228).

The owner's own corrected 10 minutes (#182) is the check on his voice.

## sherpa, Android, and the proot constraint

sherpa runs the ONNX export of the same parakeet weights, which is what makes a phone
possible: MLX publishes no wheels off Apple Silicon.

Three things to know before using it.

**It needs a proot container, not Termux.** sherpa-onnx ships manylinux wheels and Termux
is bionic, so the install lives inside a proot glibc container on the phone.

**It needs an explicit `--model <directory>`.** The command line resolves the default
model before it knows which engine you picked, and hands sherpa parakeet's Hugging Face
hub id, which is not a directory:

```bash
# fails: FileNotFoundError: sherpa model directory not found
dsj suno rec.m4a -o t.json --engine sherpa

# works
dsj suno rec.m4a -o t.json --engine sherpa --model /path/to/model-dir
```

The directory must contain encoder, decoder and joiner ONNX files (int8 or not) plus
`tokens.txt`. Nothing in the repository currently says where to obtain it, which is filed
as its own issue.

**There is no diarizer on that bundle.** Senko is CoreML and has no Android path, so
transcripts from the phone are unlabelled by design rather than by accident.

The NPU is not used. sherpa-onnx compiles its QNN runtime out of the published wheel, and
the CPU path measured faster than the published NPU benchmark anyway.

## Model defaults and where weights come from

| Engine | Default `--model` | Kind |
|---|---|---|
| parakeet | `mlx-community/parakeet-tdt-0.6b-v3` | Hugging Face hub id, downloaded and cached on first run |
| whisper | `mlx-community/whisper-large-v3-turbo` | Hugging Face hub id |
| sherpa | `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` | A **local directory**, because sherpa loads four files that have to agree with each other |

Changing `--model` invalidates any checkpoint written under the old one, which is correct:
the banked tokens describe a different model's output.

## The Python version cap

dsj requires Python 3.12 or 3.13, capped rather than open ended. The diarize extra reaches
coremltools, which publishes no wheel above 3.13 and declares no requirement of its own.
On 3.14 it builds from source into a pure-Python wheel with the CoreML extensions missing:
it imports cleanly and then cannot diarize, so the failure arrives as a transcript quietly
missing its speaker labels rather than as an error.

If senko is installed but will not import, that is the shape to suspect, and the remedy is
a reinstall pinned to 3.12.
