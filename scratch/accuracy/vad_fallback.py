#!/usr/bin/env python3
"""Why `ur_vad` took 66 min on the 30 min English call (#236): count whisper's decodes per clip.

    uv run python scratch/accuracy/vad_fallback.py [--set earnings] [--clips 8]

Cuts the set as dsj.whisper's VAD path does (Silero, then speech_segments),
and decodes the first N clips the way `_vad_decoded` does, once with
`language="ur"` and once with `"en"`. mlx-whisper retries a window at a higher
temperature when its text is too repetitive (compression ratio over 2.4) or too
unlikely, up to six decodes per window (temperatures 0.0 to 1.0); every
`model.decode` call is counted here, with the temperature it ran at. Prints per
clip: decodes, the temperature of each in order, seconds, and the text's first characters.

One whisper run at a time: start it only when no `dsj suno` is running.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from run import SETS  # noqa: E402

from dsj import whisper  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--set", default="earnings", choices=sorted(SETS))
    parser.add_argument("--clips", type=int, default=8)
    parser.add_argument("--languages", nargs="+", default=["ur", "en"])
    args = parser.parse_args()

    import mlx.core as mx
    import mlx_whisper
    from mlx_whisper.audio import load_audio
    from mlx_whisper.transcribe import ModelHolder

    data = load_audio(str(SETS[args.set]))
    spans, probs = whisper._speech(data)
    clips = whisper.speech_segments(spans, whisper.VAD_MAX_S, probs, whisper.VAD_FRAME_S)[: args.clips]

    model: Any = ModelHolder.get_model(whisper.DEFAULT_WHISPER_MODEL, mx.float16)
    real_decode = model.decode
    temps: list[float] = []

    def counted(segment: Any, options: Any) -> Any:
        temps.append(float(options.temperature))
        return real_decode(segment, options)

    model.decode = counted
    for language in args.languages:
        print(f"\n## language={language}, {args.set}, first {len(clips)} clips")
        print("| clip | s | decodes | temperatures, in order | wall s | text |")
        print("|---|---:|---:|---:|---:|---|")
        total_wall = 0.0
        total_decodes = 0
        for a, b in clips:
            temps.clear()
            started = time.monotonic()
            result = mlx_whisper.transcribe(
                data[int(a * whisper.SAMPLE_RATE) : int(b * whisper.SAMPLE_RATE)],
                path_or_hf_repo=whisper.DEFAULT_WHISPER_MODEL,
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,
                verbose=None,
            )
            wall = time.monotonic() - started
            total_wall += wall
            total_decodes += len(temps)
            text = str(result.get("text", "")).strip().replace("|", " ")[:60]
            print(f"| {a:.1f}-{b:.1f} | {b - a:.1f} | {len(temps)} | {" ".join(f"{t:g}" for t in temps) or "-"} | "
                  f"{wall:.1f} | {text} |", flush=True)
        print(f"total: {total_decodes} decodes, {total_wall:.0f} s wall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
