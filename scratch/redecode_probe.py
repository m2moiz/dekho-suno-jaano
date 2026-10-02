#!/usr/bin/env python3
"""Decode each unclear span of a transcript again, three ways, and count what comes back (#183).

A loop marks seconds whisper failed to decode, and two identical runs on the
same file differ by hundreds of loop seconds (#100), so a second attempt at
just those seconds may succeed. For every `unclear` span with reason
"repetition loop", this cuts the span plus PAD_S either side and decodes it:

- same: the `--roman-urdu` settings again (language ur, the Roman prompt)
- plain: language ur, no prompt
- warm: the Roman prompt at temperature 0.4

and reports, per option, the words that come back and whether any of them is
itself a loop by `dsj.suno.is_loop`. It counts; it never prints text, because
the owner's recordings are private.

    uv run python scratch/redecode_probe.py TRANSCRIPT.json AUDIO [TRANSCRIPT.json AUDIO ...]

Runs one whisper at a time in this process. Results print as a table and are
appended to scratch/real_bench/redecode.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PAD_S = 2.0
SR = 16000
OUT = REPO / "scratch" / "real_bench" / "redecode.md"


def options(prompt: str) -> dict[str, dict[str, Any]]:
    return {
        "same": {"language": "ur", "initial_prompt": prompt, "temperature": 0.0},
        "plain": {"language": "ur", "temperature": 0.0},
        "warm": {"language": "ur", "initial_prompt": prompt, "temperature": 0.4},
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) % 2:
        sys.exit("usage: redecode_probe.py TRANSCRIPT.json AUDIO [TRANSCRIPT.json AUDIO ...]")
    import mlx_whisper  # pyright: ignore[reportMissingImports]
    from mlx_whisper.audio import load_audio  # pyright: ignore[reportMissingImports]

    from dsj.suno import is_loop
    from dsj.whisper import DEFAULT_WHISPER_MODEL, ROMAN_URDU_PROMPT

    opts = options(ROMAN_URDU_PROMPT)
    rows: list[str] = []
    totals = {k: [0, 0, 0] for k in opts}  # spans recovered, words, spans tried
    for transcript, audio_path in zip(argv[::2], argv[1::2]):
        payload = json.loads(Path(transcript).read_text())
        spans = [u for u in payload.get("unclear") or [] if u.get("reason") == "repetition loop"]
        audio = load_audio(audio_path)
        name = Path(audio_path).stem
        for u in spans:
            a = max(0, int((u["start"] - PAD_S) * SR))
            b = min(len(audio), int((u["end"] + PAD_S) * SR))
            clip = audio[a:b]
            cells: list[str] = []
            for key, kw in opts.items():
                started = time.monotonic()
                result = mlx_whisper.transcribe(
                    clip, path_or_hf_repo=DEFAULT_WHISPER_MODEL,
                    condition_on_previous_text=False, **kw,
                )
                segments = result.get("segments") or []
                looped = any(is_loop(str(s.get("text") or "")) for s in segments)
                words = sum(len(str(s.get("text") or "").split()) for s in segments
                            if not is_loop(str(s.get("text") or "")))
                ok = not looped and words > 0
                totals[key][0] += ok
                totals[key][1] += words if ok else 0
                totals[key][2] += 1
                cells.append(f"{'ok' if ok else 'loop' if looped else 'empty'} {words}w "
                             f"{time.monotonic() - started:.0f}s")
            row = f"| {name} | {u['start']:.0f} to {u['end']:.0f} | {u['end'] - u['start']:.0f} | " \
                  + " | ".join(cells) + " |"
            print(row, flush=True)
            rows.append(row)
    head = "| file | span s | length s | " + " | ".join(opts) + " |\n|---|---|---:|" + "---|" * len(opts)
    summary = " · ".join(f"{k}: {v[0]}/{v[2]} spans recovered, {v[1]} words" for k, v in totals.items())
    text = f"\n## redecode probe, {time.strftime('%Y-%m-%d %H:%M')}\n\n{head}\n" + "\n".join(rows) \
           + f"\n\n{summary}\n"
    print(text)
    with OUT.open("a") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
