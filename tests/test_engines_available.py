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


def test_a_sherpa_that_will_not_import_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal's remedy is dsj's own extra, and nothing in it is false on a Mac (#168).

    It used to say `pip install sherpa-onnx` and "manylinux wheels only".
    sherpa-onnx publishes macOS wheels too (uv.lock carries macosx_11_0_arm64),
    and after #165 it runs on a Mac, so that hint sent a Mac reader the wrong
    way. It also named the bare package, which is the install #165 found
    broken: libonnxruntime ships in sherpa-onnx-core, which the extra pins.

    The import is made to fail rather than the module removed, because
    available() imports for real, and a failed native load is the case it
    reports.
    """
    import importlib
    import sys

    from dsj import sherpa as sherpa_mod

    def refuse(name: str) -> None:
        raise ImportError("dlopen failed: libonnxruntime.dylib not found")

    monkeypatch.delitem(sys.modules, "sherpa_onnx", raising=False)
    monkeypatch.setattr(importlib, "import_module", refuse)

    reason = sherpa_mod.available()

    assert reason is not None
    assert "libonnxruntime.dylib" in reason
    assert "dsj[sherpa]" in reason
    assert "uv sync --extra sherpa" in reason
    assert "manylinux" not in reason
    assert "pip install" not in reason
