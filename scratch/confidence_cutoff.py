#!/usr/bin/env python3
"""Where to cut a transcript's word confidence so the tint catches wrong words (#62).

Prints numbers only, never transcript text, so it can be pointed at the owner's
recordings too.

    # Against a hand-checked transcript: of the words under each cut-off, how
    # many are wrong, and how many of all wrong words that catches.
    uv run python scratch/confidence_cutoff.py TRANSCRIPT.json --truth scratch/urdu_cs/ground_truth.json

    # Without one: only the spread, what share of words each cut-off lights up.
    uv run python scratch/confidence_cutoff.py TRANSCRIPT.json

A word is a token opening with whitespace plus the tokens after it that do not,
and is as sure as its least sure token, the way the reader groups and tints
(ui/src/features/transcript/document.ts). With --truth each of the truth's
clips is aligned word by word (Levenshtein) against the transcript's words that
start inside it, after folding case, punctuation, Arabic diacritics and the
Arabic and Persian forms of yeh, kaf and heh; a word is wrong when the alignment
does not pair it with an identical truth word.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

CUTOFFS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
# A word starting this close outside a clip still counts as the clip's: whisper
# times a word up to half a second early (payload.md, "No speech").
EDGE_S = 0.5


def fold(word: str) -> str:
    word = unicodedata.normalize("NFKC", word).lower()
    word = re.sub(r"[ً-ٰٟ]", "", word)
    # Arabic yeh, kaf and heh, and heh with yeh above, to the forms Urdu writes.
    for arabic, urdu in (("\u064a", "\u06cc"), ("\u0643", "\u06a9"), ("\u0647", "\u06c1"), ("\u06c0", "\u06c1")):
        word = word.replace(arabic, urdu)
    return re.sub(r"[^\w؀-ۿ]", "", word)


def words(transcript: dict[str, Any]) -> list[tuple[float, str, float]]:
    """(start, text, least confidence) per word; a token with no `c` counts as sure."""
    out: list[tuple[float, str, float]] = []
    for sentence in transcript["sentences"]:
        for k, token in enumerate(sentence["tokens"]):
            c = float(token.get("c", 1.0))
            if k == 0 or re.match(r"\s", token["w"]):
                out.append((token["t"], token["w"], c))
            else:
                t, w, least = out[-1]
                out[-1] = (t, w + token["w"], min(least, c))
    return out


def correct(hyp: list[str], ref: list[str]) -> list[bool]:
    """For each hypothesis word, whether the edit alignment pairs it with the same word."""
    n, m = len(hyp), len(ref)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(
                d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (hyp[i - 1] != ref[j - 1])
            )
    ok = [False] * n
    i, j = n, m
    while i > 0 and j > 0:
        if d[i][j] == d[i - 1][j - 1] + (hyp[i - 1] != ref[j - 1]):
            ok[i - 1] = hyp[i - 1] == ref[j - 1]
            i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--truth", type=Path, help="a ground_truth.json as build_urdu_fixture.py writes")
    args = parser.parse_args()
    transcript = json.loads(args.transcript.read_text())
    every = words(transcript)
    print(f"{args.transcript.name}: model {transcript['model']}, {len(every)} words")
    if args.truth is None:
        n = len(every)
        for cut in CUTOFFS:
            under = sum(1 for _, _, c in every if c < cut)
            print(f"  c < {cut}: {under} words ({under / n:.1%})")
        return
    truth = json.loads(args.truth.read_text())
    scored: list[tuple[float, bool]] = []
    left = list(every)
    for clip in truth["segments"]:
        if "ground_truth" not in clip:
            continue
        # Each word is scored once, against the first clip it falls in.
        inside = [w for w in left if clip["start"] - EDGE_S <= w[0] < clip["end"] + EDGE_S]
        left = [w for w in left if w not in inside]
        hyp = [fold(w) for _, w, _ in inside]
        ref = [fold(w) for w in clip["ground_truth"].split()]
        scored += [(c, ok) for (_, w, c), ok in zip(inside, correct(hyp, ref), strict=True) if fold(w)]
    n = len(scored)
    wrong = sum(1 for _, ok in scored if not ok)
    print(f"  scored {n} words against the truth, {wrong} wrong ({wrong / n:.0%})")
    for cut in CUTOFFS:
        flagged = [ok for c, ok in scored if c < cut]
        hits = sum(1 for ok in flagged if not ok)
        print(
            f"  c < {cut}: flags {len(flagged)} ({len(flagged) / n:.0%}), "
            f"{hits} of them wrong ({hits / max(1, len(flagged)):.0%}), "
            f"catching {hits} of {wrong} wrong words ({hits / max(1, wrong):.0%})"
        )


if __name__ == "__main__":
    main()
