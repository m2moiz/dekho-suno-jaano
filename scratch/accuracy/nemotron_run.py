#!/usr/bin/env python3
"""Run NVIDIA Nemotron 3.5 ASR on one of #184's reference sets, in the shape score.py reads (#240).

    uv run --with "mlx-audio @ git+https://github.com/Blaizzy/mlx-audio@70f4add32911bab6f869b824864ad9f1e24dcb97" \
        python scratch/accuracy/nemotron_run.py --language {hi-IN,auto,en-US} --set {podcast,urdu,earnings}
    ... nemotron_run.py --language hi-IN --audio scratch/clip45.wav --out /tmp/clip45-hi.json
    ... nemotron_run.py --model hinglish --language auto --set podcast

`--model hinglish` runs `smajji/nemotron-hinglish-v4` instead, a fine-tune
of the same model on English, Hindi and Hinglish whose card decodes with
`auto`, converted with mlx-audio's own converter into
scratch/models/nemotron-hinglish-v4 (HINGLISH_CONVERT). Its runs are named
`nemotron_hinglish`. Its card lists earnings22 among its training data, so it
is not scored on the `earnings` set.

`mlx-community/nemotron-3.5-asr-streaming-0.6b` (bf16), the MLX port of
NVIDIA's cache-aware FastConformer-RNNT with a language prompt, through
mlx-audio at MLX_AUDIO_SHA (git main; mlx-audio rides in through `--with` and
never enters dsj's dependencies). The model does not run in dsj, so this is
the whole pipeline, in one process per set so the wall time includes the
imports and the model load, the way a `dsj suno` run's does:

1. The audio through mlx-whisper's loader: ffmpeg to 16 kHz mono (`-ac 1`).
2. Cut at speech with dsj's own Silero path (`dsj.whisper._speech` and
   `speech_segments`, VAD_MAX_S = 30 s), the clips `--roman-urdu` decodes, so
   both models see the same audio.
3. Each clip decoded alone with the language prompt `--language`. The prompt
   dictionary falls back to the model's default without a word when a key is
   missing (`Model._resolve_prompt_index`), so the key is checked first.
4. Word times from mlx-audio's per-token `AlignedToken` starts (RNN-T emission
   frames, 80 ms): a token opening with a space starts a word, and a word runs
   from its first token's start to its last token's end.
5. With `auto` the model emits a language tag (`<hi-IN>`) that mlx-audio drops
   as a special token; a wrapper on its tokenizer's `is_special_token` records
   them, so the run says which language each clip was called.
6. Written to scratch/accuracy/runs/<set>/nemotron_<lang>-r<N>.json, one
   sentence per clip, and a .bench.json beside it: wall time from process
   start, load and decode seconds, realtime factor, model and revision, the
   mlx-audio commit, settings and the language tags.

The owner's floor (6 Oct): 2x realtime or faster, model load included. As
run.py's `slower_than` does for dsj runs, a run is stopped once 3 min of audio
are done and its projected finish (the wall clock so far, plus the audio left
at the decode rate so far) lands under `--min-speed`, or once the wall clock
passes the recording's length over it; its bench file then records
`too_slow` and no transcript is written. The projection matters: audio done
over the wall clock so far charges a whole run's imports, load and Silero
pass to its first 3 min, and stopped two runs on course for 9 to 10x. Waits, like run.py, for no `dsj suno` running and 30% memory free
before loading. The download lands in scratch/models/dl/<repo> (`local_dir`),
never the shared ~/.cache/huggingface, so it can be deleted alone.
"""

from __future__ import annotations

import time

STARTED = time.monotonic()  # before the imports: they are part of a run's cost

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from convert_finetunes import DL, wait_turn  # noqa: E402
from other_models import sentence  # noqa: E402
from run import MIN_SPEED_AFTER_S, RUNS, SETS, commit  # noqa: E402

from dsj import whisper  # noqa: E402

