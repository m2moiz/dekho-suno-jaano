#!/usr/bin/env python3
"""Report the share of Latin vs Arabic script per minute of a transcript.

--roman-urdu asks whisper to write Urdu speech in Latin letters by seeding the
decoder with a Roman Urdu prompt. The prompt wears off (dsj/whisper.py,
issue #100): output reverts to Urdu script, and issue #100 documents that
nothing in this repo reproduces it -- no --roman-urdu run against real Urdu
speech has ever been captured here. This is that missing measurement. Given a
transcript, it walks every token in time order and reports, per minute of
audio, how many words are Arabic-script, Latin-script, or neither (digits,
punctuation, a code-switched symbol with no letters at all).

Script detection is a Unicode range check, not a model. A word counts as
Arabic if any of its characters fall in the Arabic block or its extensions --
Urdu's Nastaliq is written in the same Unicode ranges as Arabic; there is no
separate "Urdu script" block. Arabic wins over Latin when both are present in
one word, because a code-switched English word inside an otherwise-Arabic
sentence is a different failure than a whole sentence reverting to Urdu
script, and conflating them would understate the reversion this probe exists
to catch.

    uv run python scratch/roman_urdu_probe.py scratch/*.json

Every transcript committed under scratch/ today is English audio from #53's
order-inversion probes (English is Latin script by construction), so running
this against them proves the probe runs and classifies correctly -- 100%
Latin, 0% Arabic, on every one -- and it proves NOTHING about Roman Urdu. The
real curve needs a --roman-urdu run against a real, long Urdu recording, which
does not exist in this repo yet (#100 names getting one as the blocking step).
Do not read the numbers below as a Roman Urdu measurement; they are a
mechanical smoke test of this script, nothing else.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Arabic, Arabic Supplement, Arabic Extended-A, Arabic Presentation Forms A/B.
# Urdu-specific letters (e.g. U+0679, U+0688, U+0691, U+06BA, U+06BE, U+06D2) sit
# inside the main Arabic block already; the extensions are for other
# Arabic-script languages and are included so a stray character from one does
# not get miscounted as Latin by falling through to "neither".
_ARABIC_RANGES: tuple[tuple[int, int], ...] = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)
# ASCII Latin plus Latin-1 Supplement and Latin Extended-A/B, for accented
# loanwords. Plain digits and punctuation are deliberately excluded: a "42" or
# a comma is script-neutral and should not count as evidence the Roman prompt
# held.
_LATIN_RANGES: tuple[tuple[int, int], ...] = (
    (0x0041, 0x005A),
    (0x0061, 0x007A),
    (0x00C0, 0x024F),
)


def _in_ranges(codepoint: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in ranges)


def script_of(word: str) -> str:
    """"arabic", "latin", or "neither" for one word -- Arabic wins on any Arabic character.

    Checking Arabic first, rather than "which script has more characters", is
    the point: a mostly-Roman sentence with one Urdu-script word reverting is
    the exact failure --roman-urdu is supposed to prevent, and it should show
    up as Arabic, not get diluted into "mostly Latin".
    """
    if any(_in_ranges(ord(c), _ARABIC_RANGES) for c in word):
        return "arabic"
    if any(_in_ranges(ord(c), _LATIN_RANGES) for c in word):
        return "latin"
    return "neither"


def _token_text(token: dict) -> str:
    """Word text, under either serialization this repo has written.

    suno.py writes {"t", "w"}; some transcripts under scratch/ carry the raw
    parakeet alignment shape ({"start", "text", ...}) instead. See
    order_probe.py's _token_start for the same fallback, applied there to time.
    """
    return token["w"] if "w" in token else token["text"]


def _token_start(token: dict) -> float:
    return token["t"] if "t" in token else token["start"]


def _empty_counts() -> dict[str, int]:
    return {"arabic": 0, "latin": 0, "neither": 0}


def probe(path: Path) -> None:
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict) or "sentences" not in payload:
        return
    sentences = payload["sentences"]
    if not sentences or not isinstance(sentences[0], dict) or "tokens" not in sentences[0]:
        return

    per_minute: dict[int, dict[str, int]] = defaultdict(_empty_counts)
    total = _empty_counts()
    for sentence in sentences:
        for token in sentence.get("tokens", []):
            text = _token_text(token).strip()
            if not text:
                continue
            minute = int(_token_start(token) // 60)
            kind = script_of(text)
            per_minute[minute][kind] += 1
            total[kind] += 1

    grand = sum(total.values())
    if grand == 0:
        print(f"{path}: 0 classifiable words")
        return

    print(
        f"{path}: {grand} words, "
        f"{total['latin']} latin ({total['latin'] / grand:.0%}), "
        f"{total['arabic']} arabic ({total['arabic'] / grand:.0%}), "
        f"{total['neither']} neither"
    )
    for minute in sorted(per_minute):
        counts = per_minute[minute]
        words = sum(counts.values())
        if words == 0:
            continue
        print(
            f"    minute {minute:>3}: {words:>4} words  "
            f"latin {counts['latin']:>4} ({counts['latin'] / words:.0%})  "
            f"arabic {counts['arabic']:>4} ({counts['arabic'] / words:.0%})  "
            f"neither {counts['neither']:>3}"
        )


def main(argv: list[str]) -> int:
    for arg in argv:
        probe(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
