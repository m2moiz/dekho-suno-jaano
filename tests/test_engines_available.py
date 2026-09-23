"""An engine whose backend is installed must be usable, not merely present.

#165: `uv.lock` recorded no dependencies for `sherpa-onnx`, so the `sherpa`
extra installed a package whose native library (`libonnxruntime.dylib`, which
ships in `sherpa-onnx-core`) was never installed beside it. dsj itself reported
this correctly at runtime -- `sherpa.available()` imports rather than trusting
find_spec, and `get_engine` refused with the import error. What was missing was
anything that ran that check where it mattered: CI syncs every extra
(.github/workflows/ci.yml) and stayed green, because every sherpa test drives a
fake recognizer and none ever loads the real one.

This goes through `get_engine`, the same door `dsj suno` uses, so a pass here
means the engine would actually start.
"""

from __future__ import annotations

import os
from importlib.util import find_spec

import pytest

from dsj.asr import ENGINES, get_engine

# The package each engine's available() is ultimately about.
BACKEND = {"parakeet": "parakeet_mlx", "whisper": "mlx_whisper", "sherpa": "sherpa_onnx"}


def test_every_engine_has_a_backend_listed_here() -> None:
    assert set(BACKEND) == set(ENGINES)


@pytest.mark.parametrize("engine", ENGINES)
def test_an_installed_engine_starts(engine: str) -> None:
    if find_spec(BACKEND[engine]) is None:
        # A dev machine may leave an extra out. CI may not: it syncs every one,
        # so there a missing backend is the failure itself, and skipping would
        # report green in exactly the state this test exists to catch.
        assert not os.environ.get("CI"), f"{BACKEND[engine]} is not installed in CI"
        pytest.skip(f"{BACKEND[engine]} is not installed here")
    get_engine(engine)
