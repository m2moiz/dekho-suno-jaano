#!/usr/bin/env python3
"""Compare the old and the new anchored seam rule on ONE whisper decode (#190).

whisper's temperature fallback samples, so two `--roman-urdu` runs of one file
differ well away from any seam (on #148's fixture, 99 fewer words in the first
114 s, which only one window ever decodes). A before and after from two runs
therefore measures the decode as much as the rule. This makes one decode and
writes it both ways.

    uv run python scratch/seam_replay_anchored.py record MEDIA OUTDIR
    uv run python scratch/seam_replay_anchored.py replay MEDIA OUTDIR

`record` runs `dsj suno MEDIA --roman-urdu --no-diarize` in-process, exactly
as the CLI sets it up, with mlx_whisper.transcribe wrapped to save every
call's result to OUTDIR/calls.json; the transcript is OUTDIR/after-retry.json,
the real product output. `replay` hands the main-pass windows (the calls that
are not a retry) back to `transcribe()` three times: with the seam rule of
9285883 (`_anchored` from git, and no `_without_overlaps`) and the loop retry
off as OUTDIR/old.json; with the working tree's and the retry off as
OUTDIR/new.json; and with the working tree's and the retry on, as the product
runs, as OUTDIR/new-retry.json. Only that last one runs whisper, for the
retries, which are decoded for real.

Writes transcripts only, prints nothing from them: the owner's recordings are
private. Measure with scratch/transcript_invariants.py and
scratch/real_bench.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from dsj import suno
from dsj import whisper as whisper_mod
from dsj.whisper import ANCHOR_CHUNK_S, ROMAN_URDU_PROMPT

BEFORE = "9285883"


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _run(media: Path, out: Path) -> None:
    suno.transcribe(
        media,
        out,
        engine="whisper",
        language="ur",
        prompt=ROMAN_URDU_PROMPT,
        anchor_s=ANCHOR_CHUNK_S,
        diarize=False,
    )


def record(media: Path, outdir: Path) -> None:
    import mlx_whisper

    real = mlx_whisper.transcribe
    calls: list[dict[str, Any]] = []

    def recording(audio: Any, **kwargs: Any) -> dict[str, Any]:
        result = real(audio, **kwargs)
        calls.append(
            {
                "n_samples": len(audio),
                "retry": "condition_on_previous_text" in kwargs,
                "segments": _plain(result.get("segments") or []),
            }
        )
        return result

    mlx_whisper.transcribe = recording
    _run(media, outdir / "after-retry.json")
    (outdir / "calls.json").write_text(json.dumps(calls))


def replay(media: Path, outdir: Path) -> None:
    import mlx_whisper

    calls = [c for c in json.loads((outdir / "calls.json").read_text()) if not c["retry"]]
    real = mlx_whisper.transcribe
    source = subprocess.run(
        ["git", "show", f"{BEFORE}:dsj/whisper.py"], capture_output=True, text=True, check=True
    ).stdout
    old = types.ModuleType("whisper_before")
    exec(compile(source, f"{BEFORE}:dsj/whisper.py", "exec"), old.__dict__)
    new_anchored = whisper_mod._anchored  # pyright: ignore[reportPrivateUsage]
    new_overlaps = suno._without_overlaps  # pyright: ignore[reportPrivateUsage]

    for name, anchored, overlaps, retry in (
        ("old", old.__dict__["_anchored"], lambda t: t, False),
        ("new", new_anchored, new_overlaps, False),
        ("new-retry", new_anchored, new_overlaps, True),
    ):
        it = iter(calls)
        suno.RETRY_LOOPS = retry

        def replaying(
            audio: Any, it: Iterator[dict[str, Any]] = it, **kwargs: Any
        ) -> dict[str, Any]:
            if "condition_on_previous_text" in kwargs:
                return real(audio, **kwargs)
            call = next(it)
            assert call["n_samples"] == len(audio), "windows differ from the recorded run"
            return {"segments": call["segments"]}

        mlx_whisper.transcribe = replaying
        whisper_mod._anchored = anchored  # pyright: ignore[reportPrivateUsage]
        suno._without_overlaps = overlaps  # pyright: ignore[reportPrivateUsage]
        _run(media, outdir / f"{name}.json")
        assert next(it, None) is None, "not every recorded window was replayed"


def main(argv: list[str]) -> int:
    mode, media, outdir = argv[0], Path(argv[1]), Path(argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    {"record": record, "replay": replay}[mode](media, outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
