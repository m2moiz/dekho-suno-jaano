#!/usr/bin/env python3
"""What Silero costs and what speech it would throw away, before any whisper run (#236).

    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/vad_recall.py

For each reference set, with dsj.whisper's VAD settings as they stand:

- wall time of the detector pass alone (dsj.whisper._speech), audio already loaded;
- spans, speech seconds, and the clips `speech_segments` would hand whisper;
- recall, two ways, because no reference here has word times, only clip or
  segment times:
  - `spread`: each reference segment's words spread evenly over its span, and
    counted lost when that time falls outside every padded speech span. An
    upper bound: a clip's own lead-in and trailing silence gets words too.
  - `aligned`: the reference words an earlier run (#184) got right, timed by
    the middle of that run's word, counted lost when outside every padded
    span. Covers only words the run matched. Timed by the word's start
    instead (`by start`), whisper's habit of starting a word in the pause
    before it (#222) counts words as lost whose middle the detector kept:
    on 5 Oct 2026 all 56 such words on `earnings` started 0.0 to 0.3 s
    before the next span and ended inside it.
  - `least covered`: the smallest share of any reference segment's span that
    lies inside speech spans, so a segment the detector dropped whole shows.
  Each also against the clips (spans plus the pauses merged into them), which
  is what whisper is actually handed.

Nothing is written but this script's output.
"""

from __future__ import annotations

import bisect
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import score  # noqa: E402  # scratch/accuracy/score.py, beside this file
from run import SETS  # noqa: E402

from dsj import whisper  # noqa: E402

# The run of each set with the lowest WER on #184, whose word times stand in for the reference's.
TIMED_BY = {"podcast": "roman30-r1", "urdu": "ur-r1", "earnings": "plain-r1"}


def outside(t: float, spans: list[tuple[float, float]], starts: list[float]) -> bool:
    i = bisect.bisect_right(starts, t) - 1
    return i < 0 or t >= spans[i][1]


def word_ends(sentences: list[dict[str, Any]]) -> dict[float, float]:
    """Each transcript word's end, keyed by its start, grouped as score.transcript_words groups."""
    out: dict[float, float] = {}
    last: float | None = None
    for sentence in sentences:
        for k, token in enumerate(sentence["tokens"]):
            if k == 0 or re.match(r"\s", token["w"]) or last is None:
                last = round(float(token["t"]), 3)
            out[last] = float(token["e"])
    return out


def main() -> int:
    from mlx_whisper.audio import load_audio

    print(f"VAD settings: threshold {whisper.VAD_THRESHOLD}, pad {whisper.VAD_PAD_MS} ms, "
          f"min silence {whisper.VAD_MIN_SILENCE_MS} ms, min speech {whisper.VAD_MIN_SPEECH_MS} ms, "
          f"max clip {whisper.VAD_MAX_S} s")
    print("| set | audio s | VAD wall s | spans | speech s | clips | clip s | ref words | "
          "spread lost (spans) | spread lost (clips) | aligned words | aligned lost (spans) | "
          "aligned lost (clips) | by start (spans) | least covered |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, run in TIMED_BY.items():
        data = load_audio(str(SETS[name]))
        audio_s = len(data) / whisper.SAMPLE_RATE
        started = time.monotonic()
        spans, probs = whisper._speech(data)
        wall = time.monotonic() - started
        clips = whisper.speech_segments(spans, whisper.VAD_MAX_S, probs, whisper.VAD_FRAME_S)
        span_starts = [a for a, _ in spans]
        clip_starts = [a for a, _ in clips]

        truth = score.load(score.TRUTHS[name])
        spread: list[float] = []
        for seg in truth["segments"]:
            if "ground_truth" not in seg:
                continue
            words = score.pieces(seg["ground_truth"])
            step = (seg["end"] - seg["start"]) / max(1, len(words))
            spread += [seg["start"] + (k + 0.5) * step for k in range(len(words))]

        ref = score.reference_words(truth)
        doc = score.load(score.RUNS / name / f"{run}.json")
        hyp = score.transcript_words(doc["sentences"])
        s = score.score([w.text for w in hyp], ref)
        ends = word_ends(doc["sentences"])
        right = [hyp[a].t for a, b in s.pairs if a is not None and b is not None and s.correct_hyp[a]]
        aligned = [(t + ends[round(t, 3)]) / 2 for t in right]
        covered = min(
            sum(max(0.0, min(b, g["end"]) - max(a, g["start"])) for a, b in spans) / (g["end"] - g["start"])
            for g in truth["segments"] if "ground_truth" in g and g["end"] > g["start"]
        )

        def lost(times: list[float], cut: list[tuple[float, float]], starts: list[float]) -> str:
            n = sum(1 for t in times if outside(t, cut, starts))
            return f"{n} ({n / max(1, len(times)):.2%})"

        print(f"| {name} | {audio_s:.0f} | {wall:.1f} | {len(spans)} | "
              f"{sum(b - a for a, b in spans):.0f} | {len(clips)} | {sum(b - a for a, b in clips):.0f} | "
              f"{len(spread)} | {lost(spread, spans, span_starts)} | {lost(spread, clips, clip_starts)} | "
              f"{len(aligned)} (from {run}) | {lost(aligned, spans, span_starts)} | "
              f"{lost(aligned, clips, clip_starts)} | {lost(right, spans, span_starts)} | {covered:.0%} |",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
