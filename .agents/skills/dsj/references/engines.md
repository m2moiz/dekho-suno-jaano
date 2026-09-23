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
uv sync --extra parakeet --extra diarize
uv run dsj suno recording.mov -o transcript.json
```

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
| Speed | About 13x realtime | About 1.4x realtime | About 11.4x, measured on a OnePlus 15 in proot Ubuntu |
| Platform | Apple Silicon, Metal | Apple Silicon, Metal | Anywhere sherpa-onnx has wheels |
| Languages | 25, all European. No Urdu | Whatever whisper reads, including Urdu | Same weights as parakeet |
| Checkpoint and resume | Yes | **No.** An interrupted run starts over | Yes |
| Progress reporting | Per chunk | **One frame at 0%**, then nothing until the end | Per chunk |
| Speaker labels | With the diarize extra | With the diarize extra | Not on the android bundle |
| Needs `--model` | No | No | **Yes**, see below |

parakeet is the default because it is roughly ten times faster and does not hallucinate
over silence. All three are fine for a voice note; only the chunked ones are right for an
hour of lecture.

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
windows. Measured on 116 seconds of Urdu speech, 275 of 277 words came back in Latin, with
English words left in English where they were spoken in English.

`--prompt` takes your own text instead. `--language` and `--prompt` are whisper's alone;
passing either with parakeet is an error rather than a silent no-op.

The model matters more than it looks. The full `whisper-large-v3` ignores the prompt
outright and takes about two and a half times as long, so `whisper-large-v3-turbo` is the
default here and changing it means re-measuring.

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
