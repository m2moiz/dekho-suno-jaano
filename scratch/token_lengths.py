#!/usr/bin/env python3
"""How long one transcript token lasts, to set the ceiling on a muted word (#212).

Prints numbers only, never transcript text, so it can be pointed at the owner's
recordings. A token's length is its `e` minus its `t`; tokens with no text are
skipped. Each group is pooled over its files.

    uv run python scratch/token_lengths.py \\
        --group fixture scratch/real_bench/runs/*/podcast.json \\
        --group owner scratch/real_bench/runs/*/recording-*.json

A file with no `e` on its tokens (written before v0.2.0), or that is not a
transcript, is named and left out.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

PERCENTILES = (50, 90, 95, 99, 99.5, 99.9)
OVER_S = (1.0, 1.5, 2.0, 3.0, 5.0)


def lengths(path: Path) -> list[float] | None:
    """Every text token's `e - t`, or None when the file is not a transcript with ends."""
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "sentences" not in payload:
        return None
    tokens = [t for s in payload["sentences"] for t in s["tokens"] if str(t.get("w", "")).strip()]
    if not tokens or not all("e" in t for t in tokens):
        return None
    return [max(float(t["e"]) - float(t["t"]), 0.0) for t in tokens]


def percentile(ordered: list[float], p: float) -> float:
    """Nearest-rank percentile of an ascending list."""
    rank = max(math.ceil(p / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def report(name: str, files: list[Path]) -> None:
    pooled: list[float] = []
    used = 0
    worst_file = 0
    for path in files:
        found = lengths(path)
        if found is None:
            print(f"  skipped (no word ends, or not a transcript): {path}")
            continue
        used += 1
        pooled.extend(found)
        worst_file = max(worst_file, sum(1 for x in found if x > 2.0))
    if not pooled:
        print(f"{name}: no tokens")
        return
    ordered = sorted(pooled)
    print(f"{name}: {used} files, {len(ordered)} tokens")
    print("  " + "  ".join(f"p{p:g}={percentile(ordered, p):.3f}" for p in PERCENTILES)
          + f"  max={ordered[-1]:.3f}")
    print("  over: " + "  ".join(
        f">{s:g}s={sum(1 for x in ordered if x > s)}" for s in OVER_S
    ) + f"  (most past 2 s in one file: {worst_file})")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--group", nargs="+", action="append", required=True,
                        metavar="NAME TRANSCRIPT",
                        help="a name, then the transcripts pooled under it")
    args = parser.parse_args()
    for name, *paths in args.group:
        report(name, [Path(p) for p in paths])


if __name__ == "__main__":
    main()
