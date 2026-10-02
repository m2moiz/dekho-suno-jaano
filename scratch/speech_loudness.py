#!/usr/bin/env python3
"""How loud is real speech, and how loud is the fixture's silence (#181)?

Measures, without running a model, the loudness of the audio under every word
of the transcripts already on disk, so a silence threshold can be placed below
real speech with a measured margin, or shown not to exist.

    export DSJ_REAL_AUDIO="$HOME/Library/CloudStorage/GoogleDrive-m.moiz1995@gmail.com/My Drive/Hi-Q Recordings"
    uv run python scratch/speech_loudness.py measure
    uv run python scratch/speech_loudness.py apply
    uv run python scratch/speech_loudness.py vad-run   # #189: senko's VAD alone, cached
    uv run python scratch/speech_loudness.py vad       # #189: VAD against the loudness rule

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


# ---------------------------------------------------------------------------
# #189: does senko's speech detector find speech better than loudness?
#
# senko runs voice activity detection before it labels speakers (pyannote
# segmentation via CoreML on a Mac) and returns it as `"vad"`, (start, end)
# speech segments; dsj reads only `merged_segments`. `vad-run` runs senko's VAD
# backend alone (LocalSegmentationVADCoreML, the object Diarizer._perform_vad
# calls), not the whole diarizer: checked on the fixture to return exactly the
# diarizer's `"vad"` list. Segments go to scratch/real_bench/vad/<name>.json,
# which git ignores; they are times only. `vad` prints the tables from them.
#
# The VAD rule measured, by analogy with #181's: a stretch outside every VAD
# segment lasting N s or more is no speech, and a word whose start lies more
# than E s inside it is taken out.

VAD_CACHE = REPO / "scratch" / "real_bench" / "vad"
VAD_SHIFT_S = 1.0
VAD_GRID = ((1.0, 0.5), (2.0, 0.5), (2.0, 1.0), (3.0, 1.0), (5.0, 1.0))
# The passage of 094234 the owner listened to on 2026-10-02 (#189): speech only
# in its first 3 to 4 s and last 5 s, phone and keyboard sounds between.
HEARD = ("recording-20260920-094234", 1191.0, 1534.0)
# Transcripts per owner file: the brief's for #189, plus 162033's anchored
# transcript, and 094234's two runs from before #181 so the words the loudness
# rule takes are still in their sentences.
VAD_RUNS = {
    "recording-20260920-101117": ["r183b-e2e-v022-r1", "r183b-s139-a120-r1", "e2e-v022-r1"],
    "recording-20260920-094234": ["r183b-d100-a120-r1", "r183b-d100-a120-r2", "d100-a120-r1", "d100-a120-r2"],
    "recording-20260920-162033": ["d100-a120-r1"],
    "recording-20260922-171500": ["r183b-d100-a120-r1"],
    "recording-20260922-153458": ["s139-en-r1"],
}

Span = tuple[float, float]


def vad_run(root: Path) -> None:
    """VAD alone on the fixture and the owner's five files, segments and wall times to VAD_CACHE."""
    import time

    import soundfile

    from dsj.diarize import _import_senko

    t0 = time.monotonic()
    senko = _import_senko()
    from senko.vad_local_pyannote import LocalSegmentationVADCoreML

    config = senko.config
    paths = config.resolve_model_paths(None, required_fields=config.RUNTIME_PYANNOTE_COREML_MODEL_FIELDS)
    t1 = time.monotonic()
    vad = LocalSegmentationVADCoreML(
        lib_path=config.get_vad_coreml_lib_path(),
        model_path=str(paths.pyannote_segmentation_coreml_model_path),
    )
    t2 = time.monotonic()
    print(f"import senko {t1 - t0:.2f} s, load VAD model {t2 - t1:.2f} s")
    VAD_CACHE.mkdir(parents=True, exist_ok=True)
    sources = [("podcast", FIXTURE / "podcast.wav"), *((n, audio_of(root, n)) for n in VAD_RUNS)]
    with tempfile.TemporaryDirectory() as tmp:
        for name, audio in sources:
            wav = audio
            convert_s = 0.0
            if audio.suffix != ".wav":
                wav = Path(tmp) / f"{name}.wav"
                c0 = time.monotonic()
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-vn", "-ac", "1", "-ar", str(RATE),
                     "-c:a", "pcm_s16le", str(wav)],
                    check=True,
                )
                convert_s = time.monotonic() - c0
            duration = wav.stat().st_size / (2 * RATE)
            v0 = time.monotonic()
            segments = vad.process(str(wav))
            vad_s = time.monotonic() - v0
            # The same audio cut VAD_SHIFT_S earlier, times put back: a stretch
            # one run calls non-speech and the other fills is a window the
            # detector dropped, not a stretch without speech.
            samples, _ = soundfile.read(str(wav), dtype="float32")
            shifted = vad.process(samples[int(VAD_SHIFT_S * RATE):])
            (VAD_CACHE / f"{name}.json").write_text(json.dumps({
                "duration_s": duration, "vad_s": vad_s, "convert_s": convert_s,
                "segments": [[float(a), float(b)] for a, b in segments],
                "shifted": [[float(a) + VAD_SHIFT_S, float(b) + VAD_SHIFT_S] for a, b in shifted],
            }))
            print(f"{name}: {duration / 60:.1f} min, {len(segments)} segments, VAD {vad_s:.2f} s "
                  f"({vad_s / (duration / 60):.3f} s per minute), wav conversion {convert_s:.2f} s")