MODEL = ("mlx-community/nemotron-3.5-asr-streaming-0.6b", "e550040c0478027ed679b2b6b0d055502c103663")
HINGLISH = ("smajji/nemotron-hinglish-v4", "19d5c968adc7dd1eebf744909d4c5ca00bb8819f")
HINGLISH_DIR = REPO / "scratch" / "models" / "nemotron-hinglish-v4"
HINGLISH_CONVERT = (
    "uv run --with 'mlx-audio @ git+https://github.com/Blaizzy/mlx-audio@{sha}' --with torch --with pyyaml "
    "python -m mlx_audio.stt.models.nemotron_asr.convert --nemo-path "
    "scratch/models/dl/smajji--nemotron-hinglish-v4/nemotron-hinglish-v4.nemo "
    "--mlx-path scratch/models/nemotron-hinglish-v4 --dtype bfloat16"
)
MLX_AUDIO_SHA = "70f4add32911bab6f869b824864ad9f1e24dcb97"
MODES = {"hi-IN": "nemotron_hi", "auto": "nemotron_auto", "en-US": "nemotron_en"}
SR = whisper.SAMPLE_RATE


def fetch() -> Path:
    from huggingface_hub import snapshot_download

    repo, revision = MODEL
    target = DL / repo.replace("/", "--")
    snapshot_download(repo_id=repo, revision=revision, local_dir=target)
    return target


