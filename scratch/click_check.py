#!/usr/bin/env python3
"""Measure a `dsj hatao` render for clicks at its mute edges and clipped neighbours (#216).

A click is a step in the waveform, so each edge where the render's silence
starts or stops is measured two ways, in a 10 ms window centred on it:

- jump: the largest sample-to-sample difference, as a fraction of full scale
- hf: the energy above 4 kHz, in dB (Hann window, sum of |FFT|^2 above 4 kHz)

and the same two numbers are taken at 200 random points of audio the render
did not touch (seeded, so a rerun picks the same points). An edge outside the
reference range on either number is flagged for the owner to listen to. Each
edge also gets `dhf`: its hf in the render minus hf in the same window of the
input, so a cut that adds high-frequency energy the sound did not have reads
above 0 dB (`flagged_local` past LOCAL_DB), and `step`: the input's level at the edge, which a hard cut drops
to 0 in one sample.

The edges are where the render actually differs from its input, not where the
log asks for them: ffmpeg mutes in 5 ms frames (MUTE_FRAME_S in dsj/media.py).
So this needs a lossless render, a WAV in and a WAV out.

Clipped neighbours: for each muted span, the transcript's word before and the
word after the muted words, and how much of each (seconds, and share of its
length) lies inside the changed stretch, and how loud the input is over that
part against the whole word: within LOUD_DB of it is speech, not a pause.

Prints numbers and timestamps, never transcript text, so it can be pointed at
the owner's recordings.

    # mute N randomly chosen words (each said once), render with dsj hatao, measure
    uv run python scratch/click_check.py run --name clip45 \\
        --media scratch/clip45.wav --transcript /tmp/hatao/clip45.json --pick 12 \\
        --word basically --word trickiest --word anyhow

    # measure a render that already exists
    uv run python scratch/click_check.py measure --original in.wav --render out.wav \\
        --log out.bleeps.json --transcript in.json

`run` copies the media into scratch/click_check/<name>/ and renders the copy,
so the input is never written to; words.toml, the render, its bleep log and
report.json land there too.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from dsj import hatao

WINDOW_S = 0.010
HF_CUT_HZ = 4000.0
REFERENCE_POINTS = 200
# A reference point is at least this far from any change the render made, so its
# 10 ms window sees only untouched audio.
REFERENCE_CLEAR_S = 0.05
# Where the render's change is searched for around each logged span: ffmpeg's
# 5 ms frames move an edge by at most one frame.
SEARCH_S = 0.05
SEED = 216
# A neighbour's muted part within this many dB of the whole word's level is
# taken as speech muted rather than a pause inside the word's timing.
LOUD_DB = 6.0
# The second flag: the cut more than doubled the energy above 4 kHz that the
# input had in the same 10 ms. The reference range alone cannot flag a cut in a
# quiet passage, however sharp, while the file's loudest untouched 10 ms (a
# fricative, a laugh) is louder than it; this compares an edge with its own
# input instead.
LOCAL_DB = 3.0
OUT_ROOT = Path(__file__).resolve().parent / "click_check"


def read(path: Path) -> tuple[np.ndarray, int]:
    """Mono float samples in [-1, 1] and the rate; several channels are averaged."""
    data, rate = sf.read(str(path), dtype="float64", always_2d=True)
    return data.mean(axis=1), int(rate)


def window(x: np.ndarray, centre: int, size: int) -> np.ndarray | None:
    """The `size` samples centred on `centre`, or None at the file's ends."""
    lo = centre - size // 2
    if lo < 0 or lo + size > len(x):
        return None
    return x[lo:lo + size]


def jump(w: np.ndarray) -> float:
    return float(np.max(np.abs(np.diff(w))))


def hf_db(w: np.ndarray, rate: int) -> float:
    spectrum = np.fft.rfft(w * np.hanning(len(w)))
    freqs = np.fft.rfftfreq(len(w), 1 / rate)
    energy = float(np.sum(np.abs(spectrum[freqs >= HF_CUT_HZ]) ** 2))
    return float(10 * np.log10(energy + 1e-20))


def rms_db(x: np.ndarray) -> float | None:
    """The RMS level of `x` in dB of full scale, or None for no samples."""
    if not len(x):
        return None
    return round(float(10 * np.log10(np.mean(x**2) + 1e-20)), 1)


