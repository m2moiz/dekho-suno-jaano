#!/usr/bin/env python3
"""Build the two public reference recordings the accuracy scorer reads (#184).

#148's code-switching podcast (scratch/urdu_cs/, built by
scratch/build_urdu_fixture.py) is the first reference. This script builds the
other two, each about 30 minutes, as one WAV plus a `truth.json` in the same
shape as the podcast's `ground_truth.json` (`segments`, each with `start`,
`end` and `ground_truth`), so one scorer reads all three:

    uv run python scratch/accuracy/build_refs.py urdu
    uv run --with pyarrow python scratch/accuracy/build_refs.py earnings
    uv run --with pyarrow python scratch/accuracy/build_refs.py earnings_call

Nothing from either dataset is committed: sources download into
scratch/accuracy/source/, output goes to scratch/accuracy/<set>/, both ignored.

urdu: `ASLP-lab/UrduSpeech` at revision 16dd380cfd9049a3db7f06a98e878086916bf833,
CC-BY-4.0 (stated in the dataset README; credit below), the hand-checked
`benchmark/US-benchmark-Std/long/` subset: Urdu-script references, no
code-switching. Every clip of the categories in URDU_CATEGORIES, in category
then file order, joined by GAP_S of -60 dBFS noise. The brief's first choice,
`urdu-asr/csalt-voice` (revision 6f0c4fdeea94c77b4b64c4b88d5887e087566a5f),
was passed over: its README and Hub metadata state no licence at all.
Categories were picked for speech like the owner's (talk, news, interviews,
reviews) and against song, poetry, drama and film.

earnings: `distil-whisper/earnings22`, revision
0a034f9ed86d33a3859d9025d3e621cf243773ab, config `chunked`, the first parquet
shard. Earnings-22 is Rev's, CC-BY-SA-4.0 (revdotcom/speech-datasets,
earnings22/README.md; the Hub card's own licence section is a commented-out
copy of LibriSpeech's). One call, file 4483589, every segment that ends by
EARNINGS_END_S, put back on the call's own clock: each segment's samples at its
own start_ts, a later segment over an earlier one where they overlap (they are
cut from the same call, so the overlap is the same sound), and -60 dBFS noise
where no segment covers. The reference keeps Rev's text, `<inaudible>` tags
and all; the scorer drops tags.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "scratch" / "accuracy"
SOURCE = HERE / "source"
SAMPLE_RATE = 16000
NOISE_DBFS = -60.0

URDU_DATASET = "ASLP-lab/UrduSpeech"
URDU_REVISION = "16dd380cfd9049a3db7f06a98e878086916bf833"
URDU_PREFIX = "benchmark/US-benchmark-Std/long"
# `Podcast`, not `PODCAST`: both exist on the Hub, and on a case-insensitive
# disk (this Mac) their files would land in one folder. `Podcast` has 12 clips.
URDU_CATEGORIES = ("NEWS", "INTERVIEWS", "Podcast", "YOUTUBEREVIEWS", "ROADSIDE", "VLOG",
                   "COMEDYSHOW")
URDU_CREDIT = (
    "Haq, Zhu, Hu, He, Xie. UrduSpeech: A 156-Hour Urdu Speech Corpus with "
    "12-Dimension Paralinguistic Annotations, 2026, arXiv:2605.17846. CC-BY-4.0."
)
GAP_S = 1.5

EARNINGS_DATASET = "distil-whisper/earnings22"
EARNINGS_REVISION = "0a034f9ed86d33a3859d9025d3e621cf243773ab"
EARNINGS_SHARD = "chunked/test-00000-of-00038-6f4f182bdbb6f186.parquet"
EARNINGS_FILE = "4483589"
EARNINGS_END_S = 1805.0
EARNINGS_CREDIT = (
    "Del Rio, Delworth, Westerman, Hughes, Bhandari, Palakapilly, McNamara, Dong, "
    "Zelasko, Jette. Earnings-22: A Practical Benchmark for Accents in the Wild, "
    "2022, arXiv:2203.15591. CC-BY-SA-4.0."
)


def fetch(url: str, dest: Path) -> Path:
    """Download `url` to `dest` unless it is already there, never leaving a partial file."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(url) as response, partial.open("wb") as fh:
            while chunk := response.read(1 << 20):
                fh.write(chunk)
        partial.replace(dest)
    return dest


