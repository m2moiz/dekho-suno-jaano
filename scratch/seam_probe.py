#!/usr/bin/env python3
"""Capture the chunk loop's own intermediate state, to locate issue #53.

The final transcript shows sentences running backwards at chunk seams. This
runs the real engine over real audio and records, per chunk, the tokens the
engine produced and the merged list the stitch returned, so the step that
first breaks monotonicity can be named instead of guessed at.

    uv run python scratch/seam_probe.py scratch/meeting.wav /tmp/seam.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dsj import parakeet
from dsj.alignment import (
    AlignedToken,
    merge_longest_common_subsequence,
    merge_longest_contiguous,
)
from dsj.chunking import chunk_starts
from dsj.suno import CHUNK_S, OVERLAP_S


def _dump(tokens: list[AlignedToken]) -> list[list[object]]:
    return [[t.id, t.text, t.start, t.duration] for t in tokens]


def main(argv: list[str]) -> int:
    audio, out = Path(argv[0]), Path(argv[1])
    engine = parakeet.load(parakeet.DEFAULT_MODEL)
    data = engine.load_audio(audio)
    rate = engine.sample_rate

    chunk_samples = int(CHUNK_S * rate)
    overlap_samples = int(OVERLAP_S * rate)
    starts = chunk_starts(len(data), chunk_samples, overlap_samples)

    record: list[dict[str, object]] = []
    all_tokens: list[AlignedToken] = []
    for i, start in enumerate(starts):
        end = min(start + chunk_samples, len(data))
        if end - start < engine.min_chunk_samples:
            break
        offset = start / rate
        chunk_tokens = [
            AlignedToken(
                id=t.id,
                text=t.text,
                start=t.start + offset,
                duration=t.duration,
                confidence=t.confidence,
            )
            for t in engine.decode(data[start:end])
        ]
        which = "first"
        before = all_tokens
        if all_tokens:
            try:
                all_tokens = merge_longest_contiguous(
                    all_tokens, chunk_tokens, overlap_duration=OVERLAP_S
                )
                which = "contiguous"
            except RuntimeError:
                all_tokens = merge_longest_common_subsequence(
                    all_tokens, chunk_tokens, overlap_duration=OVERLAP_S
                )
                which = "lcs"
        else:
            all_tokens = chunk_tokens

        bad = [
            j
            for j in range(1, len(all_tokens))
            if all_tokens[j].start < all_tokens[j - 1].start
        ]
        record.append(
            {
                "i": i,
                "start_s": offset,
                "merge": which,
                "a_len": len(before),
                "b_len": len(chunk_tokens),
                "merged_len": len(all_tokens),
                "inversions": bad,
                "a": _dump(before),
                "b": _dump(chunk_tokens),
                "merged": _dump(all_tokens),
            }
        )
        print(
            f"chunk {i:3d} @{offset:8.1f}s via {which:10s} "
            f"a={len(before):6d} b={len(chunk_tokens):4d} -> {len(all_tokens):6d} "
            f"inversions={len(bad)}",
            flush=True,
        )

    out.write_text(json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
