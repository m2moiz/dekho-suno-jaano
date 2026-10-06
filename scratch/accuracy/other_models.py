#!/usr/bin/env python3
"""Run MMS or SeamlessM4T v2 on one of #184's reference sets, in the shape score.py reads (#235).

    uv run --with transformers --with sentencepiece --with accelerate \
        python scratch/accuracy/other_models.py {mms,seamless} --set {podcast,urdu,earnings}

Neither model runs in dsj, so this is the whole pipeline, in one process per
set so the wall time includes the model load the way a `dsj suno` run's does:

1. The audio through mlx-whisper's loader, which is ffmpeg to 16 kHz mono
   (`-ac 1` averages the channels: SeamlessM4T's feature extractor would keep
   only the left one).
2. Cut at speech with dsj's own Silero path (`dsj.whisper._speech` and
   `speech_segments`, VAD_MAX_S = 30 s), the clips `--roman-urdu` decodes.
3. Each clip decoded alone:
   - `mms`: `facebook/mms-1b-all` with the `urd-script_arabic` adapter, CTC
     greedy. Word times from the CTC frames (`output_word_offsets`).
   - `seamless`: `facebook/seamless-m4t-v2-large`, speech to text with
     `tgt_lang="urd"`, greedy, `max_new_tokens` = MAX_NEW_TOKENS (the config
     default is 256). It gives no word times, so each clip's words are spread
     evenly over the clip; a clip whose output reached the cap is counted.
4. Written to scratch/accuracy/runs/<set>/<model>-r1.json, one sentence per
   clip with its start and end, and <model>-r1.bench.json beside it: wall
   time, load and decode seconds, model and revision, device, dtype, settings.

`--slice-s 240` times only the clips starting in the first 240 s and writes
<model>-slice.bench.json: the owner's floor (6 Oct) is 2x realtime or faster,
and a model under it gets no full runs.

Downloads land in scratch/models/dl/<repo> (`local_dir`), never the shared
~/.cache/huggingface, so they can be deleted alone. Waits, like run.py, for no
`dsj suno` running and 30% memory free before loading.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from convert_finetunes import DL, wait_turn  # noqa: E402
from run import RUNS, SETS, commit  # noqa: E402

from dsj import whisper  # noqa: E402

MODELS = {
    "mms": ("facebook/mms-1b-all", "3d33597edbdaaba14a8e858e2c8caa76e3cec0cd",
            ["*.json", "model.safetensors", "adapter.urd-script_arabic.safetensors"]),
    "seamless": ("facebook/seamless-m4t-v2-large", "5f8cc790b19fc3f67a61c105133b20b34e3dcb76",
                 ["*.json", "model-*.safetensors", "*.model"]),
}
MMS_LANG = "urd-script_arabic"
MAX_NEW_TOKENS = 512
SR = whisper.SAMPLE_RATE


def fetch(which: str) -> Path:
    from huggingface_hub import snapshot_download

    repo, revision, patterns = MODELS[which]
    target = DL / repo.replace("/", "--")
    snapshot_download(repo_id=repo, revision=revision, local_dir=target, allow_patterns=patterns)
    return target


def device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def sentence(start: float, end: float, words: list[tuple[str, float, float]]) -> dict[str, Any]:
    """A payload sentence: the clip's span, its text, and one token per word."""
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "text": " ".join(w for w, _, _ in words),
        "tokens": [{"t": round(t, 3), "w": " " + w, "e": round(e, 3)} for w, t, e in words],
    }


