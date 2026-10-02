#!/usr/bin/env python3
"""Count a transcript's broken promises: overlaps, stray tokens, impossible unclear spans (#183).

    uv run python scratch/transcript_invariants.py TRANSCRIPT.json [...]

Per transcript, numbers only (the owner's recordings are private):

- overlaps: consecutive sentences where one ends after the next starts. Where
  the second starts is printed too, so a seam of whisper's anchored windows
  (a multiple of 114 s under ANCHOR_CHUNK_S 120 and ANCHOR_OVERLAP_S 6) can be
  told from anything else.
- stray tokens: a token whose `t` or `e` lies outside its own sentence, or that
  ends before it starts.
- empty unclear: an `unclear` span with end <= start.
- crowded unclear: a span with more than MAX_WPS words a second. Its words
  cannot have been spoken there; whisper timed them into it (a loop at the end
  of a window, all its words given one end time).
- unclear inside a sentence: a span that lies within one sentence, so its
  seconds were read by another decode.
- text mismatch: `text` is not the sentences joined.

scratch/retry_loops_run.py runs `violations` on every transcript it writes.
"""

from __future__ import annotations

import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

# Fast speech is about 4 words a second; ten leaves room for any real span.
MAX_WPS = 10.0


def violations(payload: dict[str, Any]) -> dict[str, Any]:
    sentences: list[dict[str, Any]] = payload["sentences"]
    unclear: list[dict[str, Any]] = payload.get("unclear") or []
    overlaps = [
        round(b["start"], 2)
        for a, b in pairwise(sentences)
        if a["end"] > b["start"]
    ]
    stray = sum(
        1
        for s in sentences
        for t in s["tokens"]
        if not (s["start"] <= t["t"] <= t.get("e", t["t"]) <= s["end"])
    )
    empty = sum(1 for u in unclear if u["end"] <= u["start"])
    crowded = sum(
        1 for u in unclear if u["end"] > u["start"] and u["words"] / (u["end"] - u["start"]) > MAX_WPS
    )
    inside = sum(
        1 for u in unclear for s in sentences if s["start"] <= u["start"] and u["end"] <= s["end"]
    )
    joined = "".join(str(s["text"]) for s in sentences).strip()
    return {
        "overlaps": len(overlaps),
        "overlap_at": overlaps,
        "stray_tokens": stray,
        "empty_unclear": empty,
        "crowded_unclear": crowded,
        "unclear_inside_a_sentence": inside,
        "text_mismatch": int(payload["text"] != joined),
    }


def main(argv: list[str]) -> int:
    for path in argv:
        print(Path(path).parent.name, Path(path).stem, json.dumps(violations(json.loads(Path(path).read_text()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