def vad_cached(name: str) -> dict[str, Any]:
    path = VAD_CACHE / f"{name}.json"
    if not path.exists():
        sys.exit(f"{path} missing; run `speech_loudness.py vad-run` first")
    return json.loads(path.read_text())


def outside(segments: list[Span], duration: float) -> list[Span]:
    """The complement of `segments` over [0, duration]."""
    out: list[Span] = []
    at = 0.0
    for a, b in sorted(segments):
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if at < duration:
        out.append((at, duration))
    return out


def overlap(spans: list[Span], a: float, b: float) -> float:
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)


def word_starts(payload: dict[str, Any]) -> list[float]:
    """Start of every token not in a loop sentence or an `unclear` span."""
    unclear = [(float(u["start"]), float(u["end"])) for u in payload.get("unclear") or []]
    return [
        float(t["t"])
        for s in payload["sentences"]
        if not is_loop(str(s.get("text") or ""))
        for t in s.get("tokens") or []
        if not any(a <= float(t["t"]) <= b for a, b in unclear)
    ]


def inner(stretches: list[Span], min_s: float, edge_s: float) -> list[Span]:
    return [(a + edge_s, b - edge_s) for a, b in stretches if b - a >= min_s]


def inside(t: float, spans: list[Span]) -> bool:
    return any(a <= t < b for a, b in spans)


def depth(t: float, stretches: list[Span]) -> float:
    """How far `t` lies inside one of `stretches`, 0 when in none."""
    return max((min(t - a, b - t) for a, b in stretches if a <= t < b), default=0.0)


