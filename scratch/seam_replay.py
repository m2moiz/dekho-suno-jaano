#!/usr/bin/env python3
"""Replay a seam_probe capture through the merge at different match tolerances.

Issue #53's disorder is made in the overlap merge, which pairs a token in the
earlier chunk with a token in the later one when their ids match and their
start times are within `overlap_duration / 2` -- 7.5 s under dsj's 15 s overlap.
Genuine pairs agree far more closely than that, so the obvious repair is to
tighten the tolerance. This answers whether that would be enough. It is not:
the merge splices two independently timed streams at three kinds of join and
checks none of them, so backwards steps survive every tolerance.

Needs a capture from scratch/seam_probe.py; decodes nothing itself.

    uv run python scratch/seam_probe.py scratch/meeting.wav /tmp/seam.json
    uv run python scratch/seam_replay.py /tmp/seam.json

Measured 2026-09-22 on scratch/meeting.wav, 42 chunks, parakeet-tdt-0.6b-v3:

    tolerance  7.50s ->  14394 tokens,  31 backwards steps (worst 7.00s)
    tolerance  3.00s ->  14394 tokens,  17 backwards steps (worst 2.76s)
    tolerance  1.00s ->  14389 tokens,   7 backwards steps (worst 0.52s)
    tolerance  0.25s ->  14381 tokens,   3 backwards steps (worst 0.12s)
    tolerance  0.10s ->  14382 tokens,   2 backwards steps (worst 0.04s)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dsj.alignment import AlignedToken
from dsj.suno import OVERLAP_S

TOLERANCES = (OVERLAP_S / 2, 3.0, 2.0, 1.0, 0.5, 0.25, 0.1)


def _pairs(
    overlap_a: list[AlignedToken],
    overlap_b: list[AlignedToken],
    tolerance: float,
    contiguous: bool,
) -> list[tuple[int, int]]:
    """The anchor pairs the merge would choose under `tolerance`.

    A transcription of dsj.alignment's two searches with the one constant they
    hardcode lifted out. Kept here rather than pushed into alignment.py because
    alignment.py is vendored verbatim and this is a measurement, not a change.
    """

    def match(i: int, j: int) -> bool:
        return (
            overlap_a[i].id == overlap_b[j].id
            and abs(overlap_a[i].start - overlap_b[j].start) < tolerance
        )

    if contiguous:
        best: list[tuple[int, int]] = []
        for i in range(len(overlap_a)):
            for j in range(len(overlap_b)):
                if not match(i, j):
                    continue
                run: list[tuple[int, int]] = []
                k, jj = i, j
                while k < len(overlap_a) and jj < len(overlap_b) and match(k, jj):
                    run.append((k, jj))
                    k += 1
                    jj += 1
                if len(run) > len(best):
                    best = run
        if len(best) < len(overlap_a) // 2:
            raise RuntimeError("too few pairs, as upstream would say")
        return best

    dp = [[0] * (len(overlap_b) + 1) for _ in range(len(overlap_a) + 1)]
    for i in range(1, len(overlap_a) + 1):
        for j in range(1, len(overlap_b) + 1):
            dp[i][j] = (
                dp[i - 1][j - 1] + 1 if match(i - 1, j - 1) else max(dp[i - 1][j], dp[i][j - 1])
            )
    out: list[tuple[int, int]] = []
    i, j = len(overlap_a), len(overlap_b)
    while i > 0 and j > 0:
        if match(i - 1, j - 1):
            out.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] > dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    out.reverse()
    return out


def _merge(
    a: list[AlignedToken], b: list[AlignedToken], tolerance: float, contiguous: bool
) -> list[AlignedToken]:
    if not a:
        return b
    if not b:
        return a
    a_end, b_start = a[-1].end, b[0].start
    if a_end <= b_start:
        return a + b

    overlap_a = [t for t in a if t.end > b_start - OVERLAP_S]
    overlap_b = [t for t in b if t.start < a_end + OVERLAP_S]
    cutoff = (a_end + b_start) / 2
    if len(overlap_a) < 2 or len(overlap_b) < 2:
        return [t for t in a if t.end <= cutoff] + [t for t in b if t.start >= cutoff]

    pairs = _pairs(overlap_a, overlap_b, tolerance, contiguous)
    if not pairs:
        return [t for t in a if t.end <= cutoff] + [t for t in b if t.start >= cutoff]

    offset = len(a) - len(overlap_a)
    at = [offset + p[0] for p in pairs]
    bt = [p[1] for p in pairs]
    merged = list(a[: at[0]])
    for i in range(len(pairs)):
        merged.append(a[at[i]])
        if i < len(pairs) - 1:
            gap_a = a[at[i] + 1 : at[i + 1]]
            gap_b = b[bt[i] + 1 : bt[i + 1]]
            merged.extend(gap_b if len(gap_b) > len(gap_a) else gap_a)
    merged.extend(b[bt[-1] + 1 :])
    return merged


def main(argv: list[str]) -> int:
    capture = json.loads(Path(argv[0]).read_text())
    chunks = [
        [AlignedToken(id=i, text=t, start=s, duration=d) for i, t, s, d in record["b"]]
        for record in capture
    ]

    for tolerance in TOLERANCES:
        merged: list[AlignedToken] = []
        for chunk in chunks:
            if not merged:
                merged = chunk
                continue
            try:
                merged = _merge(merged, chunk, tolerance, contiguous=True)
            except RuntimeError:
                merged = _merge(merged, chunk, tolerance, contiguous=False)
        back = [
            merged[j - 1].start - merged[j].start
            for j in range(1, len(merged))
            if merged[j].start < merged[j - 1].start
        ]
        print(
            f"tolerance {tolerance:5.2f}s -> {len(merged):6d} tokens, "
            f"{len(back):3d} backwards steps (worst {max(back, default=0.0):.2f}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
