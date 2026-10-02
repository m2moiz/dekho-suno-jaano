#!/usr/bin/env python3
"""Write an editable draft transcript for the owner to correct (#182).

Picks the stretch of `--minutes` with the most `unclear` seconds in a dsj
transcript, so the corrected reference covers whisper's failures, and writes
it as plain text: one line per sentence, `[mm:ss] text`, with each unclear
span as its own `[UNCLEAR mm:ss to mm:ss]` line for the owner to fill in.

    uv run python scratch/make_reference_draft.py TRANSCRIPT.json OUT.txt [--minutes 10]

The draft is private (the owner's recording) and goes outside git, under
$DSJ_REAL_AUDIO/reference/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HEADER = """\
# Reference transcript for dsj issue #182: please correct this file.
#
# Source: {source}
# Stretch: {start} to {end} of the recording.
# Drafted by: {model}, `dsj suno --roman-urdu` (120 s window). It leans toward
# this setting's wording, so change anything that is not what was said.
#
# How to correct it:
# 1. Fix any wrong word. Write each language in whatever script is fastest
#    for you: Roman Urdu, Urdu script, English. Mixing is fine.
# 2. Lines that say [UNCLEAR ...] are where whisper failed. Replace the whole
#    line with what was said there (keep the time at the front), or write
#    [SILENCE] or [NOT SPEECH] if nobody spoke.
# 3. If something was said that is missing entirely, add a line for it with
#    your best guess of the time.
# 4. Leave the [mm:ss] times alone. Lines starting with # are ignored.
#
# Save the corrected copy next to this one with -corrected in the name.
"""


def clock(s: float) -> str:
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def best_window(unclear: list[dict[str, Any]], duration: float, length: float) -> float:
    """Start of the `length`-second window holding the most unclear seconds."""
    def covered(a: float) -> float:
        b = a + length
        return sum(max(0.0, min(u["end"], b) - max(u["start"], a)) for u in unclear)

    starts = [0.0] + [u["start"] for u in unclear] + [max(0.0, u["end"] - length) for u in unclear]
    starts = [min(max(0.0, a), max(0.0, duration - length)) for a in starts]
    return max(starts, key=lambda a: (covered(a), -a))


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("transcript", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--minutes", type=float, default=10.0)
    args = parser.parse_args()

    payload: dict[str, Any] = json.loads(args.transcript.read_text())
    sentences: list[dict[str, Any]] = payload["sentences"]
    unclear: list[dict[str, Any]] = payload.get("unclear") or []
    duration = max([s["end"] for s in sentences] + [u["end"] for u in unclear])
    length = args.minutes * 60
    a = best_window(unclear, duration, length)
    b = a + length

    lines: list[tuple[float, str]] = [
        (s["start"], f"[{clock(s['start'])}] {s['text'].strip()}")
        for s in sentences if a <= s["start"] < b
    ]
    lines += [
        (u["start"], f"[UNCLEAR {clock(u['start'])} to {clock(u['end'])}]")
        for u in unclear if a <= u["start"] < b
    ]
    lines.sort()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = HEADER.format(source=payload.get("audio", args.transcript.name),
                           start=clock(a), end=clock(b), model=payload.get("model", "whisper"))
    args.out.write_text(header + "\n" + "\n".join(text for _, text in lines) + "\n")
    held = sum(max(0.0, min(u["end"], b) - max(u["start"], a)) for u in unclear)
    print(f"{args.out}: {clock(a)} to {clock(b)}, {len(lines)} lines, "
          f"{sum(1 for _, t in lines if t.startswith('[UNCLEAR'))} unclear spans ({held:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
