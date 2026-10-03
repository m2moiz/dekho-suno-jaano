#!/usr/bin/env python3
"""Measure the cutoff for a loop split across sentences (#223), on transcripts on disk.

`is_loop` (dsj/suno.py) judges one sentence at a time, so a loop whisper split
into one-word sentences, the same word 13 times over (#152's mixed.wav), was
never caught. dsj.suno._loop_runs catches LOOP_RUN_MIN or more consecutive
sentences with the same words whose words together is_loop calls a loop. This
prints what it would take out at each cutoff, so the constant rests on a
measurement:

    uv run python scratch/loop_runs.py [extra.json ...]

Over every payload under scratch/real_bench/runs/ (#148's public fixture and
the owner's recordings) and any extra files given, at cutoffs 3 to 7: the runs
caught, counted once per recording, start and length (several transcripts are
re-processings of one decode), and how many of those also repeat at least the
cutoff times within 5 s of the same seconds in some other decode of the same
recording. A loop is not a fixed property of the audio (#100: two identical
runs gave 86 and 343 loop seconds), so a run no other decode repeats is a loop,
not a speaker repeating themselves; one that is repeated elsewhere is listed
with its recording and start for a person to listen to.

Then the same counts over #148's hand-checked reference of the fixture
(scratch/urdu_cs/ground_truth.json), split into sentences at . ! ? and the
Urdu full stop: what real speech holds. Counts and timestamps only, never text.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from dsj import suno

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "scratch" / "real_bench" / "runs"
REFERENCE = REPO / "scratch" / "urdu_cs" / "ground_truth.json"
NEAR_S = 5.0


def payloads(extra: list[Path]) -> list[tuple[Path, list[dict[str, Any]]]]:
    out: list[tuple[Path, list[dict[str, Any]]]] = []
    for path in sorted(RUNS.rglob("*.json")) + extra:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("sentences"), list):
            out.append((path, data["sentences"]))
    return out


def recording(path: Path) -> str:
    """Which audio a transcript is of: its stem when that names a recording."""
    if path.stem.startswith("recording-") or path.stem == "podcast":
        return path.stem
    return f"{path.parent.name}/{path.stem}"


def words(text: str) -> tuple[str, ...]:
    return tuple(w.lower() for w in suno._WORD.findall(text))  # pyright: ignore[reportPrivateUsage]


def repeats(sentences: list[dict[str, Any]], phrase: tuple[str, ...], lo: float, hi: float) -> int:
    """How many times `phrase` is written back to back, at most, among the words in [lo, hi]."""
    said = [
        w
        for s in sentences
        for t in s["tokens"]
        if lo <= float(t["t"]) <= hi
        for w in words(str(t["w"]))
    ]
    best = run = i = 0
    n = len(phrase)
    while i + n <= len(said):
        if tuple(said[i : i + n]) == phrase:
            run += 1
            best = max(best, run)
            i += n
        else:
            run = 0
            i += 1
    return best


def reference() -> None:
    if not REFERENCE.exists():
        print(f"no reference at {REFERENCE}; `just urdu-fixture` builds it")
        return
    text = " ".join(
        str(s.get("ground_truth") or "")
        for s in json.loads(REFERENCE.read_text(encoding="utf-8"))["segments"]
    )
    said = list(words(text))
    sentences = [w for w in (words(x) for x in re.split("[.!?\u06d4]+", text)) if w]
    back_to_back = longest = 1
    for a, b in pairwise(said):
        back_to_back = back_to_back + 1 if a == b else 1
        longest = max(longest, back_to_back)
    same = sum(1 for a, b in pairwise(sentences) if a == b)
    print(
        f"reference: {len(said)} words, {len(sentences)} sentences; one word back to back "
        f"at most {longest} times; consecutive identical sentences: {same}"
    )


def main(argv: list[str]) -> None:
    shipped = suno.LOOP_RUN_MIN
    found = payloads([Path(a) for a in argv])
    print(f"{len(found)} transcripts, {sum(len(s) for _, s in found)} sentences")
    by_recording: dict[str, list[tuple[Path, list[dict[str, Any]]]]] = defaultdict(list)
    for path, sentences in found:
        by_recording[recording(path)].append((path, sentences))
    print(
        "| cutoff | runs caught | distinct | transcripts with one | distinct runs "
        "repeated as often in another decode |"
    )
    print("|---|---|---|---|---|")
    listed: list[tuple[str, int, int, int, float]] = []
    for cutoff in range(3, 8):
        suno.LOOP_RUN_MIN = cutoff
        caught = 0
        files: set[Path] = set()
        distinct: dict[tuple[str, int, int, tuple[str, ...]], tuple[bool, float]] = {}
        for name, group in by_recording.items():
            for path, sentences in group:
                for first, last in suno._loop_runs(sentences):  # pyright: ignore[reportPrivateUsage]
                    caught += 1
                    files.add(path)
                    run = sentences[first : last + 1]
                    phrase = words(str(run[0]["text"]))
                    size = sum(1 for s in run if words(str(s["text"])))
                    key = (name, round(float(run[0]["start"])), size, phrase)
                    if key in distinct:
                        continue
                    lo = float(run[0]["start"]) - NEAR_S
                    hi = float(run[-1]["end"]) + NEAR_S
                    seen = any(
                        repeats(other, phrase, lo, hi) >= cutoff for p, other in group if p != path
                    )
                    distinct[key] = (seen, float(run[-1]["end"]) - float(run[0]["start"]))
        elsewhere = [(k, v[1]) for k, v in distinct.items() if v[0]]
        print(
            f"| {cutoff} | {caught} | {len(distinct)} | {len(files)} of {len(found)} | "
            f"{len(elsewhere)} |"
        )
        if cutoff == shipped:
            listed = sorted((k[0], k[1], k[2], len(k[3]), round(d, 1)) for k, d in elsewhere)
    print()
    print(
        f"At the shipped cutoff, {shipped}, repeated in another decode "
        "(recording, start s, sentences, words each, seconds):"
    )
    for row in listed:
        print(" ", *row)
    sizes: Counter[int] = Counter(r[2] for r in listed)
    print(f"  sentences per run: {dict(sorted(sizes.items()))}")
    print()
    reference()


if __name__ == "__main__":
    main(sys.argv[1:])
