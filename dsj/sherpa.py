"""The sherpa engine: the code that may import sherpa_onnx, and nobody else.

Where parakeet-mlx needs Apple Silicon, this needs only a machine with wheels
for sherpa-onnx -- which on a phone means the proot container, because the
wheels are manylinux and Termux is bionic.

The NPU is deliberately not used. sherpa-onnx's QNN runtime is compiled out of
the published wheel (`provider="qnn"` returns "rebuild with
-DSHERPA_ONNX_ENABLE_QNN=ON"), and the CPU path measures faster on this phone
than the published NPU benchmark anyway: ~21x realtime against ~18x. The model
is memory-bandwidth-bound, so an accelerator on the same bus buys little.

Greedy decoding only. Beam search on parakeet TDT is reported to hallucinate or
return empty about a fifth of the time (sherpa-onnx#3267).
"""

from __future__ import annotations

__all__ = ["DEFAULT_MODEL", "available", "fingerprint_fields", "load", "wrap"]

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from dsj.alignment import AlignedToken

# A directory, not a hub id: sherpa loads four files that must agree with each
# other, so the unit that can be wrong is the directory.
DEFAULT_MODEL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"

SAMPLE_RATE = 16000

# sherpa reports token START times only, so a token's duration is the gap to the
# next one. The last token has no next, and this is what it gets instead.
_LAST_TOKEN_S = 0.08


def available() -> str | None:
    """None if the backend would import; otherwise the reason it will not.

    Unlike the mlx engines this does NOT stop at find_spec. A package can be
    installed and still fail to load its native library -- which is exactly how
    parakeet-mlx behaves on Linux aarch64, where mlx now publishes wheels but
    libmlx.so will not open. find_spec answers "is it installed"; the question
    that matters is "would it import". So: import it.

    The cost is one import on the machine that is about to use the engine
    anyway, which is the machine where that import was always going to happen.
    """
    import sys
    from importlib import import_module

    if "sherpa_onnx" in sys.modules:
        return None
    try:
        # import_module rather than an import statement: the module is the
        # probe's result, not a name this function uses, and both linters
        # agree once that is said in code instead of a suppression comment.
        import_module("sherpa_onnx")
    except ImportError as exc:
        return (
            f"sherpa-onnx will not import here: {exc}. Install it with "
            "`pip install sherpa-onnx` (manylinux wheels only -- inside a "
            "proot/glibc container on Android, not Termux itself)."
        )
    return None


def fingerprint_fields() -> dict[str, str]:
    """What must change for a checkpoint to be invalid.

    The wheel version pins the decoder; the model directory pins the weights.
    Either moving means tokens from an old run cannot be trusted alongside new
    ones, which is what the checkpoint is guarding against.
    """
    from importlib.metadata import version

    return {"sherpa_onnx_version": version("sherpa-onnx")}


@dataclass
class _LoadedSherpa:
    """A loaded recognizer, wrapped as a ChunkEngine.

    `OfflineRecognizer` is stateless per stream: a stream is created, fed,
    decoded and dropped, and nothing carries between chunks. That is the
    property the ChunkEngine protocol demands and the reason resume is exact
    rather than approximate.
    """

    recognizer: Any
    sample_rate: int = SAMPLE_RATE
    # One 10ms frame. Below this there is no feature frame to decode.
    min_chunk_samples: int = SAMPLE_RATE // 100

    def load_audio(self, path: Path) -> Any:
        """Decode `path` to mono float32 at the model's rate, via ffmpeg."""
        import numpy as np

        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
             "-f", "s16le", "-ac", "1", "-ar", str(self.sample_rate), "-"],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg could not decode {path}: {proc.stderr.decode()[:300]}"
            )
        return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0

    def decode(self, samples: Any) -> list[AlignedToken]:
        """One chunk's tokens, timed from the chunk's own start (t=0)."""
        import numpy as np

        stream = self.recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, np.ascontiguousarray(samples))
        self.recognizer.decode_stream(stream)
        result = stream.result

        texts = list(result.tokens)
        starts = list(result.timestamps)
        if not texts:
            return []
        # Guard rather than zip-and-hope: a mismatch here would silently shift
        # every timestamp, which is the kind of wrong that looks right.
        if len(starts) != len(texts):
            raise RuntimeError(
                f"sherpa returned {len(texts)} tokens and {len(starts)} timestamps"
            )

        out: list[AlignedToken] = []
        for i, (text, start) in enumerate(zip(texts, starts, strict=True)):
            nxt = starts[i + 1] if i + 1 < len(starts) else start + _LAST_TOKEN_S
            out.append(
                AlignedToken(
                    id=i,
                    text=text,
                    start=float(start),
                    duration=max(float(nxt) - float(start), 0.0),
                )
            )
        return out


def wrap(recognizer: Any) -> _LoadedSherpa:
    """Wrap an already-built recognizer (or a test double) as a ChunkEngine."""
    return _LoadedSherpa(recognizer=recognizer)


def load(model_id: str = DEFAULT_MODEL) -> _LoadedSherpa:
    """Build the recognizer from a model DIRECTORY. The expensive call."""
    import sherpa_onnx  # pyright: ignore[reportMissingImports]  # no stubs, and absent from the base env

    d = Path(model_id).expanduser()
    if not d.is_dir():
        raise FileNotFoundError(f"sherpa model directory not found: {d}")

    def _one(*names: str) -> str:
        for n in names:
            p = d / n
            if p.exists():
                return str(p)
        raise FileNotFoundError(f"{d} has none of {names}")

    return wrap(
        cast("Any", sherpa_onnx.OfflineRecognizer).from_transducer(
            encoder=_one("encoder.int8.onnx", "encoder.onnx"),
            decoder=_one("decoder.int8.onnx", "decoder.onnx"),
            joiner=_one("joiner.int8.onnx", "joiner.onnx"),
            tokens=_one("tokens.txt"),
            num_threads=6,  # 8 buys ~7% more; 6 leaves the phone usable
            model_type="nemo_transducer",
            decoding_method="greedy_search",
        )
    )
