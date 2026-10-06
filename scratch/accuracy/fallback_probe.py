#!/usr/bin/env python3
"""Why a turbo-shaped model runs slower than turbo: per clip, the decode time and what whisper fell back to (#240).

    uv run python scratch/accuracy/fallback_probe.py MODEL {en,roman} [--clips 8] [--set podcast]

Decodes the first `--clips` of dsj's Silero clips with mlx-whisper and the
arguments `dsj.whisper._vad_decoded` passes (word times, no conditioning on
the previous text, dsj's silence threshold), as `--language en` or as
`--roman-urdu` (language ur with ROMAN_URDU_PROMPT). For each clip it prints
the seconds taken and, per segment whisper returned, the temperature it
settled at (0.0 unless the compression-ratio or log-probability check made it
fall back), the token count, the compression ratio and the mean log-prob.
One model per process; it waits for no `dsj suno` running and 30% memory free.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

from convert_finetunes import wait_turn  # noqa: E402
from run import SETS  # noqa: E402

from dsj import whisper  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("model", help="a converted model folder or an HF repo id")
    parser.add_argument("mode", choices=["en", "roman"])
    parser.add_argument("--clips", type=int, default=8)
    parser.add_argument("--set", default="podcast", choices=sorted(SETS))
    args = parser.parse_args()

    import mlx_whisper
    from mlx_whisper.audio import load_audio

    wait_turn()
    data = np.asarray(load_audio(str(SETS[args.set]), sr=whisper.SAMPLE_RATE), dtype=np.float32)
    spans, probs = whisper._speech(data)
    clips = whisper.speech_segments(spans, whisper.VAD_MAX_S, probs, whisper.VAD_FRAME_S)[: args.clips]
    language, prompt = ("en", None) if args.mode == "en" else ("ur", whisper.ROMAN_URDU_PROMPT)
    total_audio = total_s = 0.0
    for a, b in clips:
        clip = data[int(a * whisper.SAMPLE_RATE) : int(b * whisper.SAMPLE_RATE)]
        started = time.monotonic()
        result = mlx_whisper.transcribe(
            clip, path_or_hf_repo=args.model, language=language, initial_prompt=prompt,
            word_timestamps=True, condition_on_previous_text=False,
            hallucination_silence_threshold=whisper.HALLUCINATION_SILENCE_S, verbose=None,
        )
        took = time.monotonic() - started
        total_audio += b - a
        total_s += took
        segs = result.get("segments") or []
        print(f"clip {a:6.1f}-{b:6.1f} s: {took:5.1f} s, {len(segs)} segments", flush=True)
        for s in segs:
            print(f"    t={s['temperature']:.1f} tokens={len(s['tokens']):3d} cr={s['compression_ratio']:.2f} "
                  f"lp={s['avg_logprob']:.2f} {s['text'][:90]!r}", flush=True)
    print(f"{total_audio:.0f} s of audio in {total_s:.0f} s decoding, {total_audio / total_s:.2f}x (first clip includes the load)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