def changed_runs(original: np.ndarray, render: np.ndarray, spans: list[list[float]],
                 rate: int) -> list[tuple[int, int, int, int] | None]:
    """Per logged span, four sample indices: where the render starts to differ from
    its input, where its longest run of exact zeros starts and stops, and where it
    stops differing. For a hard cut the first two are the same sample, as are the
    last two; a fade puts its ramp between them. None when nothing changed
    there, which is a span over digital silence."""
    runs: list[tuple[int, int, int, int] | None] = []
    for index, (a, b) in enumerate(spans):
        # Never past halfway to the next span, which can start 40 ms later.
        before = (spans[index - 1][1] + a) / 2 if index else 0.0
        after = (b + spans[index + 1][0]) / 2 if index + 1 < len(spans) else b + SEARCH_S
        lo = max(0, int(max(a - SEARCH_S, before) * rate))
        hi = min(len(render), int(min(b + SEARCH_S, after) * rate) + 1)
        changed = np.nonzero(render[lo:hi] != original[lo:hi])[0]
        if not len(changed):
            runs.append(None)
            continue
        start, stop = lo + int(changed[0]), lo + int(changed[-1]) + 1
        zero = np.concatenate(([0], (render[start:stop] == 0).astype(np.int8), [0]))
        bounds = np.flatnonzero(np.diff(zero))
        lengths = bounds[1::2] - bounds[::2]
        if not len(lengths):
            runs.append((start, start, start, stop))
            continue
        longest = int(np.argmax(lengths))
        runs.append((start, start + int(bounds[2 * longest]),
                     start + int(bounds[2 * longest + 1]), stop))
    return runs


def words_with_times(payload: dict[str, Any], media: Path) -> list[tuple[str, float, float]]:
    """Every word of the transcript as the matcher splits it: (normalised, start, end)."""
    doc = hatao.from_transcript(payload, media)
    out = []
    for start, stop in hatao._words(doc):  # the matcher's own split of pieces into words
        pieces = [e for e in doc.content[start:stop] if isinstance(e, hatao.Item) and e.text]
        key = hatao.normalize(hatao._written(doc, start, stop))
        if key:
            out.append((key, min(p.source_start for p in pieces),
                        max(p.source_end for p in pieces)))
    return out


