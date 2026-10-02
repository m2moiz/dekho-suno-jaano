#!/usr/bin/env python3
"""How loud is real speech, and how loud is the fixture's silence (#181)?

Measures, without running a model, the loudness of the audio under every word
of the transcripts already on disk, so a silence threshold can be placed below
real speech with a measured margin, or shown not to exist.

    export DSJ_REAL_AUDIO="$HOME/Library/CloudStorage/GoogleDrive-m.moiz1995@gmail.com/My Drive/Hi-Q Recordings"
    uv run python scratch/speech_loudness.py measure
    uv run python scratch/speech_loudness.py apply

`measure` is the measurement the threshold was chosen on. `apply` runs the
rule dsj now ships (dsj.suno's silences and _without_silence, on
dsj.media.loudness) over the same transcripts and counts what it takes out.

Sources:

- #148's public fixture, scratch/urdu_cs/podcast.wav: the words of every
  transcript of it under scratch/real_bench/runs/*/podcast.json whose start
  falls inside a ground-truth speech clip, and the 0.1 s frames of its three
  quiet gaps.
- The owner's five files: every transcript under
  scratch/real_bench/runs/*/recording-*.json plus the 22 Sep transcripts in
  $DSJ_REAL_AUDIO/transcripts/ (153458's is the parakeet control).

A word in a repetition loop (dsj.suno.is_loop on a sentence, or inside an
`unclear` span) is left out: those are not known to be speech. A word's
loudness is the RMS of the audio from its start to its end, over at least one
0.1 s frame; a token without an end runs to the next token's start, at most
1 s. Its "near" level is the loudest 0.1 s frame within 1 s of its start,
either side: whisper puts a real word's start up to half a second into the
pause before it (#181), so the RMS of its own span can be the pause's.

The last table is the candidate rule's view: a run of 0.1 s frames all below
T dB lasting at least N s is silence, and a word whose start lies more than
1 s inside it would be taken out. It counts, per source, the words that rule
would take, loop words excluded, for a few T and N.

Prints numbers only. Nothing here prints a word of any transcript.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from real_bench import english_recall, measure_fixture

from dsj.asr import Transcription
from dsj.media import loudness
from dsj.suno import (
    LOOP_REASON,
    LOUDNESS_FRAME_S,
    NO_SPEECH_REASON,
    SILENCE_EDGE_S,
    _without_silence,
    is_loop,
    silences,
)

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "scratch" / "real_bench" / "runs"
FIXTURE = REPO / "scratch" / "urdu_cs"
RATE = 16000
FRAME_S = 0.1
FRAME = int(RATE * FRAME_S)
PCTS = (0.1, 1.0, 5.0, 50.0)
PAD_S = 1.0
GRID = ((-50.0, 5.0), (-55.0, 3.0), (-55.0, 5.0), (-55.0, 10.0))
NAMES = (
    "recording-20260920-101117",
    "recording-20260920-094234",
    "recording-20260920-162033",
    "recording-20260922-171500",
    "recording-20260922-153458",
)


def frame_power(audio: Path) -> np.ndarray:
    """Mean square of every 0.1 s frame of `audio`, mono at 16 kHz."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    n = len(samples) // FRAME
    return np.mean(samples[: n * FRAME].reshape(n, FRAME) ** 2, axis=1)


def db(power: np.ndarray | float) -> np.ndarray:
    return 10 * np.log10(np.maximum(power, 1e-18))


def word_spans(payload: dict[str, Any]) -> list[tuple[float, float]]:
    """(start, end) of every word not in a loop sentence or an `unclear` span."""
    unclear = [(float(u["start"]), float(u["end"])) for u in payload.get("unclear") or []]
    spans: list[tuple[float, float]] = []
    for s in payload["sentences"]:
        if is_loop(str(s.get("text") or "")):
            continue
        tokens = s.get("tokens") or []
        for i, t in enumerate(tokens):
            start = float(t["t"])
            if any(a <= start <= b for a, b in unclear):
                continue
            end = t.get("e")
            if end is None:
                end = float(tokens[i + 1]["t"]) if i + 1 < len(tokens) else start + 1.0
            end = min(float(end), start + 1.0)
            spans.append((start, end))
    return spans


