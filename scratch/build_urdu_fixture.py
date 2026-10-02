#!/usr/bin/env python3
"""Build the public Urdu-English test recording from UrduSpeech (#148).

The repo had no Urdu audio and no Urdu transcript, and the owner's recordings
(#149) are private. This script builds the public one: 12.5 minutes of one
code-switching podcast speaker, stitched back into a continuous conversation,
with a human-checked transcript to score against and three quiet gaps to test
whether whisper invents text over silence.

    just urdu-fixture
    uv run python scratch/build_urdu_fixture.py [--gaps zero]

Source, credit and licence:

    Haq, Zhu, Hu, He, Xie. *UrduSpeech: A 156-Hour Urdu Speech Corpus with
    12-Dimension Paralinguistic Annotations*, 2026, arXiv:2605.17846. CC-BY-4.0.

The licence is stated in the dataset README at the pinned revision. It is NOT in
the Hub's metadata tags, so an automated licence check will not find it.

Dataset `ASLP-lab/UrduSpeech`, revision
16dd380cfd9049a3db7f06a98e878086916bf833, path
`benchmark/US-benchmark-CS/long/PODCAST/`, `SPEAKER_000` only: 30 clips from
the hand-checked `US-benchmark` subset. Nothing from the dataset is committed;
it is downloaded into scratch/urdu_cs/source/ (gitignored), and each WAV is
checked against the sha256 the Hub records for it at that revision.

What it builds, all under scratch/urdu_cs/:

1. `podcast.wav`: the 30 clips in clip-number order, 16 kHz mono 16-bit PCM,
   with three gaps inserted at clip joins: 10 s after clip 7, 30 s after clip
   15, 60 s after clip 22. The gaps are low-level white noise at -60 dBFS RMS,
   not digital zero, because a real quiet stretch carries room sound.
2. `ground_truth.json`: every clip's start, end and `ground_truth` text in the
   stitched file, every gap's start, end and kind, and every jump in the clip
   numbering.

`--gaps zero` builds `podcast_zero.wav` and `ground_truth_zero.json` instead,
the same file with digital-zero gaps. If whisper treats true silence
differently from room sound, that difference is itself a finding.

Two wrinkles, recorded and not fixed:

- Boundary phrases repeat. Where one clip ends and the next begins with the
  same words, the stitched audio says them twice, and so does the ground truth.
  Scoring stays honest about it.
- The numbering has holes (0004 then 0006, 0007 then 0010, ...). At each hole
  the conversation jumps; `jumps` in the ground truth lists every one.

The dataset's `Duration_seconds` field is not the clip length (clip 0002 says
32, the WAV is 35.0 s), so every time here comes from the decoded samples.

Deterministic: the noise comes from a seeded PCG64's raw output, which NumPy
keeps stable across versions, and resampling is ffmpeg's default resampler.
Built 2026-09-23 with ffmpeg 9.0.1, three times (one from a cold download,
two from the cache), to the same bytes, 853.7 s long:

    podcast.wav       sha256 dd004bf0d5d6ff99fce92a420954a9c5413a275ee60f546cfaf1bf7910ad0bd4
    podcast_zero.wav  sha256 4c25e5be997820d4848fb2956fbcebbf4da6361f87dba6e6f9d929a2f93b4e01

A different hash means different audio, so the build fails rather than hand a
test a file its numbers were not measured on. The likeliest cause is another
ffmpeg version resampling differently; the message prints the version in use.

Baseline, 2026-09-23, commit 372d10e (v0.2.0's decode path, so before #99 and
#100), whisper-large-v3-turbo, 72% memory free, 10.7 of 12.0 GB swap in use:

    uv run dsj suno scratch/urdu_cs/podcast.wav --roman-urdu --no-diarize \\
        -o scratch/urdu_cs/roman.json
    uv run python scratch/urdu_script_share.py scratch/urdu_cs/roman.json

- 853.7 s of audio in 265.4 s wall clock, 3.22x realtime, model load included.
- Urdu script: 6 s of 763 s in sentences (1%). The first Urdu-script sentence
  starts at 571.6 s. This file does NOT reproduce the owner's drift (78% to
  98% on #149's set), so a clean result here is not evidence drift is fixed.
- Loops by scratch/real_bench.py's rule (more than six words, at most two
  distinct): one sentence, 4.4 s.
- Words starting inside the gaps: 1 in the 10 s gap, 1 in the 30 s, 223 in
  the 60 s. Those 223 are a phrase cycling three distinct words, which the
  two-distinct loop rule does not count.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "scratch" / "urdu_cs"
SOURCE = OUT / "source"

DATASET = "ASLP-lab/UrduSpeech"
REVISION = "16dd380cfd9049a3db7f06a98e878086916bf833"
PREFIX = "benchmark/US-benchmark-CS/long/PODCAST"
SPEAKER = "SPEAKER_000"
RESOLVE = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}"
TREE = f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}"
CREDIT = (
    "Haq, Zhu, Hu, He, Xie. UrduSpeech: A 156-Hour Urdu Speech Corpus with "
    "12-Dimension Paralinguistic Annotations, 2026, arXiv:2605.17846. CC-BY-4.0."
)

SAMPLE_RATE = 16000
CLIPS = 30
# (clips before the gap, gap seconds). Joins spread through the file: roughly
# a quarter, a half and three quarters of the way through the speech.
GAPS = ((7, 10.0), (15, 30.0), (22, 60.0))
NOISE_DBFS = -60.0
NOISE_SEED = 148

PODCAST_SHA256 = "dd004bf0d5d6ff99fce92a420954a9c5413a275ee60f546cfaf1bf7910ad0bd4"
ZERO_SHA256 = "4c25e5be997820d4848fb2956fbcebbf4da6361f87dba6e6f9d929a2f93b4e01"

CLIP_NUMBER = re.compile(r"_(\d+)(?:\.WAV)?$", re.IGNORECASE)
ARABIC_BLOCK = ("\u0600", "\u06ff")


def clip_number(name: str) -> int:
    """The number at the end of a clip name: SPEAKER_000_PODCAST_0010.WAV is 10."""
    found = CLIP_NUMBER.search(name)
    if not found:
        raise ValueError(f"no clip number in {name!r}")
    return int(found.group(1))


def noise(samples: int, kind: str, seed: int) -> np.ndarray:
    """A gap's audio: uniform white noise at NOISE_DBFS RMS, or digital zero.

    Built from the bit generator's raw output rather than a distribution method,
    because NumPy keeps the raw stream stable across versions and not the rest.
    """
    if kind == "zero":
        return np.zeros(samples, dtype=np.int16)
    raw = np.random.Generator(np.random.PCG64(seed)).bit_generator.random_raw(samples)
    unit = (raw >> np.uint64(11)).astype(np.float64) / float(1 << 53) * 2.0 - 1.0
    # Uniform on [-a, a] has RMS a / sqrt(3).
    amplitude = 32768.0 * 10 ** (NOISE_DBFS / 20) * np.sqrt(3.0)
    return np.rint(unit * amplitude).astype(np.int16)


def layout(
    clips: list[tuple[str, int, str]], gaps: tuple[tuple[int, float], ...], kind: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Where every clip and gap sits in the stitched file, and every numbering jump.

    Args:
        clips: (clip name, length in samples, ground truth text), in play order.
        gaps: (clips before the gap, gap seconds).
        kind: "noise" or "zero", recorded on each gap.

    Returns:
        The segments in order, and the jumps: every join where the next clip's
        number is not one more than the last, so the conversation skips.
    """
    after = dict(gaps)
    segments: list[dict[str, Any]] = []
    jumps: list[dict[str, Any]] = []
    cursor = 0
    for index, (name, length, text) in enumerate(clips):
        if index and clip_number(name) != clip_number(clips[index - 1][0]) + 1:
            jumps.append({
                "from_clip": clip_number(clips[index - 1][0]),
                "to_clip": clip_number(name),
                "at": round(cursor / SAMPLE_RATE, 3),
            })
        segments.append({
            "kind": "clip",
            "clip": name,
            "start": round(cursor / SAMPLE_RATE, 3),
            "end": round((cursor + length) / SAMPLE_RATE, 3),
            "ground_truth": text,
        })
        cursor += length
        if index + 1 in after:
            gap = round(after[index + 1] * SAMPLE_RATE)
            segments.append({
                "kind": "gap",
                "noise": kind,
                "start": round(cursor / SAMPLE_RATE, 3),
                "end": round((cursor + gap) / SAMPLE_RATE, 3),
            })
            cursor += gap
    return segments, jumps


