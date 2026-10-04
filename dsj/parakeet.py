"""The parakeet engine: the code that may import parakeet-mlx, and nobody else.

Extracted from suno.py and chunking.py so the default engine finally gets the
treatment whisper.py and diarize.py always had -- one backend, one leaf module,
lazy imports behind an availability probe. The AST test in
tests/test_core_is_portable.py is what holds this line: no core module may
import parakeet_mlx, mlx, or any other backend, ever again.

Module top is backend-free ON PURPOSE. The registry imports this module before
calling available(), so a top-level `import parakeet_mlx` would crash the
resolution this module exists to make safe. Every backend import lives inside
the function that needs it, which is also what lets the test suite patch the
source attributes (parakeet_mlx.from_pretrained and friends) and have the
function-local imports pick the patches up.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_MODEL",
    "MEASURES_END_AND_CONFIDENCE",
    "REREAD_DEPTH",
    "REREAD_GAP_S",
    "available",
    "fingerprint_fields",
    "load",
    "wrap",
]

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol, cast

from dsj.alignment import AlignedToken

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from parakeet_mlx.alignment import AlignedResult as UpstreamResult

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"

# Whether a token's `end` and `confidence` are the decoder's own, and so worth
# writing into the transcript (dsj/suno.py reads this). They are here: TDT
# decodes frame by frame, so a token's duration is the frames it was emitted
# over, and its confidence is one minus the normalised entropy of the
# decoder's distribution at that step (parakeet_mlx/parakeet.py:579-584).
MEASURES_END_AND_CONFIDENCE = True

# A gap after a token longer than REREAD_GAP_S, inside one decode, is decoded
# again on its own (#228). parakeet's greedy decoder can stop writing anything
# after a sentence's full stop and stay stopped for 11 to 46 s of speech: on
# the Earnings-22 call #228 measured, all six such gaps follow a "." token.
# It is the decoder's state, not what the encoder heard: on 0 to 60 s of that
# call the gap at 27.0 to 40.1 s gets 0 tokens decoded from the state the
# first pass had there and 94 from a reset state, over the same encoder
# output (260 to 330 s: 0 against 61). A shorter chunk does not cure it: 90 s
# chunks skip 144 s of speech against 118 s at 120 s, and only 30 s chunks
# skip none, at 65% more decode time (scratch/skip_probe.py why and sweep).
# Decoding a gap's own audio starts the decoder afresh. On the call, missed
# words fall from 6.6% to 0.7% at 4 s, against whisper's 1.3%; 2 s adds 0.1
# point for twice the gaps decoded. The cost is the gaps' own audio decoded
# once more: 7 gaps, 137 s, added 5.1 s to 61.8 s of decoding on the call;
# scratch/clip360.wav has no gap over 4 s and decodes nothing more. A gap
# with nothing in it costs one short decode that returns nothing (the
# podcast's 60 s of silence still holds no word). REREAD_DEPTH bounds the
# gaps found inside a gap that are read again in turn.
REREAD_GAP_S = 4.0
REREAD_DEPTH = 3


def available() -> str | None:
    """None if the backend would import; otherwise the reason it will not.

    find_spec, never an import: this runs adjacent to `--help` and on machines
    where the import would fail, and both must stay cheap and safe.
    """
    import sys
    from importlib.util import find_spec

    # sys.modules first, for the same reason as dsj.whisper.available: an
    # imported (or test-stubbed) backend is available, and find_spec raises
    # on a stub with no __spec__.
    if "parakeet_mlx" in sys.modules:
        return None
    if find_spec("parakeet_mlx") is None:
        import platform

        return (
            "parakeet-mlx is not installed. It requires Apple Silicon and "
            f"Metal; this machine is {platform.machine()} {platform.system()}. "
            "On a Mac, reinstall with the parakeet engine included (see the "
            "README's install line)."
        )
    return None


def fingerprint_fields() -> dict[str, str]:
    """The engine's contribution to a checkpoint fingerprint, merged flat.

    The key NAME is load-bearing: `parakeet_version` is what every checkpoint
    on disk already carries from when checkpoint.py hardcoded it, and the flat
    merge in Fingerprint.to_dict() only reproduces those bytes if this key
    matches. The version matters for the reason the old comment gave -- the
    merge helpers were vendored from parakeet-mlx, and tokens merged by one
    version's functions cannot safely be extended by another's.
    """
    from importlib.metadata import version

    return {"parakeet_version": version("parakeet-mlx")}


class _Generates(Protocol):
    """The one method this engine calls on a loaded model.

    BaseParakeet.generate is annotated upstream, but its `mel: mx.array`
    parameter resolves to Unknown (mlx ships no stubs), which makes every call
    through it partially unknown. Restating the signature with the mel as Any
    keeps the useful half -- the list[AlignedResult] return -- typed.
    """

    def generate(
        self, mel: Any, *, decoding_config: Any = ...
    ) -> list[UpstreamResult]: ...


@dataclass
class _LoadedParakeet:
    """A loaded model behind the ChunkEngine protocol (dsj.asr).

    Holds the model handle and the decoding config; the feature step
    (get_logmel) is re-imported per decode so a monkeypatched
    parakeet_mlx.audio is honoured -- the same reason every other backend
    import here is function-local.
    """

    model: Any
    sample_rate: int
    min_chunk_samples: int
    _decoding: Any = field(default=None, repr=False)

    def load_audio(self, path: Path) -> Any:
        """Decode `path` to the model's sample rate. Returns an mx.array."""
        from parakeet_mlx.audio import (
            load_audio as _load_audio,  # pyright: ignore[reportUnknownVariableType]  # mlx has no stubs
        )

        return cast("Any", _load_audio)(path, self.sample_rate)

    def decode(self, samples: Any) -> list[AlignedToken]:
        """One chunk's tokens, timed from the chunk's own start (t=0).

        Every gap over REREAD_GAP_S after a token is decoded again on its own
        (_with_gaps_read, #228).
        """
        return _with_gaps_read(
            self._decode_once, samples, self.sample_rate, self.min_chunk_samples
        )

    def _decode_once(self, samples: Any) -> list[AlignedToken]:
        """`samples` through the model once: one encoder pass, one greedy decode."""
        from parakeet_mlx.audio import (
            get_logmel as _get_logmel,  # pyright: ignore[reportUnknownVariableType]  # mlx has no stubs
        )

        mel = cast("Any", _get_logmel)(samples, self.model.preprocessor_config)
        result = cast(_Generates, self.model).generate(
            mel, decoding_config=self._decoding
        )[0]
        # The vocabulary boundary: upstream tokens become dsj tokens here, and
        # nothing above this module ever sees a parakeet_mlx type again.
        return [
            AlignedToken(
                id=token.id,
                text=token.text,
                start=token.start,
                duration=token.duration,
                confidence=token.confidence,
            )
            for sentence in result.sentences
            for token in sentence.tokens
        ]


