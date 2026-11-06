#!/usr/bin/env python3
"""Run a model dsj has no engine for on one of #184's reference sets, in the shape score.py reads (#235, #281).

    uv run --with transformers --with sentencepiece --with accelerate \
        python scratch/accuracy/other_models.py {mms,seamless} --set {podcast,urdu,earnings}
    uv run --with sherpa-onnx==1.13.7 --with sherpa-onnx-core==1.13.7 \
        python -I scratch/accuracy/other_models.py {dolphin,omni1b} --set {podcast,urdu,earnings}
    uv run --with onnxruntime==1.31.0 \
        python -I scratch/accuracy/other_models.py {indicconformer_ctc,indicconformer_rnnt} --set {podcast,urdu}

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
   - `dolphin` (#281): DataoceanAI's Dolphin small, sherpa-onnx's int8 CTC
     export, `OfflineRecognizer.from_dolphin_ctc`, greedy, on the CPU. The
     CTC-only export takes no language, so it cannot be told Urdu.
   - `omni1b` (#281): Meta's Omnilingual ASR CTC 1B v2, sherpa-onnx's int8
     export, `from_omnilingual_asr_ctc`, greedy, on the CPU. Language-free;
     its 40 s input cap is above VAD_MAX_S.
   - `indicconformer_ctc` and `indicconformer_rnnt` (#281): AI4Bharat's
     IndicConformer 600M multilingual with its Urdu head, from an int8 ONNX
     copy (`yashwork-byte/indic-conformer-600m-int8-onnx`). Its card loads it
     through `trust_remote_code`, whose `from_pretrained` downloads into the
     shared Hugging Face cache; `IndicConformer` below is that remote code's
     `forward` written out (read at the pinned revision): the TorchScript
     preprocessor, the ONNX encoder, then the CTC head masked to Urdu's
     vocabulary or the RNN-T joint with the `ur` post-net, both greedy.
   Word times: from sherpa's token starts for the two sherpa models and from
   the CTC frames (80 ms) for `indicconformer_ctc`; spread evenly over the
   clip where a model gives none (`indicconformer_rnnt`) or its tokens do not
   rebuild its text.
4. Written to scratch/accuracy/runs/<set>/<model>-r<N>.json, one sentence per
   clip with its start and end, and a .bench.json beside it: wall time from
   process start (imports and model load included, as a `dsj suno` run's
   wall time is), VAD, load and decode seconds, the load average, model and
   revision, device, dtype, settings.

The owner's ruling of 9 Oct (#281): no run is stopped for being slow except
by a sanity cap, wall time past `--max-wall-x` (2.5) times the recording's
length. A capped run writes no transcript; its bench file records
`too_slow` with the speed it had reached (audio done over wall time).

`--slice-s 240` times only the clips starting in the first 240 s and writes
<model>-slice.bench.json: the owner's floor (6 Oct) is 2x realtime or faster,
and a model under it gets no full runs.

Downloads land in scratch/models/dl/<repo> (`local_dir`), never the shared
~/.cache/huggingface, so they can be deleted alone. Waits, like run.py, for no
`dsj suno` running and 30% memory free before loading.
"""

from __future__ import annotations

import time

STARTED = time.monotonic()  # before the imports: they are part of a run's cost

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from importlib.util import find_spec  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

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
    "dolphin": ("csukuangfj/sherpa-onnx-dolphin-small-ctc-multi-lang-int8-2025-04-02",
                "c8b6689509acfcd744c04e5e169164f9ac4cae32", ["model.int8.onnx", "tokens.txt", "README.md"]),
    "omni1b": ("csukuangfj2/sherpa-onnx-omnilingual-asr-1600-languages-1B-ctc-v2-int8-2026-02-05",
               "5243e02858d1428b8fbeeb5f7f1cc6fccf4d9433", ["model.int8.onnx", "tokens.txt", "README.md", "LICENSE"]),
    "indicconformer_ctc": ("yashwork-byte/indic-conformer-600m-int8-onnx", "9c590ef62f537c30de47df62e525539938549f13",
                           ["config.json", "README.md", "model_onnx.py", "assets/*"]),
}
MODELS["indicconformer_rnnt"] = MODELS["indicconformer_ctc"]
# CPU threads for the ONNX models (#281). The M2 has 4 performance cores.
THREADS = 4
MMS_LANG = "urd-script_arabic"
MAX_NEW_TOKENS = 512
SR = whisper.SAMPLE_RATE


