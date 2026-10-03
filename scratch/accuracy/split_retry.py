#!/usr/bin/env python3
"""Replay #183's loop retry on the split loops (#223) of transcripts already on disk.

    uv run python scratch/accuracy/split_retry.py

For each whisper run under scratch/accuracy/runs/ whose `.preretry.json` holds
a split loop (dsj.suno._loop_runs), the split loop's sentences are put back
into the finished transcript (which already holds every single-sentence retry
the run made, and none of the loops that failed it), and the transcript goes
through the steps dsj runs after a whisper pass: `_retried` with the real
`redecoder`, `_without_loops`, `_without_overlaps`. Only split loops are loops
in that input, so only they are decoded: one whisper model in this process,
spans one at a time. This needs the `_retried` that reads a split loop as one
span; on code before it, nothing is decoded and the output equals the input.

The result goes to `<name>.splitretry.json` beside the run, never over an
existing file, and is scored with `score.py one`. Its `unclear` is the run's,
less the split loops the retry read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from dsj import media as media_mod
from dsj.asr import Transcription
from dsj.suno import (
    LOUDNESS_FRAME_S,
    Progress,
    _loop_runs,
    _retried,
    _without_loops,
    _without_overlaps,
    silences,
)
from dsj.whisper import DEFAULT_WHISPER_MODEL, ROMAN_URDU_PROMPT, redecoder

REPO = Path(__file__).resolve().parent.parent.parent
RUNS = REPO / "scratch" / "accuracy" / "runs"
SETTINGS: dict[str, tuple[str | None, str | None]] = {
    "plain": (None, None),
    "ur": ("ur", None),
    "roman": ("ur", ROMAN_URDU_PROMPT),
    "roman30": ("ur", ROMAN_URDU_PROMPT),
}


def quiet(p: Progress, state: str) -> None:
    del p, state


def replay(path: Path) -> None:
    out = path.with_name(f"{path.stem}.splitretry.json")
    side = path.with_name(f"{path.stem}.preretry.json")
    if out.exists() or not side.exists():
        return
    pre: list[dict[str, Any]] = json.loads(side.read_text())["sentences"]
    runs = _loop_runs(pre)
    if not runs:
        return
    doc = json.loads(path.read_text())
    split = [s for a, b in runs for s in pre[a : b + 1]]
    spans = [(pre[a]["start"], max(s["end"] for s in pre[a : b + 1])) for a, b in runs]
    sentences = sorted(doc["sentences"] + split, key=lambda s: float(s["start"]))
    language, prompt = SETTINGS[path.stem.rsplit("-", 1)[0]]
    audio = Path(doc["audio"])
    stretches = silences(media_mod.loudness(audio, LOUDNESS_FRAME_S))
    got = _retried(
        Transcription(text="", sentences=sentences),
        stretches,
        lambda: redecoder(audio, model_id=DEFAULT_WHISPER_MODEL, language=language, prompt=prompt),
        quiet,
    )
    kept, loops = _without_loops(got)
    kept = _without_overlaps(kept, merge=True)
    others = [u for u in doc["unclear"]
              if not any(abs(u["start"] - a) < 0.01 and abs(u["end"] - b) < 0.01 for a, b in spans)]
    unclear = sorted(others + [u for u in loops
                               if any(abs(u["start"] - a) < 0.01 for a, _ in spans)],
                     key=lambda u: cast("float", u["start"]))
    left = [u for u in unclear if any(abs(u["start"] - a) < 0.01 for a, _ in spans)]
    payload = doc | {"text": kept.text, "sentences": kept.sentences, "unclear": unclear}
    out.write_text(json.dumps(payload, ensure_ascii=False))
    print(f"{path.parent.name}/{path.stem}: {len(runs)} split loops, "
          f"{sum(b - a for a, b in spans):.0f} s; {len(runs) - len(left)} read, "
          f"{sum(u['end'] - u['start'] for u in left):.0f} s left unclear", flush=True)


def main() -> int:
    for path in sorted(RUNS.glob("*/*-r[0-9].json")):
        if not path.stem.startswith("parakeet"):
            replay(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
