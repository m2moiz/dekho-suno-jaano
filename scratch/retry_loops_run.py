#!/usr/bin/env python3
"""Apply dsj's loop retry (#183) to transcripts already on disk, and count what it recovers.

The transcripts the probe used (scratch/redecode_probe.py) were written on
v0.2.1, which had already taken each loop out of `sentences` into `unclear`.
So each `repetition loop` span is put back as a stand-in loop sentence (the
span's own bounds and word count, one repeated word), and the transcript then
goes through the same three steps the product runs after a whisper pass:
`_without_silence`, `_retried` with the real `redecoder`, `_without_loops`.
No full re-transcription; one whisper model in this process, spans one at a
time.

    uv run python scratch/retry_loops_run.py LABEL/NAME [LABEL/NAME ...]

LABEL/NAME is a transcript under scratch/real_bench/runs/, without `.json`;
its audio is NAME.m4a in $DSJ_REAL_AUDIO. Prints numbers only, never text: the
owner's recordings are private. The retried transcript is written to
scratch/real_bench/runs/r183-LABEL/NAME.json (never over an existing file) so
it can be scored against #182 when that is back. The table is appended to
scratch/real_bench/retry183.md.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dsj import media as media_mod
from dsj import suno
from dsj.asr import Transcription, with_char_offsets
from dsj.whisper import ROMAN_URDU_PROMPT, redecoder

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "scratch" / "real_bench" / "runs"
OUT = REPO / "scratch" / "real_bench" / "retry183.md"


def stand_in(u: dict[str, Any]) -> dict[str, Any]:
    """A loop sentence over `u`'s span with `u`'s word count, one word repeated."""
    n = int(u["words"])
    step = (u["end"] - u["start"]) / n
    tokens = [
        {"t": round(u["start"] + i * step, 3), "w": " x",
         "e": round(u["start"] + (i + 1) * step, 3), "c": 0.0}
        for i in range(n)
    ]
    tokens[-1]["e"] = u["end"]
    return {"start": u["start"], "end": u["end"], "text": " x" * n,
            "tokens": with_char_offsets(tokens)}


def words(sentences: list[dict[str, Any]]) -> int:
    return sum(len(suno._WORD.findall(str(s["text"]))) for s in sentences)  # pyright: ignore[reportPrivateUsage]


def loops(unclear: list[dict[str, Any]]) -> tuple[int, float]:
    spans = [u for u in unclear if u["reason"] == suno.LOOP_REASON]
    return len(spans), sum(u["end"] - u["start"] for u in spans)


def one(ref: str, audio_root: Path) -> str:
    label, name = ref.split("/")
    payload = json.loads((RUNS / label / f"{name}.json").read_text())
    audio = audio_root / f"{name}.m4a"
    out = RUNS / f"r183-{label}" / f"{name}.json"
    if out.exists():
        sys.exit(f"{out} exists; refusing to overwrite")

    before_spans, before_s = loops(payload["unclear"])
    sentences = sorted(
        payload["sentences"] + [stand_in(u) for u in payload["unclear"]
                                if u["reason"] == suno.LOOP_REASON],
        key=lambda s: s["start"],
    )
    text = "".join(str(s["text"]) for s in sentences).strip()
    stretches = suno.silences(media_mod.loudness(audio, suno.LOUDNESS_FRAME_S))
    t, no_speech = suno._without_silence(Transcription(text, sentences), stretches)  # pyright: ignore[reportPrivateUsage]
    loop_sentences = [s for s in t.sentences if suno.is_loop(str(s["text"]))]
    base_words = words([s for s in t.sentences if not suno.is_loop(str(s["text"]))])

    calls = {"plain": 0, "warm": 0}
    frames: list[str] = []

    def decoder() -> suno.Decode:
        decode = redecoder(audio, model_id=payload["model"], language="ur",
                           prompt=ROMAN_URDU_PROMPT)

        def counted(a: float, b: float, options: dict[str, Any]) -> list[dict[str, Any]]:
            calls["plain" if options is suno.RETRY_PLAIN else "warm"] += 1
            return decode(a, b, options)

        return counted

    def report(p: suno.Progress, state: str) -> None:
        frames.append(state)

    started = time.monotonic()
    t = suno._retried(t, stretches, decoder, report)  # pyright: ignore[reportPrivateUsage]
    wall = time.monotonic() - started
    t, loops_after = suno._without_loops(t)  # pyright: ignore[reportPrivateUsage]
    after_spans, after_s = loops(loops_after)
    # One frame before the first span, then one per span retried.
    retried = max(len(frames) - 1, 0)
    recovered = len(loop_sentences) - after_spans
    # A span goes to warm only when plain failed on it.
    by_plain = retried - calls["warm"]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload | {
        "text": t.text,
        "unclear": sorted(no_speech + loops_after, key=lambda u: u["start"]),
        "sentences": t.sentences,
    }))
    return (
        f"| {label}/{name[-6:]} | {before_spans} | {before_s:.0f} | "
        f"{len(no_speech)} | {len(loop_sentences)} | {retried} | {after_spans} | "
        f"{after_s:.0f} | {recovered} ({by_plain} plain, {recovered - by_plain} warm) | "
        f"{words(t.sentences) - base_words} | {wall:.0f} |"
    )


def main(argv: list[str]) -> int:
    root = os.environ.get("DSJ_REAL_AUDIO")
    if not root or not argv:
        sys.exit("usage: DSJ_REAL_AUDIO=... retry_loops_run.py LABEL/NAME [...]")
    head = (
        "| transcript | loop spans before | loop s before | no-speech stretches"
        " | loops left after the silence rule | spans retried | loop spans after"
        " | loop s after | spans recovered | words added | retry wall s |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|"
    )
    print(head, flush=True)
    rows: list[str] = []
    for ref in argv:
        row = one(ref, Path(root))
        print(row, flush=True)
        rows.append(row)
    with OUT.open("a") as fh:
        fh.write(f"\n## loop retry, {time.strftime('%Y-%m-%d %H:%M')}\n\n{head}\n"
                 + "\n".join(rows) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