def decode(data: bytes) -> np.ndarray:
    """Any audio ffmpeg reads, as 16 kHz mono 16-bit samples."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", "-", "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "s16le", "-"],
        input=data, capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.int16)


def noise(samples: int, seed: int) -> np.ndarray:
    """Uniform white noise at NOISE_DBFS RMS, as build_urdu_fixture.py makes it."""
    raw = np.random.Generator(np.random.PCG64(seed)).bit_generator.random_raw(samples)
    unit = (raw >> np.uint64(11)).astype(np.float64) / float(1 << 53) * 2.0 - 1.0
    amplitude = 32768.0 * 10 ** (NOISE_DBFS / 20) * np.sqrt(3.0)
    return np.rint(unit * amplitude).astype(np.int16)


def write(name: str, audio: np.ndarray, truth: dict[str, Any]) -> None:
    out = HERE / name
    out.mkdir(parents=True, exist_ok=True)
    wav = out / f"{name}.wav"
    with wave.open(str(wav), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SAMPLE_RATE)
        fh.writeframes(audio.astype("<i2").tobytes())
    truth = {"audio": wav.name, "duration_s": round(len(audio) / SAMPLE_RATE, 3), **truth}
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n")
    clips = [s for s in truth["segments"] if "ground_truth" in s]
    words = sum(len(s["ground_truth"].split()) for s in clips)
    speech = sum(s["end"] - s["start"] for s in clips)
    print(f"{wav.relative_to(REPO)}: {len(audio) / SAMPLE_RATE:.1f} s, {len(clips)} segments, "
          f"{speech:.1f} s in segments, {words} reference words")


def urdu() -> None:
    resolve = f"https://huggingface.co/datasets/{URDU_DATASET}/resolve/{URDU_REVISION}"
    pieces: list[np.ndarray] = []
    segments: list[dict[str, Any]] = []
    cursor = 0
    for category in URDU_CATEGORIES:
        folder = SOURCE / "urdu" / category
        jsonl = fetch(f"{resolve}/{URDU_PREFIX}/{category}/clean_transcription.jsonl",
                      folder / "clean_transcription.jsonl")
        rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
        for row in sorted(rows, key=lambda r: r["Audio_Clip"]):
            name = row["Audio_Clip"]
            wav = fetch(f"{resolve}/{URDU_PREFIX}/{category}/audio/{name}", folder / "audio" / name)
            samples = decode(wav.read_bytes())
            if segments:
                gap = round(GAP_S * SAMPLE_RATE)
                pieces.append(noise(gap, len(segments)))
                cursor += gap
            segments.append({
                "kind": "clip", "clip": f"{category}/{Path(name).stem}",
                "start": round(cursor / SAMPLE_RATE, 3),
                "end": round((cursor + len(samples)) / SAMPLE_RATE, 3),
                "ground_truth": row["ground_truth"],
            })
            pieces.append(samples)
            cursor += len(samples)
    write("urdu", np.concatenate(pieces), {
        "source": {"dataset": URDU_DATASET, "revision": URDU_REVISION, "path": URDU_PREFIX,
                   "categories": list(URDU_CATEGORIES), "licence": "CC-BY-4.0",
                   "credit": URDU_CREDIT},
        "segments": segments,
    })


def earnings() -> None:
    import pyarrow.parquet as pq  # only this set needs it; run with `uv run --with pyarrow`

    shard = fetch(
        f"https://huggingface.co/datasets/{EARNINGS_DATASET}/resolve/{EARNINGS_REVISION}/{EARNINGS_SHARD}",
        SOURCE / "earnings22" / "shard0.parquet",
    )
    table = pq.read_table(shard).to_pylist()
    rows = sorted((r for r in table if r["file_id"] == EARNINGS_FILE and r["end_ts"] <= EARNINGS_END_S),
                  key=lambda r: r["start_ts"])
    origin = rows[0]["start_ts"]
    length = round((rows[-1]["end_ts"] - origin) * SAMPLE_RATE) + SAMPLE_RATE
    audio = noise(length, 22)
    segments: list[dict[str, Any]] = []
    for row in rows:
        samples = decode(row["audio"]["bytes"])
        at = round((row["start_ts"] - origin) * SAMPLE_RATE)
        audio[at : at + len(samples)] = samples[: length - at]
        segments.append({
            "kind": "clip", "clip": f"{EARNINGS_FILE}/{row['segment_id']}",
            "start": round(at / SAMPLE_RATE, 3),
            "end": round((at + len(samples)) / SAMPLE_RATE, 3),
            "ground_truth": row["transcription"],
        })
    write("earnings", audio, {
        "source": {"dataset": EARNINGS_DATASET, "revision": EARNINGS_REVISION,
                   "path": EARNINGS_SHARD, "file_id": EARNINGS_FILE,
                   "call_seconds": [round(origin, 3), EARNINGS_END_S],
                   "licence": "CC-BY-SA-4.0", "credit": EARNINGS_CREDIT},
        "segments": segments,
    })


EARNINGS_FULL_SHARD = "full/test-00001-of-00004-e6d772bca8e23981.parquet"


def earnings_call() -> None:
    """The same 30 minutes cut from the call's own recording, with no splices.

    `earnings` rebuilds the call from its segments. parakeet skipped whole
    segments there, each starting at a splice (#184), so this cut from the
    `full` config's continuous audio checks whether the splices were the cause.
    Same reference and the same clock as `earnings`: the call from its first
    segment's start, so earnings/truth.json scores it.
    """
    import pyarrow.parquet as pq

    shard = fetch(
        f"https://huggingface.co/datasets/{EARNINGS_DATASET}/resolve/{EARNINGS_REVISION}/{EARNINGS_FULL_SHARD}",
        SOURCE / "earnings22" / "full1.parquet",
    )
    table = pq.read_table(shard, filters=[("file_id", "=", EARNINGS_FILE)]).to_pylist()
    call = decode(table[0]["audio"]["bytes"])
    truth = json.loads((HERE / "earnings" / "truth.json").read_text())
    origin = truth["source"]["call_seconds"][0]
    a = round(origin * SAMPLE_RATE)
    audio = call[a : a + round(truth["duration_s"] * SAMPLE_RATE)]
    out = HERE / "earnings_call"
    out.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out / "earnings_call.wav"), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SAMPLE_RATE)
        fh.writeframes(audio.astype("<i2").tobytes())
    print(f"{(out / 'earnings_call.wav').relative_to(REPO)}: {len(audio) / SAMPLE_RATE:.1f} s, "
          f"scored with {(HERE / 'earnings' / 'truth.json').relative_to(REPO)}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("set", choices=("urdu", "earnings", "earnings_call"))
    args = parser.parse_args(argv)
    {"urdu": urdu, "earnings": earnings, "earnings_call": earnings_call}[args.set]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