def spread(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    words = text.split()
    step = (end - start) / max(1, len(words))
    return [(w, start + k * step, start + (k + 1) * step) for k, w in enumerate(words)]


class Mms:
    def __init__(self, folder: Path, dev: str) -> None:
        import torch
        from transformers import AutoProcessor, Wav2Vec2ForCTC

        self.torch = torch
        self.dev = dev
        self.processor: Any = AutoProcessor.from_pretrained(folder, target_lang=MMS_LANG)
        self.model: Any = Wav2Vec2ForCTC.from_pretrained(
            folder, target_lang=MMS_LANG, ignore_mismatched_sizes=True).to(dev).eval()
        # inputs_to_logits_ratio samples per CTC frame (320 = 20 ms).
        self.frame_s = self.model.config.inputs_to_logits_ratio / SR
        self.dtype = "float32"

    def __call__(self, clip: Any, offset: float, end: float) -> tuple[list[tuple[str, float, float]], bool]:
        inputs = self.processor(clip, sampling_rate=SR, return_tensors="pt").to(self.dev)
        with self.torch.inference_mode():
            logits = self.model(**inputs).logits
        ids = self.torch.argmax(logits, dim=-1)[0].cpu()
        out = self.processor.decode(ids, output_word_offsets=True)
        words = [(w["word"], offset + w["start_offset"] * self.frame_s, offset + w["end_offset"] * self.frame_s)
                 for w in out.word_offsets]
        return words, False


class Seamless:
    def __init__(self, folder: Path, dev: str) -> None:
        import torch
        from transformers import AutoProcessor, SeamlessM4Tv2ForSpeechToText

        self.torch = torch
        self.dev = dev
        self.processor: Any = AutoProcessor.from_pretrained(folder)
        dtype = torch.float16 if dev == "mps" else torch.float32
        self.model: Any = SeamlessM4Tv2ForSpeechToText.from_pretrained(folder, dtype=dtype).to(dev).eval()
        self.dtype = str(dtype).removeprefix("torch.")

    def __call__(self, clip: Any, offset: float, end: float) -> tuple[list[tuple[str, float, float]], bool]:
        inputs = self.processor(audio=clip, sampling_rate=SR, return_tensors="pt").to(self.dev)
        inputs["input_features"] = inputs["input_features"].to(self.model.dtype)
        with self.torch.inference_mode():
            tokens = self.model.generate(**inputs, tgt_lang="urd", max_new_tokens=MAX_NEW_TOKENS,
                                         do_sample=False, num_beams=1)
        seq = tokens[0] if not hasattr(tokens, "sequences") else tokens.sequences[0]
        capped = len(seq) >= MAX_NEW_TOKENS
        text = self.processor.decode(seq, skip_special_tokens=True)
        return spread(text, offset, end), capped


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--set", required=True, choices=["podcast", "urdu", "earnings"])
    parser.add_argument("--fetch-only", action="store_true", help="download and stop")
    parser.add_argument("--slice-s", type=float, default=None,
                        help="time only the clips starting in the first N s; write <model>-slice.bench.json")
    args = parser.parse_args()

    out = RUNS / args.set / f"{args.model}-r1.json"
    if out.exists() and not args.fetch_only and not args.slice_s:
        print(f"{out} already there", flush=True)
        return 0
    folder = fetch(args.model)
    if args.fetch_only:
        return 0

    from mlx_whisper.audio import load_audio

    wait_turn()
    started = time.monotonic()
    audio = SETS[args.set]
    data = np.asarray(load_audio(str(audio), sr=SR), dtype=np.float32)  # an mx.array otherwise
    spans, probs = whisper._speech(data)
    clips = whisper.speech_segments(spans, whisper.VAD_MAX_S, probs, whisper.VAD_FRAME_S)
    if args.slice_s:
        clips = [c for c in clips if c[0] < args.slice_s]
    vad_s = time.monotonic() - started

    dev = device()
    loaded = time.monotonic()
    decoder = Mms(folder, dev) if args.model == "mms" else Seamless(folder, dev)
    load_s = time.monotonic() - loaded

    sentences: list[dict[str, Any]] = []
    capped = 0
    decoding = time.monotonic()
    for k, (a, b) in enumerate(clips, 1):
        clip = data[int(a * SR) : min(int(b * SR), len(data))]
        words, hit = decoder(clip, a, b)
        capped += hit
        if words:
            sentences.append(sentence(a, b, words))
        print(f"  clip {k}/{len(clips)} {a:.1f}-{b:.1f} s: {len(words)} words", flush=True)
    decode_s = time.monotonic() - decoding
    wall = time.monotonic() - started

    repo, revision, _ = MODELS[args.model]
    if args.slice_s:
        # The owner's floor (6 Oct): 2x realtime or faster, or no full runs.
        audio_s = clips[-1][1] if clips else 0.0
        meta = {"audio_s": round(audio_s, 1), "clips": len(clips), "load_s": round(load_s, 1),
                "decode_s": round(decode_s, 1), "wall_s": round(wall, 1),
                "x_realtime_decode": round(audio_s / decode_s, 2),
                "x_realtime_with_load": round(audio_s / wall, 2),
                "model": repo, "revision": revision, "device": dev, "dtype": decoder.dtype,
                "words": sum(len(s["tokens"]) for s in sentences), "commit": commit()}
        side = RUNS / args.set / f"{args.model}-slice.bench.json"
        side.write_text(json.dumps(meta, indent=2) + "\n")
        print(json.dumps(meta), flush=True)
        for s in sentences[:3]:
            print(f"  {s['start']:.1f}-{s['end']:.1f}: {s['text'][:200]}", flush=True)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "audio": str(audio), "engine": args.model, "model": f"{repo}@{revision}",
        "text": " ".join(s["text"] for s in sentences), "unclear": [], "sentences": sentences,
    }, ensure_ascii=False, indent=1) + "\n")
    meta = {
        "wall_s": round(wall, 1), "vad_s": round(vad_s, 1), "load_s": round(load_s, 1),
        "decode_s": round(decode_s, 1), "returncode": 0, "model": repo, "revision": revision,
        "device": dev, "dtype": decoder.dtype, "clips": len(clips),
        "settings": {
            "vad_max_s": whisper.VAD_MAX_S, "vad_pad_ms": whisper.VAD_PAD_MS,
            "vad_threshold": whisper.VAD_THRESHOLD, "vad_min_silence_ms": whisper.VAD_MIN_SILENCE_MS,
            "vad_min_speech_ms": whisper.VAD_MIN_SPEECH_MS, "decode": "greedy",
            **({"target_lang": MMS_LANG, "word_times": "ctc frames"} if args.model == "mms" else
               {"tgt_lang": "urd", "max_new_tokens": MAX_NEW_TOKENS, "clips_at_cap": capped,
                "word_times": "spread evenly over the clip"}),
        },
        "commit": commit(),
    }
    out.with_name(f"{out.stem}.bench.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{args.set}/{args.model}-r1: {len(sentences)} clips with text, {wall / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