def measure(original_path: Path, render_path: Path, log_path: Path, transcript: Path) -> dict:
    original, rate = read(original_path)
    render, rate_r = read(render_path)
    if rate != rate_r or len(original) != len(render):
        raise SystemExit(f"{render_path} is not the same length and rate as {original_path}")
    log = json.loads(log_path.read_text(encoding="utf-8"))
    spans: list[list[float]] = log["spans"]
    size = round(WINDOW_S * rate)
    runs = changed_runs(original, render, spans, rate)

    near_change = np.zeros(len(render), dtype=bool)
    clear = round(REFERENCE_CLEAR_S * rate)
    for run in runs:
        if run is not None:
            near_change[max(0, run[0] - clear):run[3] + clear] = True
    near_change[:size] = near_change[-size:] = True
    untouched = np.nonzero(~near_change)[0]
    rng = random.Random(SEED)
    points = sorted(int(untouched[i]) for i in rng.sample(range(len(untouched)),
                                                          REFERENCE_POINTS))
    ref_windows = [window(render, p, size) for p in points]
    ref_jump = np.array([jump(w) for w in ref_windows if w is not None])
    ref_hf = np.array([hf_db(w, rate) for w in ref_windows if w is not None])
    jump_max, hf_max = float(ref_jump.max()), float(ref_hf.max())

    words = words_with_times(json.loads(transcript.read_text(encoding="utf-8")),
                             original_path)
    muted_starts = [float(m["start"]) for m in log["muted"]]

    def is_muted(t: float) -> bool:
        return any(abs(t - s) < 0.002 for s in muted_starts)

    edges: list[dict[str, Any]] = []
    neighbours: list[dict[str, Any]] = []
    half = size // 2
    for (a, b), run in zip(spans, runs, strict=True):
        if run is None:
            edges += [{"span": [a, b], "side": side, "note": "nothing changed"}
                      for side in ("start", "end")]
            continue
        start, silent_start, silent_stop, stop = run
        # The window covers the whole change at the edge and 5 ms either side of
        # it: 10 ms centred on the step for a hard cut, longer for a fade.
        for side, lo, hi, at in (("start", start - half, silent_start + half, silent_start),
                                 ("end", silent_stop - half, stop + half, silent_stop)):
            entry: dict[str, Any] = {"span": [a, b], "side": side, "at_s": round(at / rate, 4)}
            if lo < 0 or hi > len(render):
                entry["note"] = "at the file's edge"
                edges.append(entry)
                continue
            w_r, w_o = render[lo:hi], original[lo:hi]
            j, h, h_o = jump(w_r), hf_db(w_r, rate), hf_db(w_o, rate)
            entry.update({
                "window_ms": round(1000 * (hi - lo) / rate, 2),
                "jump": round(j, 5), "hf_db": round(h, 2), "dhf_db": round(h - h_o, 2),
                # The input's level at the sample beside the silence: the step a
                # hard cut makes there.
                "step": round(float(abs(original[at - 1 if side == "start" else at])), 5),
                "jump_pct": round(100 * float(np.mean(ref_jump < j)), 1),
                "hf_pct": round(100 * float(np.mean(ref_hf < h)), 1),
                "flagged": j > jump_max or h > hf_max,
                "flagged_local": h - h_o > LOCAL_DB,
            })
            edges.append(entry)
        # Every sample the log asked for is exactly 0 in the render.
        asked = render[round(a * rate):round(b * rate)]
        edges[-1]["span_silent"] = edges[-2]["span_silent"] = bool(not asked.any())
        lo_s, hi_s = start / rate, stop / rate
        inside = [i for i, (_, t, _) in enumerate(words) if lo_s - 0.01 <= t < hi_s
                  and is_muted(t)]
        if not inside:
            continue
        for side, idx in (("before", inside[0] - 1), ("after", inside[-1] + 1)):
            if not 0 <= idx < len(words):
                continue
            _, t, e = words[idx]
            covered = max(0.0, min(e, hi_s) - max(t, lo_s))
            length = max(e - t, 0.0)
            lo_c, hi_c = max(t, lo_s), min(e, hi_s)
            neighbours.append({
                "span": [a, b], "side": side, "word_start": t, "word_end": e,
                # How loud the input is over the part of the word the silence
                # covers, and over the whole word: speech muted, or a pause
                # inside the word's timing.
                "covered_db": rms_db(original[int(lo_c * rate):int(hi_c * rate)])
                if covered else None,
                "word_db": rms_db(original[int(t * rate):int(e * rate)]),
                "gap_s": round((t - words[inside[-1]][2]) if side == "after"
                               else (words[inside[0]][1] - e), 3),
                "covered_s": round(covered, 3),
                "covered_share": round(covered / length, 3) if length else None,
            })
    return {
        "original": str(original_path), "render": str(render_path), "log": str(log_path),
        "transcript": str(transcript), "rate": rate, "window_s": WINDOW_S,
        "hf_cut_hz": HF_CUT_HZ, "seed": SEED, "pad_s": log.get("pad_s"),
        "reference": {
            "points": len(ref_jump),
            "jump_min_median_max": [round(float(ref_jump.min()), 5),
                                    round(float(np.median(ref_jump)), 5), round(jump_max, 5)],
            "hf_db_min_median_max": [round(float(ref_hf.min()), 2),
                                     round(float(np.median(ref_hf)), 2), round(hf_max, 2)],
        },
        "edges": edges,
        "neighbours": neighbours,
    }


