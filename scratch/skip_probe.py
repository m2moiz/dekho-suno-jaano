#!/usr/bin/env python3
"""Why parakeet skips 11 to 46 s of speech inside a chunk (#228).

    uv run python scratch/skip_probe.py why  [AUDIO]   # one window, every suspect
    uv run python scratch/skip_probe.py sweep [AUDIO]  # chunk length over the whole file
    uv run python scratch/skip_probe.py fill AUDIO frames|audio GAP_S  # two re-reads compared
    uv run python scratch/skip_probe.py speed AUDIO [REPS]  # dsj's decode with and without

`why` decodes the windows #228 names (0 to 60 s, 0 to 120 s, 260 to 330 s of
the Earnings-22 call) and, for each, tries one suspect at a time, so the one
that makes the gap close is the cause:

- `greedy`: dsj's own decode (parakeet-mlx's greedy TDT, the default).
- `beam`: parakeet-mlx's beam search, same encoder output.
- `state`: the same encoder output, the gap's frames decoded greedily again
  four ways: from the decoder state the first pass had there (`carried`,
  which should reproduce the gap), from a reset state (`fresh`), and with
  only the last token or only the LSTM state kept. If `fresh` reads the gap
  and `carried` does not, the decoder's state is what stopped it, not the
  encoder's output.
- `local`: the encoder with local attention (256 frames each side, about
  20 s), which NeMo recommends for long audio, instead of full attention.

`sweep` runs dsj's chunk loop (dsj.chunking.transcribe_chunked) over the
whole file at several CHUNK_S values and prints the seconds of speech left
in gaps over GAP_S, the token count and the decode time, and writes each as
a transcript under scratch/skip_probe/ for scratch/accuracy/score.py.

Speech here is loudness, the way dsj.suno reads silence: a gap counts as
over speech when its median 0.1 s frame is above SILENCE_DB.
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
CALL = REPO / "scratch" / "accuracy" / "earnings_call" / "earnings_call.wav"
OUT = REPO / "scratch" / "skip_probe"
GAP_S = 4.0
WINDOWS = [(0.0, 60.0), (0.0, 120.0), (260.0, 330.0), (20.0, 65.0), (290.0, 320.0)]


def gaps(starts: list[float], lo: float, hi: float) -> list[tuple[float, float]]:
    """Every stretch over GAP_S with no token start in it, [lo, hi] edges included."""
    edges = [lo, *sorted(starts), hi]
    return [(a, b) for a, b in itertools.pairwise(edges) if b - a > GAP_S]


def speech_gaps(
    found: list[tuple[float, float]], frame_db: np.ndarray, frame_s: float
) -> list[tuple[float, float]]:
    from dsj.suno import SILENCE_DB

    out = []
    for a, b in found:
        seg = frame_db[int(a / frame_s) : int(b / frame_s)]
        if len(seg) and float(np.median(seg)) > SILENCE_DB:
            out.append((round(a, 2), round(b, 2)))
    return out


def fmt(gs: list[tuple[float, float]]) -> str:
    return ", ".join(f"{a:.1f}-{b:.1f}" for a, b in gs) or "none"


def cmd_why(audio: Path) -> None:
    import mlx.core as mx
    from parakeet_mlx import Beam, DecodingConfig, Greedy
    from parakeet_mlx.audio import get_logmel

    from dsj import parakeet
    from dsj.media import loudness

    engine = parakeet.load(parakeet.DEFAULT_MODEL)
    model: Any = engine.model
    data = engine.load_audio(audio)
    rate = engine.sample_rate
    ratio = float(model.time_ratio)
    frame_db = loudness(audio, 0.1)

    def encode(lo: float, hi: float) -> Any:
        mel = get_logmel(data[int(lo * rate) : int(hi * rate)], model.preprocessor_config)
        if len(mel.shape) == 2:
            mel = mx.expand_dims(mel, 0)
        features, _ = model.encoder(mel)
        mx.eval(features)
        return features

    def greedy(features: Any, offset: float, first: int = 0) -> list[float]:
        toks, _ = model.decode(features[:, first:], config=DecodingConfig(decoding=Greedy()))
        return [offset + first * ratio + t.start for t in toks[0]]

    def from_state(features: Any, f0: int, f1: int, last: Any, hidden: Any) -> int:
        """Tokens a greedy decode of frames [f0, f1) emits from the given state."""
        toks, _ = model.decode(
            features[:, f0:f1], last_token=[last], hidden_state=[hidden],
            config=DecodingConfig(decoding=Greedy()),
        )
        return len(toks[0])

    report: dict[str, Any] = {}
    for lo, hi in WINDOWS:
        key = f"{lo:.0f}-{hi:.0f}"
        row: dict[str, Any] = {}
        feats = encode(lo, hi)
        g = greedy(feats, lo)
        sg = speech_gaps(gaps(g, lo, hi), frame_db, 0.1)
        row["greedy"] = {"tokens": len(g), "speech_gaps": sg}

        beam_cfg = DecodingConfig(decoding=Beam(beam_size=5))
        toks, _ = model.decode(feats, config=beam_cfg)
        b = [lo + t.start for t in toks[0]]
        row["beam"] = {"tokens": len(b), "speech_gaps": speech_gaps(gaps(b, lo, hi), frame_db, 0.1)}

        fresh: list[dict[str, Any]] = []
        for a, z in sg:
            f0 = round((a - lo) / ratio) + 1
            f1 = round((z - lo) / ratio)
            # The decoder's state as it stood just after the last token before
            # the gap: decode up to that frame and keep what it hands back.
            before, state = model.decode(features := feats[:, :f0],
                                         config=DecodingConfig(decoding=Greedy()))
            last = before[0][-1].id if before[0] else None
            hidden = state[0]
            fresh.append(
                {
                    "gap": [a, z],
                    "carried": from_state(feats, f0, f1, last, hidden),
                    "fresh": from_state(feats, f0, f1, None, None),
                    "last_token_only": from_state(feats, f0, f1, last, None),
                    "lstm_state_only": from_state(feats, f0, f1, None, hidden),
                }
            )
            del features
        row["state"] = fresh

        model.encoder.set_attention_model("rel_pos_local_attn", (256, 256))
        lf = encode(lo, hi)
        model.encoder.set_attention_model("rel_pos")
        lg = greedy(lf, lo)
        row["local"] = {"tokens": len(lg), "speech_gaps": speech_gaps(gaps(lg, lo, hi), frame_db, 0.1)}

        # The audio where the gap starts: loudness either side of it.
        row["level_db"] = [
            {
                "gap": [a, z],
                "before_5s": round(float(np.median(frame_db[int((a - 5) / 0.1) : int(a / 0.1)])), 1),
                "after_5s": round(float(np.median(frame_db[int(a / 0.1) : int((a + 5) / 0.1)])), 1),
                "gap_median": round(float(np.median(frame_db[int(a / 0.1) : int(z / 0.1)])), 1),
            }
            for a, z in sg
        ]
        report[key] = row
        print(key, json.dumps(row), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "why.json").write_text(json.dumps(report, indent=1))


def cmd_sweep(audio: Path, chunks: list[float]) -> None:
    from dsj import parakeet
    from dsj.chunking import transcribe_chunked
    from dsj.media import loudness
    from dsj.suno import OVERLAP_S

    engine = parakeet.load(parakeet.DEFAULT_MODEL)
    data = engine.load_audio(audio)
    rate = engine.sample_rate
    total = len(data) / rate
    frame_db = loudness(audio, 0.1)
    OUT.mkdir(parents=True, exist_ok=True)
    for chunk_s in chunks:
        overlap = min(OVERLAP_S, chunk_s / 4)
        t0 = time.monotonic()
        result = transcribe_chunked(engine, data, chunk_s=chunk_s, overlap_s=overlap)
        wall = time.monotonic() - t0
        starts = [t.start for s in result.sentences for t in s.tokens]
        sg = speech_gaps(gaps(starts, 0.0, total), frame_db, 0.1)
        sentences = [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "tokens": [{"t": t.start, "w": t.text} for t in s.tokens],
            }
            for s in result.sentences
        ]
        name = OUT / f"{audio.stem}-chunk{chunk_s:g}.json"
        name.write_text(json.dumps({"sentences": sentences, "text": result.text}))
        print(
            f"chunk {chunk_s:5.0f}s overlap {overlap:4.1f}s: {len(starts):6d} tokens, "
            f"{wall:6.1f} s wall, {len(sg)} speech gaps over {GAP_S:g} s "
            f"totalling {sum(b - a for a, b in sg):6.1f} s: {fmt(sg)}  -> {name.relative_to(REPO)}",
            flush=True,
        )


class Filled:
    """A parakeet engine whose decode reads each in-chunk gap over `gap_s` again.

    `how` is "frames" (the chunk's own encoder output from the gap's first
    frame, greedy, from a reset decoder state) or "audio" (the gap's samples
    decoded alone, through the engine's ordinary decode). Counts what it did.
    """

    def __init__(self, engine: Any, how: str, gap_s: float) -> None:
        self.engine = engine
        self.how = how
        self.gap_s = gap_s
        self.sample_rate = engine.sample_rate
        self.min_chunk_samples = engine.min_chunk_samples
        self.load_audio = engine.load_audio
        self.tried = 0
        self.filled = 0
        self.added = 0

    def _holes(self, toks: list[Any], lo: float, hi: float) -> list[tuple[float, float]]:
        ends = [lo] + [t.start + t.duration for t in toks]
        starts = [t.start for t in toks] + [hi]
        return [(a, b) for a, b in zip(ends, starts, strict=True) if b - a > self.gap_s]

    def decode(self, samples: Any) -> list[Any]:
        from dsj.alignment import AlignedToken

        rate = self.sample_rate
        hi = len(samples) / rate
        if self.how == "audio":

            def read(a: float, b: float, depth: int) -> list[Any]:
                toks = self.engine.decode(samples[int(a * rate) : int(b * rate)])
                toks = [
                    AlignedToken(id=t.id, text=t.text, start=t.start + a,
                                 duration=t.duration, confidence=t.confidence)
                    for t in toks
                ]
                if depth >= 3:
                    return toks
                out = list(toks)
                for x, y in self._holes(toks, a, b):
                    if x == a and depth > 0:
                        continue
                    if (y - x) * rate < self.min_chunk_samples:
                        continue
                    self.tried += 1
                    got = read(x, y, depth + 1)
                    if got:
                        self.filled += 1
                        self.added += len(got)
                    out.extend(got)
                return sorted(out, key=lambda t: t.start)

            return read(0.0, hi, 0)

        import mlx.core as mx
        from parakeet_mlx import DecodingConfig, Greedy
        from parakeet_mlx.audio import get_logmel

        model = self.engine.model
        ratio = float(model.time_ratio)
        mel = get_logmel(samples, model.preprocessor_config)
        if len(mel.shape) == 2:
            mel = mx.expand_dims(mel, 0)
        features, _ = model.encoder(mel)
        mx.eval(features)
        cfg = DecodingConfig(decoding=Greedy())

        def frames(f0: int, f1: int, depth: int) -> list[Any]:
            got, _ = model.decode(features[:, f0:f1], config=cfg)
            toks = [
                AlignedToken(id=t.id, text=t.text, start=t.start + f0 * ratio,
                             duration=t.duration, confidence=t.confidence)
                for t in got[0]
            ]
            if depth >= 3:
                return toks
            out = list(toks)
            for x, y in self._holes(toks, f0 * ratio, f1 * ratio):
                if x == f0 * ratio:
                    continue  # the decode started fresh here already
                self.tried += 1
                more = frames(round(x / ratio), round(y / ratio), depth + 1)
                if more:
                    self.filled += 1
                    self.added += len(more)
                out.extend(more)
            return sorted(out, key=lambda t: t.start)

        return frames(0, int(features.shape[1]), 0)


def cmd_fill(audio: Path, how: str, gap_s: float, chunk_s: float) -> None:
    from dsj import parakeet
    from dsj.chunking import transcribe_chunked
    from dsj.media import loudness
    from dsj.suno import OVERLAP_S

    engine = Filled(parakeet.load(parakeet.DEFAULT_MODEL), how, gap_s)
    data = engine.load_audio(audio)
    total = len(data) / engine.sample_rate
    frame_db = loudness(audio, 0.1)
    t0 = time.monotonic()
    result = transcribe_chunked(engine, data, chunk_s=chunk_s, overlap_s=OVERLAP_S)
    wall = time.monotonic() - t0
    starts = [t.start for s in result.sentences for t in s.tokens]
    sg = speech_gaps(gaps(starts, 0.0, total), frame_db, 0.1)
    sentences = [
        {"start": s.start, "end": s.end, "text": s.text,
         "tokens": [{"t": t.start, "w": t.text} for t in s.tokens]}
        for s in result.sentences
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    name = OUT / f"{audio.stem}-fill-{how}-{gap_s:g}.json"
    name.write_text(json.dumps({"sentences": sentences, "text": result.text}))
    print(
        f"fill {how} gap>{gap_s:g}s: {len(starts)} tokens, {wall:.1f} s wall, "
        f"{engine.tried} gaps tried, {engine.filled} filled, {engine.added} tokens added, "
        f"{len(sg)} speech gaps left totalling {sum(b - a for a, b in sg):.1f} s: {fmt(sg)}"
        f"  -> {name.relative_to(REPO)}",
        flush=True,
    )


def cmd_speed(audio: Path, reps: int) -> None:
    """dsj's chunk loop with and without the gap re-read (#228), interleaved, one process.

    "before" decodes each chunk once (_decode_once); "after" is dsj's decode.
    Interleaved, and in alternating order, so a machine that slows down
    partway slows both alike.
    """
    from statistics import median

    from dsj import parakeet
    from dsj.chunking import transcribe_chunked
    from dsj.suno import CHUNK_S, OVERLAP_S

    engine = parakeet.load(parakeet.DEFAULT_MODEL)
    data = engine.load_audio(audio)

    class Once:
        sample_rate = engine.sample_rate
        min_chunk_samples = engine.min_chunk_samples

        def decode(self, samples: Any) -> Any:
            return engine._decode_once(samples)

    # One warm-up each, untimed: the first decode of a shape compiles kernels.
    transcribe_chunked(Once(), data, chunk_s=CHUNK_S, overlap_s=OVERLAP_S)
    transcribe_chunked(engine, data, chunk_s=CHUNK_S, overlap_s=OVERLAP_S)
    walls: dict[str, list[float]] = {"before": [], "after": []}
    tokens: dict[str, int] = {}
    pair: list[tuple[str, Any]] = [("before", Once()), ("after", engine)]
    for rep in range(reps):
        # Each goes first on alternate reps, so a machine warming up or
        # throttling partway through a pair does not always land on one side.
        for name, eng in pair if rep % 2 == 0 else pair[::-1]:
            t0 = time.monotonic()
            result = transcribe_chunked(eng, data, chunk_s=CHUNK_S, overlap_s=OVERLAP_S)
            walls[name].append(time.monotonic() - t0)
            tokens[name] = sum(len(s.tokens) for s in result.sentences)
    total = len(data) / engine.sample_rate
    for name, w in walls.items():
        print(
            f"{name}: {tokens[name]} tokens, wall {', '.join(f'{x:.1f}' for x in w)} s, "
            f"median {median(w):.1f} s = {total / median(w):.1f}x realtime"
        )
    print(f"after / before: {median(walls['after']) / median(walls['before']):.3f}")


def main(argv: list[str]) -> int:
    cmd = argv[0]
    audio = Path(argv[1]) if len(argv) > 1 else CALL
    if cmd == "why":
        cmd_why(audio)
    elif cmd == "sweep":
        chunks = [float(x) for x in argv[2:]] or [120.0, 90.0, 60.0, 45.0, 30.0]
        cmd_sweep(audio, chunks)
    elif cmd == "speed":
        cmd_speed(audio, int(argv[2]) if len(argv) > 2 else 3)
    elif cmd == "fill":
        cmd_fill(audio, argv[2], float(argv[3]), float(argv[4]) if len(argv) > 4 else 120.0)
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
