#!/usr/bin/env python3
"""Time one speaker-labelling pass and say which numba cache it used (#186).

Runs `dsj.diarize.speaker_turns` once on a 16 kHz mono wav in this process and
prints one JSON line: wall seconds, the numba cache directory in force when
umap and pynndescent compiled, and how many speakers and turns came back. Run
it as separate processes, one at a time, so each pays its own imports and its
own compile, the way one `dsj suno` does. scratch/senko_gate.py times senko
directly; this goes through dsj, so it measures whatever cache dsj sets up.

    uv run python scratch/diarize_cache_cost.py scratch/clip360.wav
    uv run python scratch/diarize_cache_cost.py scratch/clip360.wav --shared-cache

The wall time covers the whole call: senko's import, the CoreML model load,
the clustering warmup where umap compiles, and the diarization itself.

`--shared-cache` is the comparison: dsj's private cache switched off, so umap
and pynndescent load what earlier processes compiled. It imports numba before
senko, the order a whisper run has (mlx_whisper imports numba), which puts the
cache in site-packages' __pycache__. The other order, senko first, uses
~/.cache/senko/numba_cache, and on 2026-10-02 that one crashed in five of five
runs (#186), so it has no wall time to compare.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    wav = Path(sys.argv[1])
    if "--shared-cache" in sys.argv[2:]:
        import numba  # noqa: F401  # pyright: ignore[reportUnusedImport]  # first, as on the whisper path

        import dsj.diarize

        dsj.diarize._use_private_numba_cache = lambda: None  # pyright: ignore[reportPrivateUsage]
    from dsj.diarize import speaker_turns

    started = time.monotonic()
    result = speaker_turns(wav)
    wall_s = time.monotonic() - started

    from numba.core import config

    print(
        json.dumps(
            {
                "wall_s": round(wall_s, 1),
                "numba_cache_dir": vars(config)["CACHE_DIR"],
                "speakers": len(result.labels),
                "turns": len(result.turns),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