def summary(report: dict) -> str:
    edges = [e for e in report["edges"] if "jump" in e]
    flagged = [e for e in edges if e["flagged"]]
    ref = report["reference"]
    dhf = [e["dhf_db"] for e in edges]
    lines = [
        f"render {report['render']}",
        f"reference: {ref['points']} points, jump min/median/max "
        f"{ref['jump_min_median_max']}, hf dB min/median/max {ref['hf_db_min_median_max']}",
        f"edges: {len(report['edges'])}, measured {len(edges)}, flagged by the reference "
        f"range {len(flagged)}, by dhf over {LOCAL_DB:g} dB "
        f"{sum(e['flagged_local'] for e in edges)}",
        f"dhf above 0 dB at {sum(d > 0 for d in dhf)} edges, median "
        f"{float(np.median(dhf)) if dhf else float('nan'):.2f} dB, max "
        f"{max(dhf) if dhf else float('nan'):.2f} dB",
    ]
    lines += [
        f"  FLAGGED {e['side']:5} at {e['at_s']:8.3f} s, span {e['span']}: jump {e['jump']} "
        f"(above {e['jump_pct']}% of reference), hf {e['hf_db']} dB (above {e['hf_pct']}%), "
        f"dhf {e['dhf_db']} dB, step {e['step']}"
        for e in flagged
    ]
    n = report["neighbours"]
    touched = [x for x in n if x["covered_s"] > 0]
    lines.append(f"neighbouring words: {len(n)}, reached into by the silence: {len(touched)}")
    if touched:
        shares = [x["covered_share"] or 0 for x in touched]
        lines.append(
            f"  covered s median {float(np.median([x['covered_s'] for x in touched])):.3f}, "
            f"max {max(x['covered_s'] for x in touched):.3f}; share of the word median "
            f"{float(np.median(shares)):.2f}, max {max(shares):.2f}; "
            f"half or more muted {sum(s >= 0.5 for s in shares)}, whole word muted "
            f"{sum(s >= 0.999 for s in shares)}")
        loud = [x for x in touched if x["covered_db"] is not None and x["word_db"] is not None
                and x["covered_db"] >= x["word_db"] - LOUD_DB]
        lines.append(
            f"  the muted part is within {LOUD_DB:g} dB of its word's level (speech, not a "
            f"pause) at {len(loud)} of {len(touched)}")
    return "\n".join(lines)


def pick_words(payload: dict[str, Any], media: Path, count: int, given: list[str]) -> list[str]:
    """`given`, plus `count` words said once in the transcript, chosen with SEED."""
    seen: dict[str, int] = {}
    for key, _, _ in words_with_times(payload, media):
        seen[key] = seen.get(key, 0) + 1
    once = sorted(k for k, n in seen.items()
                  if n == 1 and len(k) >= 4 and k.isascii() and k.isalpha() and k not in given)
    return given + random.Random(SEED).sample(once, min(count, len(once)))


def run(args: argparse.Namespace) -> None:
    out_dir = OUT_ROOT / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    media = out_dir / f"input{args.media.suffix}"
    shutil.copyfile(args.media, media)
    payload = json.loads(args.transcript.read_text(encoding="utf-8"))
    chosen = pick_words(payload, media, args.pick, [w.lower() for w in args.word])
    words = out_dir / "words.toml"
    words.write_text(f'[[entry]]\nname = "click_check"\nroman = {json.dumps(chosen)}\n',
                     encoding="utf-8")
    render = out_dir / f"clean{args.media.suffix}"
    dsj = shutil.which("dsj")
    if dsj is None:
        raise SystemExit("no dsj on PATH; run this with `uv run`")
    cmd = [dsj, "hatao", str(media), "-t", str(args.transcript), "-o", str(render),
           "--overwrite"]
    proc = subprocess.run(cmd, env={**os.environ, hatao.WORDS_ENV: str(words)},
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"dsj hatao exited {proc.returncode}:\n{proc.stderr}")
    sys.stderr.write(proc.stderr.strip().splitlines()[-1] + "\n")
    report = measure(media, render, out_dir / "clean.bleeps.json", args.transcript)
    report["command"] = f"{hatao.WORDS_ENV}={words} " + " ".join(cmd)
    report["words_listed"] = len(chosen)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(summary(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="pick words, render with dsj hatao, measure")
    r.add_argument("--name", required=True)
    r.add_argument("--media", type=Path, required=True)
    r.add_argument("--transcript", type=Path, required=True)
    r.add_argument("--pick", type=int, default=10)
    r.add_argument("--word", action="append", default=[])
    m = sub.add_parser("measure", help="measure a render that exists")
    m.add_argument("--original", type=Path, required=True)
    m.add_argument("--render", type=Path, required=True)
    m.add_argument("--log", type=Path, required=True)
    m.add_argument("--transcript", type=Path, required=True)
    m.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.cmd == "run":
        run(args)
        return
    report = measure(args.original, args.render, args.log, args.transcript)
    if args.report:
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(summary(report))


if __name__ == "__main__":
    main()