def fetch(url: str, dest: Path) -> None:
    """Download `url` to `dest` unless it is already there, never leaving a partial file."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as fh:
        while chunk := response.read(1 << 20):
            fh.write(chunk)
    partial.replace(dest)


def expected_hashes() -> dict[str, str]:
    """The sha256 the Hub records for every SPEAKER_000 WAV at the pinned revision."""
    with urllib.request.urlopen(f"{TREE}/{PREFIX}/audio") as response:
        entries = json.load(response)
    return {
        Path(e["path"]).name: e["lfs"]["oid"]
        for e in entries
        if Path(e["path"]).name.startswith(SPEAKER)
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def decode(path: Path) -> np.ndarray:
    """A clip as 16 kHz mono 16-bit samples."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.int16)


def ffmpeg_version() -> str:
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()[0]


def speaker_rows() -> list[dict[str, Any]]:
    """SPEAKER_000's transcript rows, in clip-number order."""
    jsonl = SOURCE / "clean_transcription.jsonl"
    fetch(f"{RESOLVE}/{PREFIX}/clean_transcription.jsonl", jsonl)
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    mine = sorted((r for r in rows if r["Speaker_id"] == SPEAKER),
                  key=lambda r: clip_number(r["Audio_Clip"]))
    if len(mine) != CLIPS:
        sys.exit(f"expected {CLIPS} {SPEAKER} clips at {REVISION[:12]}, found {len(mine)}")
    return mine