def fetch(which: str) -> Path:
    from huggingface_hub import snapshot_download

    repo, revision, patterns = MODELS[which]
    target = DL / repo.replace("/", "--")
    # Fetched before the timed run (--fetch-only), so a timed run does not
    # spend its wall clock asking the hub whether the files changed.
    marker = target / f".fetched-{revision[:8]}"
    if marker.exists():
        return target
    snapshot_download(repo_id=repo, revision=revision, local_dir=target, allow_patterns=patterns)
    marker.write_text(revision + "\n")
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


def from_tokens(tokens: list[str], starts: list[float], text: str, offset: float,
                end: float) -> tuple[list[tuple[str, float, float]], str]:
    """(word, start, end) from token starts where the tokens rebuild `text`'s words, else spread evenly.

    A token opening with a space or SentencePiece's \u2581 starts a word. A word
    ends where the next one starts (the clip's end for the last), since CTC
    gives a token's first frame only.
    """
    words: list[tuple[str, float]] = []
    for token, t in zip(tokens, starts, strict=False):
        opens = token[:1] in (" ", "\u2581")
        piece = token.replace("\u2581", " ").strip()
        if not piece:
            continue
        if opens or not words:
            words.append((piece, offset + t))
        else:
            words[-1] = (words[-1][0] + piece, words[-1][1])
    if not tokens or len(tokens) != len(starts) or [w for w, _ in words] != text.split():
        return spread(text, offset, end), "spread evenly over the clip"
    ends = [t for _, t in words[1:]] + [end]
    return [(w, t, max(t, e)) for (w, t), e in zip(words, ends, strict=True)], "token starts"


class Sherpa:
    """Dolphin small or Omnilingual 1B, sherpa-onnx int8 CTC, greedy, CPU (#281)."""

    def __init__(self, folder: Path, which: str) -> None:
        import sherpa_onnx

        build = (sherpa_onnx.OfflineRecognizer.from_dolphin_ctc if which == "dolphin"
                 else sherpa_onnx.OfflineRecognizer.from_omnilingual_asr_ctc)
        self.recognizer: Any = build(model=str(folder / "model.int8.onnx"), tokens=str(folder / "tokens.txt"),
                                     num_threads=THREADS)
        self.dtype = "int8"
        self.version = sherpa_onnx.__version__
        self.word_times: set[str] = set()

    def __call__(self, clip: Any, offset: float, end: float) -> tuple[list[tuple[str, float, float]], bool]:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(SR, clip)
        self.recognizer.decode_stream(stream)
        result = stream.result
        words, how = from_tokens(list(result.tokens), list(result.timestamps), result.text, offset, end)
        self.word_times.add(how)
        return words, False