def _with_gaps_read(
    decode: Callable[[Any], list[AlignedToken]],
    samples: Any,
    rate: int,
    min_samples: int,
    depth: int = 0,
) -> list[AlignedToken]:
    """`decode(samples)`, with each gap over REREAD_GAP_S after a token decoded again alone.

    A gap runs from a token's end to the next token's start, or to the end of
    `samples` after the last token. Its audio is decoded by itself, so the
    decoder starts from a reset state there, and what it finds is put in the
    gap, timed from the start of `samples`. The gap before the first token is
    never read again: the decoder already started fresh there. Gaps inside a
    gap are read in turn, REREAD_DEPTH deep at most.
    """
    tokens = decode(samples)
    if not tokens or depth >= REREAD_DEPTH:
        return tokens
    ends = [t.start + t.duration for t in tokens]
    starts = [t.start for t in tokens[1:]] + [len(samples) / rate]
    found: list[AlignedToken] = []
    for a, b in zip(ends, starts, strict=True):
        lo, hi = round(a * rate), round(b * rate)
        if b - a <= REREAD_GAP_S or hi - lo < min_samples:
            continue
        found += [
            replace(t, start=t.start + lo / rate)
            for t in _with_gaps_read(decode, samples[lo:hi], rate, min_samples, depth + 1)
        ]
    if not found:
        return tokens
    return sorted(tokens + found, key=lambda t: t.start)


def wrap(model: Any) -> _LoadedParakeet:
    """Wrap an already-loaded model (or a test double) as a ChunkEngine.

    Split from load() so the slow equivalence tests, which hold a real model,
    and the fast tests, which hold a FakeModel, drive the exact engine object
    production uses rather than a lookalike.
    """
    from parakeet_mlx import DecodingConfig

    return _LoadedParakeet(
        model=model,
        # A property of this model's preprocessor, not a constant we assume.
        sample_rate=model.preprocessor_config.sample_rate,
        # Below one hop there is no feature frame to decode -- upstream's own
        # guard, restated as a number chunking.py can compare against.
        min_chunk_samples=model.preprocessor_config.hop_length,
        _decoding=DecodingConfig(),
    )


def load(model_id: str = DEFAULT_MODEL) -> _LoadedParakeet:
    """Download/load the weights and return the engine. The expensive call."""
    from parakeet_mlx import (
        from_pretrained as _from_pretrained,  # pyright: ignore[reportUnknownVariableType]  # mlx has no stubs
    )

    return wrap(cast("Any", _from_pretrained)(model_id))
