"""Keep the Mac awake while a run or a render works (#89).

A Mac left alone sleeps partway through a long transcription and the run
stalls until someone wakes it. `held(name)` takes a power assertion for the
length of a `with` block by starting `/usr/bin/caffeinate -i -w <our pid>`:
`-i` is "no idle sleep", and `-w` ties the assertion to this process, so the
hold ends when this process ends, however it ends (a `kill -9` included,
which no `finally` of ours would see). Normal exit from the block ends it
sooner, by stopping caffeinate.

Holds are counted, not toggled: two overlapping runs in one process (the app's
queue) share one caffeinate, and the one that finishes first does not release
the other's hold. The names are for the log.

Failure to take the hold is said on stderr and never raised: a Mac that may
sleep is a slower run, not a failed one. On a machine with no caffeinate
(Linux, a container) every hold is a no-op and says so once.
"""

from __future__ import annotations

__all__ = ["CAFFEINATE", "held"]

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Generator
from pathlib import Path

CAFFEINATE = "/usr/bin/caffeinate"

_lock = threading.Lock()
_holders: list[str] = []
_process: subprocess.Popen[bytes] | None = None
_said_missing = False


def _start() -> subprocess.Popen[bytes] | None:
    global _said_missing
    if not Path(CAFFEINATE).exists():
        if not _said_missing:
            print(f"{CAFFEINATE} is not here, so the machine may sleep during this run",
                  file=sys.stderr, flush=True)
            _said_missing = True
        return None
    try:
        return subprocess.Popen(
            [CAFFEINATE, "-i", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        print(f"could not keep the machine awake ({type(exc).__name__}: {exc}); "
              f"it may sleep during this run", file=sys.stderr, flush=True)
        return None


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)


@contextlib.contextmanager
def held(name: str) -> Generator[None]:
    """Keep the machine awake until the block ends; nested holds share one assertion."""
    global _process
    with _lock:
        if not _holders:
            _process = _start()
        _holders.append(name)
    try:
        yield
    finally:
        with _lock:
            _holders.remove(name)
            if not _holders and _process is not None:
                _stop(_process)
                _process = None


def holders() -> tuple[str, ...]:
    """The names holding the machine awake right now, for a test or a log line."""
    with _lock:
        return tuple(_holders)