def tenths(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def groups(times: list[float], join_s: float = 5.0) -> list[tuple[float, float, int]]:
    """Sorted times as runs no more than `join_s` apart: (first, last, count)."""
    out: list[tuple[float, float, int]] = []
    for t in sorted(times):
        if out and t - out[-1][1] <= join_s:
            a, _, n = out[-1]
            out[-1] = (a, t, n + 1)
        else:
            out.append((t, t, 1))
    return out


def peak_near(frame_db: np.ndarray, t: float) -> float:
    a = max(0, int((t - PAD_S) / LOUDNESS_FRAME_S))
    b = int(np.ceil((t + PAD_S) / LOUDNESS_FRAME_S))
    return float(np.max(frame_db[a:b]))


def span_db(frame_db: np.ndarray, a: float, b: float) -> tuple[float, float]:
    """Median and loudest 0.1 s frame of [a, b]."""
    lo = max(0, int(a / LOUDNESS_FRAME_S))
    frames = frame_db[lo: max(lo + 1, int(np.ceil(b / LOUDNESS_FRAME_S)))]
    return float(np.median(frames)), float(np.max(frames))


def vad_fixture() -> None:
    truth = json.loads((FIXTURE / "ground_truth.json").read_text())
    clips = [(float(g["start"]), float(g["end"])) for g in truth["segments"] if g["kind"] == "clip"]
    gaps = [(float(g["start"]), float(g["end"])) for g in truth["segments"] if g["kind"] == "gap"]
    vad = vad_cached("podcast")
    segments = [(a, b) for a, b in vad["segments"]]
    non = outside(segments, vad["duration_s"])
    quiet = silences(loudness(FIXTURE / "podcast.wav", LOUDNESS_FRAME_S))

    print("## Fixture: scratch/urdu_cs/podcast.wav\n")
    clip_s = sum(b - a for a, b in clips)
    missed = sum(overlap(non, a, b) for a, b in clips)
    lengths = sorted((min(y, b) - max(x, a) for a, b in clips for x, y in non if x < b and a < y), reverse=True)
    print(f"VAD: {len(segments)} segments, {sum(b - a for a, b in segments):.1f} s of speech in {vad['duration_s']:.1f} s.")
    print(f"Reference clips: {clip_s:.1f} s; outside VAD: {missed:.1f} s ({100 * missed / clip_s:.1f}%), "
          f"in {len(lengths)} runs; the five longest: {[round(v, 2) for v in lengths[:5]]} s.")
    print(f"Loudness rule (silences()): {[(round(a, 1), round(b, 1)) for a, b in quiet]}\n")
    print("| gap | s | VAD speech inside, s | non-VAD stretch covering it |")
    print("|---|---:|---:|---|")
    for a, b in gaps:
        cover = [(round(x, 2), round(y, 2)) for x, y in non if x < b and a < y]
        print(f"| {a:.1f} to {b:.1f} | {b - a:.0f} | {overlap(segments, a, b):.2f} | {cover} |")

    paths = [*sorted(RUNS.glob("*/podcast.json")), FIXTURE / "roman.json"]
    print("\nWords of every fixture transcript (loops and `unclear` left out), by where they start.\n")
    header = " | ".join(f"N {n:g}, E {e:g}: clip · gap" for n, e in VAD_GRID)
    print(f"| transcript | words in clips | in gaps | deepest clip word outside VAD, s | {header} | loudness: clip · gap |")
    print("|---|---:|---:|---:|" + "---|" * len(VAD_GRID) + "---|")
    loud = inner(quiet, 0.0, SILENCE_EDGE_S)
    for path in paths:
        starts = word_starts(json.loads(path.read_text()))
        in_clips = [t for t in starts if inside(t, clips)]
        in_gaps = [t for t in starts if inside(t, gaps)]
        deepest = max((depth(t, non) for t in in_clips), default=0.0)
        cells = []
        for n, e in VAD_GRID:
            rule = inner(non, n, e)
            cells.append(f"{sum(inside(t, rule) for t in in_clips)} · {sum(inside(t, rule) for t in in_gaps)}")
        lc = f"{sum(inside(t, loud) for t in in_clips)} · {sum(inside(t, loud) for t in in_gaps)}"
        print(f"| {path.parent.name}/{path.name} | {len(in_clips)} | {len(in_gaps)} | {deepest:.2f} | "
              + " | ".join(cells) + f" | {lc} |")


def vad_owner(root: Path) -> None:
    print("\n## The owner's five files\n")
    print("| file | min | VAD segments | VAD speech | non-VAD stretches >= 5 s | of them filled by the shifted run "
          "| loudness silences | VAD s | s per min |")
    print("|---|---:|---:|---:|---|---|---|---:|---:|")
    loud: dict[str, np.ndarray] = {}
    for name in VAD_RUNS:
        vad = vad_cached(name)
        segments = [(a, b) for a, b in vad["segments"]]
        long = [(a, b) for a, b in outside(segments, vad["duration_s"]) if b - a >= 5.0]
        shifted = [(a, b) for a, b in vad["shifted"]]
        dropped = [(a, b) for a, b in long if overlap(shifted, a, b) > (b - a) / 2]
        frame_db = loud[name] = loudness(audio_of(root, name), LOUDNESS_FRAME_S)
        quiet = silences(frame_db)
        minutes = vad["duration_s"] / 60
        print(f"| {name.removeprefix('recording-')} | {minutes:.1f} | {len(segments)} "
              f"| {sum(b - a for a, b in segments) / 60:.1f} min | {len(long)}, {sum(b - a for a, b in long):.0f} s "
              f"| {', '.join(f'{tenths(a)} to {tenths(b)}' for a, b in dropped) or '-'} "
              f"| {len(quiet)}, {sum(b - a for a, b in quiet):.0f} s | {vad['vad_s']:.2f} | {vad['vad_s'] / minutes:.3f} |")

    name, lo, hi = HEARD
    vad = vad_cached(name)
    frame_db = loud[name]
    print(f"\n### {name}, {tenths(lo)} to {tenths(hi)} (owner heard speech in the first 3 to 4 s and last 5 s only)\n")
    print("| VAD segment | s | from window start | to window end | median dB | loudest frame |")
    print("|---|---:|---:|---:|---:|---:|")
    window = [(a, b) for a, b in vad["segments"] if a < hi and lo < b]
    for a, b in window:
        med, top = span_db(frame_db, a, b)
        print(f"| {tenths(a)} to {tenths(b)} | {b - a:.2f} | {a - lo:+.1f} | {hi - b:+.1f} | {med:.1f} | {top:.1f} |")
    print(f"\nVAD speech inside the window: {overlap(window, lo, hi):.1f} s; "
          f"inside {lo + 5:.0f} to {hi - 6:.0f} (the middle the owner heard as no speech): "
          f"{overlap(window, lo + 5, hi - 6):.1f} s.")
    quiet = silences(frame_db)
    print(f"Loudness silences in the window: {[(tenths(a), tenths(b)) for a, b in quiet if a < hi and lo < b]}")

    print("\n### Words outside VAD speech, per transcript\n")
    header = " | ".join(f"N {n:g}, E {e:g}" for n, e in VAD_GRID)
    print(f"| file · run | words | {header} | N 5, E 1, two offsets | loudness rule | both (N 5, E 1 and loudness) "
          "| existing `no speech` entries: words · VAD speech inside |")
    print("|---|---:|" + "---:|" * len(VAD_GRID) + "---:|---:|---:|---|")
    detail: list[str] = []
    for name, runs in VAD_RUNS.items():
        vad = vad_cached(name)
        segments = [(a, b) for a, b in vad["segments"]]
        non = outside(segments, vad["duration_s"])
        # Speech where either run found it: the shifted run fills the windows the first dropped.
        non_two = inner(outside(segments + [(a, b) for a, b in vad["shifted"]], vad["duration_s"]), 5.0, 1.0)
        frame_db = loud[name]
        loud_rule = inner(silences(frame_db), 0.0, SILENCE_EDGE_S)
        for run in runs:
            payload = json.loads((RUNS / run / f"{name}.json").read_text())
            starts = word_starts(payload)
            cells = [sum(inside(t, inner(non, n, e)) for t in starts) for n, e in VAD_GRID]
            by_vad = [t for t in starts if inside(t, inner(non, 5.0, 1.0))]
            by_loud = [t for t in starts if inside(t, loud_rule)]
            both = sum(inside(t, loud_rule) for t in by_vad)
            ns = [u for u in payload.get("unclear") or [] if u["reason"] == NO_SPEECH_REASON]
            ns_cell = (f"{sum(int(u['words']) for u in ns)} · "
                       f"{sum(overlap(segments, u['start'], u['end']) for u in ns):.1f} of "
                       f"{sum(u['end'] - u['start'] for u in ns):.0f} s") if ns else "-"
            two = sum(inside(t, non_two) for t in starts)
            print(f"| {name[-6:]} · {run} | {len(starts)} | " + " | ".join(map(str, cells))
                  + f" | {two} | {len(by_loud)} | {both} | {ns_cell} |")
            for a, b, n in groups(by_vad):
                med, _ = span_db(frame_db, a - 1, b + 1)
                peak = max(peak_near(frame_db, t) for t in by_vad if a <= t <= b)
                stretch = next((x, y) for x, y in non if x <= a < y)
                heard = "heard window" if name == HEARD[0] and HEARD[1] <= a <= HEARD[2] else ""
                also = sum(inside(t, loud_rule) for t in by_vad if a <= t <= b)
                detail.append(
                    f"| {name[-6:]} · {run} | {tenths(a)} to {tenths(b)} | {n} | {also} "
                    f"| {tenths(stretch[0])} to {tenths(stretch[1])} ({stretch[1] - stretch[0]:.1f} s) "
                    f"| {med:.1f} | {peak:.1f} | {heard} |")
    print("\nWhere the VAD rule (N 5, E 1) takes words: runs of taken words no more than 5 s apart.\n")
    print("| file · run | words from, to | words | of them loudness also takes | non-VAD stretch "
          "| median dB around | loudest frame within 1 s of a word | |")
    print("|---|---|---:|---:|---|---:|---:|---|")
    print("\n".join(detail))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("measure", "apply", "vad-run", "vad"))
    args = parser.parse_args(argv)
    folder = os.environ.get("DSJ_REAL_AUDIO")
    if not folder:
        sys.exit("set DSJ_REAL_AUDIO; see the docstring")
    root = Path(folder).expanduser()
    if args.command == "measure":
        measure(root)
    elif args.command == "apply":
        apply(root)
    elif args.command == "vad-run":
        vad_run(root)
    else:
        vad_fixture()
        vad_owner(root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
