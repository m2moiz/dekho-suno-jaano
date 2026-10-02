"""The real `dsj suno` command, run as its own process, over a stub engine.

    python tests/stub_suno.py <the arguments `dsj suno` takes>

Signals, process lifetimes and lock files are facts about a process, so the tests
for them (#143, #138, #136) need one: a real interpreter, with the real CLI and its
real signal handling, that the test can SIGINT, SIGTERM and SIGKILL. What it must
not need is 2.4 GB of parakeet weights, so the engine, the probe and the loudness
pass are replaced and nothing else is. The CLI, transcribe(), the checkpoint, the
heartbeat and every write to disk are the shipped code.

Two environment variables steer it:

    STUB_HOLD=1             after the first chunk is banked and reported, block until
                            a signal arrives, so a test can catch the run mid-flight,
                            or until its parent process is gone
    STUB_LOADED=<path>      touched when the model is loaded, so a test can prove a
                            refused run never got that far

The audio is a 300-second recording that does not exist: probe() says so and
load_audio() hands back that many zeros.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from dsj import asr, chunking, cli, media, suno

RATE = 16_000
AUDIO_S = 300.0
PARENT = os.getppid()


def _load_audio(_path: Path) -> Any:
    return np.zeros(int(AUDIO_S * RATE), dtype=np.float32)


def _load(_model_id: str) -> SimpleNamespace:
    marker = os.environ.get("STUB_LOADED")
    if marker:
        Path(marker).touch()
    return SimpleNamespace(sample_rate=RATE, load_audio=_load_audio)


ENGINE = SimpleNamespace(
    DEFAULT_MODEL="stub-model",
    MEASURES_END_AND_CONFIDENCE=True,
    load=_load,
    fingerprint_fields=lambda: {"stub_version": "0"},
)


def _get_engine(name: str) -> tuple[asr.EngineSpec, Any]:
    return asr.EngineSpec(name, "tests.stub_suno", "chunk"), ENGINE


def _transcribe_chunked(
    engine: Any, audio_data: Any, *, on_chunk: Any = None, **_: Any
) -> SimpleNamespace:
    total = len(audio_data)
    # One chunk banked and reported, as the real loop does after its first decode,
    # so the checkpoint and a `running` frame are both on disk before any hold.
    first = int(105 * RATE)
    if on_chunk is not None:
        on_chunk(first, first, total, [])
    if os.environ.get("STUB_HOLD") == "1":
        # Held until a signal arrives, or until the test that started it is
        # gone: a parent that died without stopping this process (pytest killed
        # by a timeout, say) would otherwise leave it running for good.
        while os.getppid() == PARENT:
            time.sleep(0.05)
        raise SystemExit("stub_suno: the process that started this one is gone")
    if on_chunk is not None:
        on_chunk(total, total, total, [])
    return SimpleNamespace(text="", sentences=[])


def _probe(path: Path) -> media.AudioStream:
    if not path.exists():
        raise FileNotFoundError(path)
    return media.AudioStream("pcm_s16le", RATE, 1, AUDIO_S)


def _needs_conversion(_stream: media.AudioStream, _rate: int) -> bool:
    return False


def _loudness(_path: Path, _frame_s: float, _sample_rate: int = RATE) -> Any:
    return np.zeros(0, dtype=np.float64)


# setattr, as monkeypatch would: these replace module attributes the shipped code
# reads at call time, which is exactly what makes them stand-ins.
for module, name, stand_in in (
    (suno, "get_engine", _get_engine),
    (chunking, "transcribe_chunked", _transcribe_chunked),
    (media, "probe", _probe),
    (media, "needs_conversion", _needs_conversion),
    (media, "loudness", _loudness),
):
    setattr(module, name, stand_in)

if __name__ == "__main__":
    sys.exit(cli.main(["suno", *sys.argv[1:]]))