def write_atomic(path: Path, data: bytes) -> None:
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(path)


def build(kind: str) -> int:
    rows = speaker_rows()
    hashes = expected_hashes()
    clips: list[tuple[str, int, str]] = []
    audio: list[np.ndarray] = []
    for row in rows:
        name = row["Audio_Clip"]
        wav = SOURCE / "audio" / name
        fetch(f"{RESOLVE}/{PREFIX}/audio/{name}", wav)
        if sha256(wav) != hashes.get(name):
            wav.unlink()
            sys.exit(f"{name}: sha256 differs from the Hub's record at {REVISION[:12]}; "
                     "deleted it, rerun to download again")
        samples = decode(wav)
        clips.append((Path(name).stem, len(samples), row["ground_truth"]))
        audio.append(samples)

    segments, jumps = layout(clips, GAPS, kind)
    pieces: list[np.ndarray] = []
    clip_audio = iter(audio)
    for seed, segment in enumerate(segments):
        if segment["kind"] == "clip":
            pieces.append(next(clip_audio))
        else:
            length = round((segment["end"] - segment["start"]) * SAMPLE_RATE)
            pieces.append(noise(length, kind, NOISE_SEED + seed))
    stitched = np.concatenate(pieces)

    stem = "podcast" if kind == "noise" else "podcast_zero"
    wav_out = OUT / f"{stem}.wav"
    partial = OUT / f"{stem}.wav.part"
    with wave.open(str(partial), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SAMPLE_RATE)
        fh.writeframes(stitched.astype("<i2").tobytes())
    partial.replace(wav_out)
    digest = sha256(wav_out)

    text = " ".join(t for _, _, t in clips)
    urdu = sum(1 for c in text if ARABIC_BLOCK[0] <= c <= ARABIC_BLOCK[1])
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    truth = {
        "source": {
            "dataset": DATASET, "revision": REVISION, "path": PREFIX,
            "speaker": SPEAKER, "licence": "CC-BY-4.0", "credit": CREDIT,
        },
        "audio": wav_out.name,
        "sha256": digest,
        "sample_rate": SAMPLE_RATE,
        "duration_s": round(len(stitched) / SAMPLE_RATE, 3),
        "letters": {"latin": latin, "urdu_script": urdu},
        "jumps": jumps,
        "segments": segments,
    }
    json_out = OUT / ("ground_truth.json" if kind == "noise" else "ground_truth_zero.json")
    write_atomic(json_out, (json.dumps(truth, ensure_ascii=False, indent=2) + "\n").encode())

    speech = sum(length for _, length, _ in clips) / SAMPLE_RATE
    print(f"{wav_out.relative_to(REPO)}: {len(stitched) / SAMPLE_RATE:.1f} s "
          f"({speech:.1f} s speech in {len(clips)} clips, {len(GAPS)} {kind} gaps), "
          f"{len(jumps)} numbering jumps")
    print(f"ground truth letters: {latin} Latin, {urdu} Urdu script "
          f"({100 * urdu / (urdu + latin):.0f}% Urdu)")
    print(f"sha256 {digest}")

    pinned = PODCAST_SHA256 if kind == "noise" else ZERO_SHA256
    if digest != pinned:
        print(f"MISMATCH: the pinned sha256 is {pinned}. Built with {ffmpeg_version()}; "
              "the pinned file was built with ffmpeg 9.0.1. Different bytes are "
              "different audio, so numbers measured on the pinned file do not "
              "transfer to this one.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--gaps", choices=("noise", "zero"), default="noise",
                        help="low-level noise (the fixture) or digital zero (the comparison)")
    args = parser.parse_args(argv)
    return build(args.gaps)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