class IndicConformer:
    """IndicConformer 600M int8 with its Urdu head: the card's remote-code `forward`, written out (#281).

    Read from model_onnx.py at the pinned revision: the TorchScript
    preprocessor (80-bin log-mel), the ONNX encoder, then either the CTC
    decoder's log-probs masked to `language_masks["ur"]` and collapsed
    greedily, or the RNN-T greedy loop through `rnnt_decoder`, `joint_enc`,
    `joint_pred`, `joint_pre_net` and `joint_post_net_ur`, at most
    RNNT_MAX_SYMBOLS per frame. BLANK_ID and SOS are 256 in its config.
    """

    LANG = "ur"
    FRAME_S = 0.08  # the remote code's default FRAME_DURATION_MS, which its config does not set

    def __init__(self, folder: Path, decoding: str) -> None:
        import onnxruntime as ort
        import torch

        self.torch = torch
        self.decoding = decoding
        assets = folder / "assets"
        config = json.loads((folder / "config.json").read_text())
        self.blank, self.sos = int(config["BLANK_ID"]), int(config["SOS"])
        self.max_symbols = int(config["RNNT_MAX_SYMBOLS"])
        self.layers, self.hidden = int(config["PRED_RNN_LAYERS"]), int(config["PRED_RNN_HIDDEN_DIM"])
        self.preprocessor = torch.jit.load(str(assets / "preprocessor.ts"), map_location="cpu")
        options = ort.SessionOptions()
        options.intra_op_num_threads = THREADS
        names = ["encoder", "ctc_decoder"] if decoding == "ctc" else [
            "encoder", "rnnt_decoder", "joint_enc", "joint_pred", "joint_pre_net", f"joint_post_net_{self.LANG}"]
        self.sessions = {n: ort.InferenceSession(str(assets / f"{n}.onnx"), options,
                                                 providers=["CPUExecutionProvider"]) for n in names}
        self.vocab = json.loads((assets / "vocab.json").read_text())[self.LANG]
        self.mask = json.loads((assets / "language_masks.json").read_text())[self.LANG]
        self.dtype = "int8 encoder"
        self.version = f"onnxruntime {ort.__version__}, torch {torch.__version__}"
        self.word_times = {"ctc frames"} if decoding == "ctc" else {"spread evenly over the clip"}

    def __call__(self, clip: Any, offset: float, end: float) -> tuple[list[tuple[str, float, float]], bool]:
        torch = self.torch
        wav = torch.from_numpy(np.ascontiguousarray(clip)).unsqueeze(0)
        with torch.inference_mode():
            signal, length = self.preprocessor(input_signal=wav, length=torch.tensor([wav.shape[-1]]))
        encoded, lengths = self.sessions["encoder"].run(
            ["outputs", "encoded_lengths"], {"audio_signal": signal.numpy(), "length": length.numpy()})
        if self.decoding == "ctc":
            return self._ctc(encoded, int(lengths[0]), offset, end), False
        return spread(self._rnnt(encoded), offset, end), False

    def _ctc(self, encoded: Any, frames: int, offset: float, end: float) -> list[tuple[str, float, float]]:
        logprobs = self.sessions["ctc_decoder"].run(["logprobs"], {"encoder_output": encoded})[0]
        path = np.argmax(logprobs[0, :frames][:, self.mask], axis=-1)
        # Greedy CTC: a token starts where the path changes to it from anything else.
        tokens: list[str] = []
        starts: list[float] = []
        previous = -1
        for f, tok in enumerate(path.tolist()):
            if tok != previous and tok != self.blank:
                tokens.append(self.vocab[tok])
                starts.append(f * self.FRAME_S)
            previous = tok
        text = "".join(tokens).replace("\u2581", " ").strip()
        words, _ = from_tokens(tokens, starts, text, offset, end)
        return words

    def _rnnt(self, encoded: Any) -> str:
        s = self.sessions
        joint_enc = s["joint_enc"].run(["output"], {"input": encoded.transpose(0, 2, 1)})[0]
        hyp = [self.sos]
        state = (np.zeros((self.layers, 1, self.hidden), dtype=np.float32),
                 np.zeros((self.layers, 1, self.hidden), dtype=np.float32))
        for t in range(joint_enc.shape[1]):
            f = joint_enc[:, t : t + 1, :]
            for _ in range(self.max_symbols):
                g, _, h0, h1 = s["rnnt_decoder"].run(
                    ["outputs", "prednet_lengths", "states", "162"],
                    {"targets": np.array([[hyp[-1]]], dtype=np.int32), "target_length": np.array([1], dtype=np.int32),
                     "states.1": state[0], "onnx::Slice_3": state[1]})
                g = s["joint_pred"].run(["output"], {"input": g.transpose(0, 2, 1)})[0]
                joint = s["joint_pre_net"].run(["output"], {"input": f + g})[0]
                logits = s[f"joint_post_net_{self.LANG}"].run(["output"], {"input": joint})[0]
                token = int(np.argmax(logits.reshape(-1)))
                if token == self.blank:
                    break
                hyp.append(token)
                state = (h0, h1)
        return "".join(self.vocab[x] for x in hyp if x != self.sos).replace("\u2581", " ").strip()


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
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--max-wall-x", type=float, default=2.5,
                        help="stop once wall time passes this many times the recording's length (#281)")
    args = parser.parse_args()

    out = RUNS / args.set / f"{args.model}-r{args.run}.json"
    if out.exists() and not args.fetch_only and not args.slice_s:
        print(f"{out} already there", flush=True)
        return 0
    folder = fetch(args.model)
    if args.fetch_only:
        return 0

    from mlx_whisper.audio import load_audio

    waited = wait_turn()
    load_before = [round(x, 1) for x in os.getloadavg()]
    vad_started = time.monotonic()
    audio = SETS[args.set]
    data = np.asarray(load_audio(str(audio), sr=SR), dtype=np.float32)  # an mx.array otherwise
    duration = len(data) / SR
    spans, probs = whisper._speech(data)
    clips = whisper.speech_segments(spans, whisper.VAD_MAX_S, probs, whisper.VAD_FRAME_S)
    if args.slice_s:
        clips = [c for c in clips if c[0] < args.slice_s]
    vad_s = time.monotonic() - vad_started

    dev = "cpu" if args.model in ("dolphin", "omni1b") or args.model.startswith("indicconformer") else device()
    loaded = time.monotonic()
    decoder: Any
    if args.model == "mms":
        decoder = Mms(folder, dev)
    elif args.model == "seamless":
        decoder = Seamless(folder, dev)
    elif args.model in ("dolphin", "omni1b"):
        decoder = Sherpa(folder, args.model)
    else:
        decoder = IndicConformer(folder, args.model.removeprefix("indicconformer_"))
    load_s = time.monotonic() - loaded

    sentences: list[dict[str, Any]] = []
    capped = 0
    too_slow: dict[str, Any] | None = None
    decoding = time.monotonic()
    for k, (a, b) in enumerate(clips, 1):
        clip = data[int(a * SR) : min(int(b * SR), len(data))]
        words, hit = decoder(clip, a, b)
        capped += hit
        if words:
            sentences.append(sentence(a, b, words))
        wall = time.monotonic() - STARTED - waited
        print(f"  clip {k}/{len(clips)} {a:.1f}-{b:.1f} s: {len(words)} words ({b / wall:.2f}x so far)", flush=True)
        # The owner's sanity cap (#281): nothing else stops a run for being slow.
        if not args.slice_s and wall > duration * args.max_wall_x:
            too_slow = {"rule": "cap", "speed": round(b / wall, 2), "audio_done_s": round(b, 1), "wall_s": round(wall)}
            print(f"  past the {args.max_wall_x}x wall cap: {too_slow}", flush=True)
            break
    decode_s = time.monotonic() - decoding
    wall = time.monotonic() - STARTED - waited

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
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps(meta, indent=2) + "\n")
        print(json.dumps(meta), flush=True)
        for s in sentences[:3]:
            print(f"  {s['start']:.1f}-{s['end']:.1f}: {s['text'][:200]}", flush=True)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    if not too_slow:
        out.write_text(json.dumps({
            "audio": str(audio), "engine": args.model, "model": f"{repo}@{revision}",
            "text": " ".join(s["text"] for s in sentences), "unclear": [], "sentences": sentences,
        }, ensure_ascii=False, indent=1) + "\n")
    if args.model == "mms":
        extra: dict[str, Any] = {"target_lang": MMS_LANG, "word_times": "ctc frames"}
    elif args.model == "seamless":
        extra = {"tgt_lang": "urd", "max_new_tokens": MAX_NEW_TOKENS, "clips_at_cap": capped,
                 "word_times": "spread evenly over the clip"}
    else:
        extra = {"threads": THREADS, "runtime": decoder.version, "word_times": sorted(decoder.word_times),
                 **({"language": IndicConformer.LANG} if args.model.startswith("indicconformer") else
                    {"language": "none: the export takes none"})}
    meta = {
        "wall_s": round(wall, 1), "waited_s": round(waited, 1), "audio_s": round(duration, 1),
        # A stopped run did only part of the audio: its speed is what it did.
        "x_realtime": round((too_slow["audio_done_s"] if too_slow else duration) / wall, 2),
        "vad_s": round(vad_s, 1), "load_s": round(load_s, 1),
        "decode_s": round(decode_s, 1), "returncode": 0, "model": repo, "revision": revision,
        "device": dev, "dtype": decoder.dtype, "clips": len(clips),
        "settings": {
            "vad_max_s": whisper.VAD_MAX_S, "vad_pad_ms": whisper.VAD_PAD_MS,
            "vad_threshold": whisper.VAD_THRESHOLD, "vad_min_silence_ms": whisper.VAD_MIN_SILENCE_MS,
            "vad_min_speech_ms": whisper.VAD_MIN_SPEECH_MS, "decode": "greedy", "max_wall_x": args.max_wall_x,
            # Silero runs as ONNX when onnxruntime imports (dsj.whisper._speech), as TorchScript otherwise.
            "vad_backend": "onnx" if find_spec("onnxruntime") else "torchscript",
            **extra,
        },
        "loadavg_before": load_before, "loadavg_after": [round(x, 1) for x in os.getloadavg()],
        "commit": commit(), **({"too_slow": too_slow} if too_slow else {}),
    }
    out.with_name(f"{out.stem}.bench.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{args.set}/{args.model}-r{args.run}: {len(sentences)} clips with text, {wall / 60:.1f} min, "
          f"{meta['x_realtime']}x realtime" + (", stopped at the cap" if too_slow else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