def words_of(tokens: list[Any], offset: float) -> list[tuple[str, float, float]]:
    """(word, start, end) from RNN-T tokens: a token opening with a space starts a word.

    SentencePiece also emits the space alone (`▁`, then `an`, `s`, `w`, `er`),
    so a bare space starts the next word rather than being dropped.
    """
    out: list[tuple[str, float, float]] = []
    fresh = True
    for token in tokens:
        text = str(token.text)
        if not text.strip():
            fresh = True
            continue
        if fresh or text.startswith(" ") or not out:
            out.append((text.strip(), offset + token.start, offset + token.end))
        else:
            word, start, _ = out[-1]
            out[-1] = (word + text, start, offset + token.end)
        fresh = False
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--language", required=True, choices=sorted(MODES))
    parser.add_argument("--model", choices=["base", "hinglish"], default="base")
    parser.add_argument("--set", choices=["podcast", "urdu", "earnings"])
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--audio", type=Path, help="any recording instead of a set (a smoke run), with --out")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--min-speed", type=float, default=2.0, help="stop a run that cannot finish at this x realtime")
    args = parser.parse_args()
    if bool(args.set) == bool(args.audio) or bool(args.audio) != bool(args.out):
        parser.error("give --set, or --audio with --out")

    mode = "nemotron_hinglish" if args.model == "hinglish" else MODES[args.language]
    out = args.out or RUNS / args.set / f"{mode}-r{args.run}.json"
    if out.exists():
        print(f"{out} already there", flush=True)
        return 0
    if args.model == "hinglish":
        if not HINGLISH_DIR.exists():
            sys.exit(f"convert it first: {HINGLISH_CONVERT.format(sha=MLX_AUDIO_SHA)}")
        folder = HINGLISH_DIR
    else:
        folder = fetch()

    import mlx.core as mx
    from mlx_audio.stt import load
    from mlx_audio.stt.models.nemotron_asr import tokenizer
    from mlx_whisper.audio import load_audio

    tags: list[str] = []
    special = tokenizer.is_special_token

    def recorded(token_id: int, vocabulary: list[str]) -> bool:
        if 0 <= token_id < len(vocabulary) and tokenizer.is_lang_tag(vocabulary[token_id]):
            tags.append(vocabulary[token_id][1:-1])
        return special(token_id, vocabulary)

    tokenizer.is_special_token = recorded

    wait_turn()
    # Other work on this Mac shares the GPU; the load average says how busy it was.
    load_before = [round(x, 1) for x in os.getloadavg()]
    audio = args.audio or SETS[args.set]
    data = np.asarray(load_audio(str(audio), sr=SR), dtype=np.float32)
    duration = len(data) / SR
    vad_started = time.monotonic()
    spans, probs = whisper._speech(data)
    clips = whisper.speech_segments(spans, whisper.VAD_MAX_S, probs, whisper.VAD_FRAME_S)
    vad_s = time.monotonic() - vad_started

    loaded = time.monotonic()
    model: Any = load(str(folder))
    load_s = time.monotonic() - loaded
    if args.language not in model.prompt_dictionary:
        sys.exit(f"{args.language} is not in the prompt dictionary: the model would fall back to its default")

    sentences: list[dict[str, Any]] = []
    per_clip: Counter[str] = Counter()
    too_slow: dict[str, Any] | None = None
    decoding = time.monotonic()
    for k, (a, b) in enumerate(clips, 1):
        clip = data[int(a * SR) : min(int(b * SR), len(data))]
        first = len(tags)
        result = model.generate(mx.array(clip), language=args.language)
        tokens = [t for s in result.sentences for t in s.tokens]
        words = words_of(tokens, a)
        clip_tags = tags[first:]
        per_clip[clip_tags[0] if clip_tags else "none"] += 1
        if words:
            sentences.append({**sentence(a, b, words), **({"lang": clip_tags} if clip_tags else {})})
        wall = time.monotonic() - STARTED
        print(f"  clip {k}/{len(clips)} {a:.1f}-{b:.1f} s: {len(words)} words {clip_tags or ''} "
              f"({b / wall:.2f}x so far)", flush=True)
        # The owner's floor, as run.py's slower_than: own speed after 3 min of
        # audio, or a wall clock past the recording's length over the floor.
        projected = wall + (duration - b) * (time.monotonic() - decoding) / b
        if b >= MIN_SPEED_AFTER_S and duration / projected < args.min_speed:
            too_slow = {"rule": "speed", "projected_speed": round(duration / projected, 2),
                        "audio_done_s": round(b, 1), "wall_s": round(wall)}
        elif wall > duration / args.min_speed:
            too_slow = {"rule": "wall", "speed": round(b / wall, 2), "audio_done_s": round(b, 1), "wall_s": round(wall)}
        if too_slow:
            print(f"  too slow: {too_slow}", flush=True)
            break
    decode_s = time.monotonic() - decoding
    wall = time.monotonic() - STARTED

    repo, revision = HINGLISH if args.model == "hinglish" else MODEL
    if not too_slow:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "audio": str(audio), "engine": "nemotron", "model": f"{repo}@{revision}", "language": args.language,
            "text": " ".join(s["text"] for s in sentences), "unclear": [], "sentences": sentences,
        }, ensure_ascii=False, indent=1) + "\n")
    meta = {
        "wall_s": round(wall, 1), "audio_s": round(duration, 1),
        # A stopped run did only part of the audio: its speed is what it did.
        "x_realtime": round((too_slow["audio_done_s"] if too_slow else duration) / wall, 2),
        "vad_s": round(vad_s, 1), "load_s": round(load_s, 1), "decode_s": round(decode_s, 1),
        "returncode": 0, "model": repo, "revision": revision, "dtype": "bfloat16",
        "mlx_audio": f"git+https://github.com/Blaizzy/mlx-audio@{MLX_AUDIO_SHA}", "clips": len(clips),
        "settings": {
            "language": args.language, "segmentation": "dsj Silero clips (whisper.speech_segments)",
            "vad_max_s": whisper.VAD_MAX_S, "vad_pad_ms": whisper.VAD_PAD_MS,
            "vad_threshold": whisper.VAD_THRESHOLD, "vad_min_silence_ms": whisper.VAD_MIN_SILENCE_MS,
            "vad_min_speech_ms": whisper.VAD_MIN_SPEECH_MS, "decode": "greedy RNN-T, mlx-audio defaults",
            "word_times": "first token start to last token end, RNN-T emission frames",
        },
        "loadavg_before": load_before, "loadavg_after": [round(x, 1) for x in os.getloadavg()],
        "lang_tags": dict(Counter(tags)), "clips_by_first_tag": dict(per_clip),
        "commit": commit(), **({"too_slow": too_slow} if too_slow else {}),
    }
    out.with_name(f"{out.stem}.bench.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{out}: {len(sentences)} clips with text, {wall / 60:.1f} min, {duration / wall:.2f}x realtime"
          + (", stopped as too slow" if too_slow else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
