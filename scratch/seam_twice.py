#!/usr/bin/env python3
"""Count words a parakeet transcript holds twice at its chunk seams (#198).

    uv run python scratch/seam_twice.py TRANSCRIPT.json [...]

Prints numbers only, never text, so it can be pointed at the owner's
recordings too.

parakeet decodes CHUNK_S windows that overlap by OVERLAP_S and splices each
pair in the overlap (dsj/alignment.py). If a splice keeps both chunks' words
for the same seconds, the transcript says those words twice. Two measures:

1. **Echoes.** In the time-ordered word stream, a run of ECHO_MIN or more words
   that appears again, word for word (lower-cased, punctuation stripped),
   starting within ECHO_S seconds of the first. Speech repeats itself too
   ("we, we"), so echoes are counted at the seams (from a seam's start to
   SEAM_PAD_S past its overlap's end) and everywhere else, per hour of audio
   in each: if the seams carry no more than the rest, the merge is not the cause.
2. **Shared seconds.** Pairs of adjacent sentences whose time spans overlap
   with at least two words of each inside the shared seconds: two streams over
   the same audio. A transcript written since #192 (`1be4095`) splits every
   overlapping pair, so this reads 0 on it by construction; it is for the
   older transcripts on disk.

Seam positions come from dsj.chunking.chunk_starts with the CHUNK_S and
OVERLAP_S in dsj/suno.py, which every parakeet transcript here was written with.
"""

from __future__ import annotations

import json
import re
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

from dsj.suno import CHUNK_S, OVERLAP_S

ECHO_MIN = 3
ECHO_S = 4.0
SEAM_PAD_S = 2.0
WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")


def words(sentences: list[dict[str, Any]]) -> list[tuple[float, str]]:
    """(start, folded text) per word, earliest first; a word is a token opening with whitespace."""
    out: list[tuple[float, str]] = []
    for s in sentences:
        for k, token in enumerate(s["tokens"]):
            t = float(token.get("t", token.get("start", 0.0)))
            w = str(token.get("w", token.get("text", "")))
            if k == 0 or re.match(r"\s", w) or not out:
                out.append((t, w))
            else:
                out[-1] = (out[-1][0], out[-1][1] + w)
    folded = [(t, " ".join(WORD.findall(w.lower()))) for t, w in out]
    return sorted(((t, w) for t, w in folded if w), key=lambda x: x[0])


def seams(duration: float) -> list[tuple[float, float]]:
    """Each chunk overlap as (start, end) seconds, padded at the end by SEAM_PAD_S."""
    step = CHUNK_S - OVERLAP_S
    out = []
    k = 1
    while k * step < duration:
        out.append((k * step, k * step + OVERLAP_S + SEAM_PAD_S))
        k += 1
    return out


def echoes(stream: list[tuple[float, str]]) -> list[tuple[float, int]]:
    """(time of the repeat, words repeated) for each echo, never counting a word twice."""
    texts = [w for _, w in stream]
    found: list[tuple[float, int]] = []
    used = [False] * len(stream)
    for i in range(len(stream)):
        for j in range(i + 1, len(stream)):
            if stream[j][0] - stream[i][0] > ECHO_S:
                break
            n = 0
            while j + n < len(stream) and i + n < j and texts[i + n] == texts[j + n] and not used[j + n]:
                n += 1
            if n >= ECHO_MIN:
                for k in range(j, j + n):
                    used[k] = True
                found.append((stream[j][0], n))
                break
    return found


def shared(sentences: list[dict[str, Any]]) -> list[tuple[float, int]]:
    """(start of the shared seconds, words of the smaller side inside them) per overlapping pair."""
    ordered = sorted(sentences, key=lambda s: float(s["start"]))
    out = []
    for a, b in pairwise(ordered):
        lo, hi = float(b["start"]), min(float(a["end"]), float(b["end"]))
        if hi <= lo:
            continue
        inside = [sum(1 for t, _ in words([x]) if lo <= t <= hi) for x in (a, b)]
        if min(inside) >= 2:
            out.append((lo, min(inside)))
    return out


def report(path: Path) -> None:
    doc = json.loads(path.read_text())
    sentences = doc["sentences"]
    duration = max(float(s["end"]) for s in sentences)
    stream = words(sentences)
    windows = seams(duration)
    seam_s = sum(min(b, duration) - a for a, b in windows)
    rest_s = duration - seam_s

    def at_seam(t: float) -> bool:
        return any(a <= t < b for a, b in windows)

    found = echoes(stream)
    at = [n for t, n in found if at_seam(t)]
    off = [n for t, n in found if not at_seam(t)]
    pairs = shared(sentences)
    print(
        f"{path.name}: {duration / 60:.0f} min, {len(stream)} words, {len(windows)} seams "
        f"({seam_s:.0f} s in seam windows)\n"
        f"  echoes at seams: {len(at)} ({sum(at)} words, {sum(at) / seam_s * 3600:.0f} words/h of seam audio)\n"
        f"  echoes elsewhere: {len(off)} ({sum(off)} words, {sum(off) / max(rest_s, 1) * 3600:.0f} words/h)\n"
        f"  sentence pairs sharing seconds: {len(pairs)} ({sum(1 for t, _ in pairs if at_seam(t))} at seams), "
        f"{sum(n for _, n in pairs)} words twice, {sum(n for _, n in pairs) / duration * 3600:.0f} per hour"
    )


def main(argv: list[str]) -> int:
    for arg in argv:
        report(Path(arg))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