def word_levels(power: np.ndarray, spans: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """RMS dB and loudest-frame dB of each span."""
    rms, peak = [], []
    for start, end in spans:
        a = int(start / FRAME_S)
        b = max(a + 1, int(np.ceil(end / FRAME_S)))
        frames = power[a:b]
        if len(frames) == 0:
            continue
        rms.append(float(db(np.mean(frames))))
        peak.append(float(db(np.max(frames))))
    return np.array(rms), np.array(peak)


def near_levels(power: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
    """Loudest frame within PAD_S of each span's start, either side."""
    out = []
    for start, _ in spans:
        a = max(0, int((start - PAD_S) / FRAME_S))
        b = int(np.ceil((start + PAD_S) / FRAME_S))
        frames = power[a:b]
        if len(frames):
            out.append(float(db(np.max(frames))))
    return np.array(out)


def quiet_runs(power: np.ndarray, threshold_db: float, min_s: float) -> list[tuple[float, float]]:
    """(start, end) in seconds of every run of frames below `threshold_db` lasting `min_s` or more."""
    quiet = np.concatenate([[False], db(power) < threshold_db, [False]])
    edges = np.flatnonzero(np.diff(quiet.astype(np.int8)))
    return [(a * FRAME_S, b * FRAME_S) for a, b in zip(edges[::2], edges[1::2], strict=True)
            if (b - a) * FRAME_S >= min_s - 1e-9]


def taken(spans: list[tuple[float, float]], runs: list[tuple[float, float]]) -> int:
    return sum(1 for s, _ in spans if any(a + PAD_S <= s < b - PAD_S for a, b in runs))


def pct_row(label: str, n_transcripts: int, rms: np.ndarray, peak: np.ndarray) -> str:
    cells = " | ".join(f"{np.percentile(rms, p):.1f}" for p in PCTS)
    peaks = " | ".join(f"{np.percentile(peak, p):.1f}" for p in PCTS[:3])
    return f"| {label} | {n_transcripts} | {len(rms)} | {cells} | {rms.min():.1f} | {peaks} | {peak.min():.1f} |"


def audio_of(root: Path, name: str) -> Path:
    for suffix in (".m4a", ".mp3"):
        if (root / f"{name}{suffix}").exists():
            return root / f"{name}{suffix}"
    sys.exit(f"{name}: no audio in {root}")


def measure(root: Path) -> None:

    truth = json.loads((FIXTURE / "ground_truth.json").read_text())
    clips = [(g["start"], g["end"]) for g in truth["segments"] if g["kind"] == "clip"]
    gaps = [(g["start"], g["end"]) for g in truth["segments"] if g["kind"] == "gap"]
    fixture_power = frame_power(FIXTURE / "podcast.wav")
    transcripts = sorted(RUNS.glob("*/podcast.json"))
    sources = [(
        "fixture, words in speech clips", fixture_power, len(transcripts),
        [[span for span in word_spans(json.loads(path.read_text())) if any(a <= span[0] < b for a, b in clips)]
         for path in transcripts],
    )]
    for name in NAMES:
        paths = [*sorted(RUNS.glob(f"*/{name}.json")), root / "transcripts" / f"{name}.json"]
        sources.append((name.removeprefix("recording-"), frame_power(audio_of(root, name)), len(paths),
                        [word_spans(json.loads(path.read_text())) for path in paths]))

    print("| source | transcripts | words | 0.1% | 1% | 5% | median | quietest | near 0.1% | near 1% | near 5% | quietest near |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    all_rms, all_near = [], []
    for label, power, n, per_transcript in sources:
        spans = [span for spans in per_transcript for span in spans]
        rms, _ = word_levels(power, spans)
        near = near_levels(power, spans)
        all_rms.append(rms)
        all_near.append(near)
        print(pct_row(label, n, rms, near))
    print(pct_row("all", sum(n for _, _, n, _ in sources), np.concatenate(all_rms), np.concatenate(all_near)))

    print()
    print("| fixture gap | s | RMS dB | loudest 0.1 s frame | quietest frame |")
    print("|---|---:|---:|---:|---:|")
    for a, b in gaps:
        frames = fixture_power[int(np.ceil(a / FRAME_S)) : int(b / FRAME_S)]
        print(f"| {a:.1f} to {b:.1f} | {b - a:.0f} | {float(db(np.mean(frames))):.1f} "
              f"| {float(db(np.max(frames))):.1f} | {float(db(np.min(frames))):.1f} |")
    for threshold in (-45.0, -50.0, -55.0):
        longest = max(
            (b - a for c0, c1 in clips
             for a, b in quiet_runs(fixture_power[int(np.ceil(c0 / FRAME_S)) : int(c1 / FRAME_S)], threshold, 0.0)),
            default=0.0,
        )
        print(f"\nfixture speech clips: longest run of frames below {threshold:.0f} dB: {longest:.1f} s", end="")
    print("\n")

    header = " | ".join(f"T {t:.0f}, N {n:.0f}: s · words · most in one" for t, n in GRID)
    print(f"| source | {header} |")
    print("|---|" + "---:|" * len(GRID))
    for label, power, _, per_transcript in sources:
        cells = []
        for threshold, min_s in GRID:
            runs = quiet_runs(power, threshold, min_s)
            counts = [taken(spans, runs) for spans in per_transcript]
            cells.append(f"{sum(b - a for a, b in runs):.0f} · {sum(counts)} · {max(counts)}")
        print(f"| {label} | " + " | ".join(cells) + " |")


def clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def applied(payload: dict[str, Any], stretches: list[tuple[float, float]]) -> tuple[dict[str, Any], list[float], int]:
    """`payload` as dsj would now write it, the start of every word taken, and loop words relabelled.

    Runs _without_silence on the sentences exactly as transcribe() does. A
    transcript written since #140 has already moved its loops into `unclear`
    without their words, so the product's order (silence first) cannot be
    replayed on them: such a loop whose start lies inside a stretch's interior
    is relabelled no speech here, and counted apart.
    """
    sentences = payload["sentences"]
    before = Counter((t["t"], t["w"]) for s in sentences for t in s.get("tokens") or [])
    text = "".join(str(s.get("text") or "") for s in sentences).strip()
    result, no_speech = _without_silence(Transcription(text=text, sentences=sentences), stretches)
    after = Counter((t["t"], t["w"]) for s in result.sentences for t in s.get("tokens") or [])
    gone = sorted(t for (t, _), n in (before - after).items() for _ in range(n))
    unclear = []
    relabelled = 0
    for u in payload.get("unclear") or []:
        inside = any(a + SILENCE_EDGE_S <= u["start"] < b - SILENCE_EDGE_S for a, b in stretches)
        if u["reason"] == LOOP_REASON and inside:
            relabelled += int(u["words"])
            u = u | {"reason": NO_SPEECH_REASON}
        unclear.append(u)
    new = payload | {"text": result.text, "sentences": result.sentences,
                     "unclear": sorted(unclear + no_speech, key=lambda u: u["start"])}
    return new, gone, relabelled


def apply(root: Path) -> None:
    truth = json.loads((FIXTURE / "ground_truth.json").read_text())
    gaps = [(g["start"], g["end"]) for g in truth["segments"] if g["kind"] == "gap"]
    stretches = silences(loudness(FIXTURE / "podcast.wav", LOUDNESS_FRAME_S))
    print(f"fixture silences: {[(round(a, 1), round(b, 1)) for a, b in stretches]}\n")
    print("| fixture transcript | words in gaps, 10 · 30 · 60 s, before | after | words taken in gaps | taken elsewhere | loop words relabelled | English recall before | after |")
    print("|---|---|---|---:|---:|---:|---:|---:|")
    paths = [*sorted(RUNS.glob("*/podcast.json")), FIXTURE / "roman.json"]
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            payload = json.loads(path.read_text())
            new, gone, relabelled = applied(payload, stretches)
            out = Path(tmp) / "podcast.json"
            out.write_text(json.dumps(new))
            before, after = measure_fixture(path, None).gap_words, measure_fixture(out, None).gap_words
            in_gaps = sum(1 for t in gone if any(a <= t < b for a, b in gaps))
            print(f"| {path.parent.name}/{path.name} | {' · '.join(map(str, before))} | {' · '.join(map(str, after))} "
                  f"| {in_gaps} | {len(gone) - in_gaps} | {relabelled} "
                  f"| {english_recall(payload['sentences']):.1f} | {english_recall(new['sentences']):.1f} |")

    print()
    print("| owner's transcript | silences | words taken | where | loudest frame under a taken word | loop words relabelled | words left |")
    print("|---|---|---:|---|---:|---:|---:|")
    for name in NAMES:
        audio = audio_of(root, name)
        frame_db = loudness(audio, LOUDNESS_FRAME_S)
        stretches = silences(frame_db)
        span = f"{len(stretches)}, {sum(b - a for a, b in stretches):.0f} s"
        for path in [*sorted(RUNS.glob(f"*/{name}.json")), root / "transcripts" / f"{name}.json"]:
            payload = json.loads(path.read_text())
            new, gone, relabelled = applied(payload, stretches)
            where = f"{clock(gone[0])} to {clock(gone[-1])}" if gone else "-"
            loudest = max((float(frame_db[int(t / LOUDNESS_FRAME_S)]) for t in gone), default=None)
            left = sum(len(s.get("tokens") or []) for s in new["sentences"])
            print(f"| {name.removeprefix('recording-')} {path.parent.name} | {span} | {len(gone)} | {where} "
                  f"| {'-' if loudest is None else f'{loudest:.1f}'} | {relabelled} | {left} |")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("measure", "apply"))
    args = parser.parse_args(argv)
    folder = os.environ.get("DSJ_REAL_AUDIO")
    if not folder:
        sys.exit("set DSJ_REAL_AUDIO; see the docstring")
    root = Path(folder).expanduser()
    measure(root) if args.command == "measure" else apply(root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
