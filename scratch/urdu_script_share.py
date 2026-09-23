#!/usr/bin/env python3
"""Reproduce the 41% / 80% / 97% / 99% Urdu-script figures in dsj/whisper.py.

Those four numbers came from a Claude Cowork session on 2026-09-22 that ran
`dsj suno --roman-urdu` over four recordings from 20 Sep 2026. Its session
transcript (fetched later with `claude --teleport`) shows the exact metric, as
an inline script in tool call #82. This file is that metric, verbatim, so the
docstring's numbers have something in the repo that reproduces them (#100).

scratch/roman_urdu_probe.py measures something else: a per-minute curve of
words by script. This one is the single sentence-weighted number the docstring
quotes, and nothing more.

The metric: a sentence counts as Urdu script when more than 30% of its
characters are in the Arabic block (U+0600 to U+06FF). The share is the
seconds covered by such sentences over the seconds covered by all sentences.

Two things it does not measure, so read the output with them in mind:

1. The denominator is seconds *covered by sentences*, not the recording's
   length. Silence and dropped audio are in neither side.
2. Repetition loops count as speech, in whichever script they are written.
   A Latin loop ("ho ho ho ho ...") reads as more Roman; a loop of one Urdu
   letter repeated reads as more Urdu. On recording-20260922-171500 that
   second kind is 671 of the file's 1,684 seconds: the share is 56% with the
   loops in and 15% with them out, so that file's number is mostly loops,
   not drift. On the three Sunday files removing loops moves the share by
   one to three points. Separate the two before reading this as drift (#140).

    uv run python scratch/urdu_script_share.py path/to/recording-*.json

Run 2026-09-23 against the JSONs still on disk in the Drive folder
`Hi-Q Recordings/transcripts/`, it reproduced three of the four exactly:

    recording-20260920-094234    arabic-script   884s of   914s (97%)
    recording-20260920-101117    arabic-script   458s of   572s (80%)
    recording-20260920-162033    arabic-script   415s of  1023s (41%)

The fourth, 99% for recording-20260920-164413, cannot be rerun: that JSON was
deleted by a batch script before a re-run that was then stopped (#137).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ARABIC_BLOCK = ("؀", "ۿ")
THRESHOLD = 0.3


def is_urdu(text: str) -> bool:
    """Whether more than THRESHOLD of `text`'s characters are in the Arabic block.

    The one definition of "this sentence came back in Urdu script". Imported by
    scratch/real_bench.py so its numbers and this file's cannot drift apart.
    """
    arabic = sum(1 for c in text if ARABIC_BLOCK[0] <= c <= ARABIC_BLOCK[1])
    return arabic > len(text) * THRESHOLD


def urdu_share(path: Path) -> tuple[float, float]:
    """Seconds in Urdu-script sentences, and seconds in all sentences."""
    sentences = json.loads(path.read_text())["sentences"]
    urdu = latin = 0.0
    for sentence in sentences:
        seconds = sentence["end"] - sentence["start"]
        if is_urdu(sentence.get("text") or ""):
            urdu += seconds
        else:
            latin += seconds
    return urdu, urdu + latin


def main(argv: list[str]) -> int:
    """Print one line per transcript given on the command line."""
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        path = Path(arg)
        urdu, total = urdu_share(path)
        share = 100 * urdu / total if total else 0.0
        print(f"{path.stem:28} arabic-script {urdu:5.0f}s of {total:5.0f}s ({share:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
