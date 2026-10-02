"""One `dsj suno` at a time on this machine (#136).

Two runs at once froze the owner's Mac on 2026-09-19. One run is already sized
against the machine's memory (suno chunks because an hour of audio in one piece
asks Metal for more than it has); two of them are not. The guard lived only in
four batch scripts an agent wrote, as `pgrep -f "dsj suno"`. Here it is in dsj
itself.

The lock is an flock(2) on one fixed file, not a pid file, and the difference
is the whole design:

  * The kernel drops an flock when the process holding it ends, however it
    ends. A run killed with SIGKILL, or by the system under memory pressure,
    frees the lock with no stale file to notice and no cleanup to get right.
  * A pid file has to be judged stale by asking whether its pid is alive, and
    pids are reused: a dead run's pid handed to some other process would block
    every run after it until that process ended.

The file's CONTENTS are only for the message: the holder writes its pid and
paths there so a refused run can say which job it is waiting on. The file is
never deleted. Deleting it would let the next run lock a new file while the
current one still holds the old, and two would run at once.

One fixed path rather than one beside `--out`, because the runs that froze the
machine were writing to different outputs.
"""

from __future__ import annotations

__all__ = [
    "LOCK_ENV",
    "AlreadyRunning",
    "acquire",
    "lock_path",
]

import contextlib
import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any

# The lock file's path, when set. The test suite points it into a temporary
# directory so that running the suite never contends with a real run.
LOCK_ENV = "DSJ_SUNO_LOCK"

# How long a refused run waits for the holder's details to appear. The holder
# writes them straight after taking the lock, so this only covers a second run
# started in the same instant as the first.
_HOLDER_WAIT_S = 1.0


class AlreadyRunning(RuntimeError):
    """Another `dsj suno` holds the lock. Nothing has been loaded or written."""

    def __init__(self, path: Path, holder: dict[str, Any]) -> None:
        """Say who holds the lock at `path`, from the `holder` it wrote there."""
        pid = holder.get("pid", "unknown")
        out = holder.get("out", "unknown")
        super().__init__(
            f"another dsj suno is already running on this machine: pid {pid}, writing {out}.\n"
            f"Two at once can exhaust this machine's memory (two froze the owner's Mac on "
            f"2026-09-19), so this one did not start. Wait for it to finish, which is when "
            f"`kill -0 {pid}` fails, or stop it with `kill {pid}`, then run this again.\n"
            f"The lock is {path}. Do not delete it: that frees nothing, it only lets a "
            f"second run start beside the first."
        )


def lock_path() -> Path:
    """Where the lock lives: `$DSJ_SUNO_LOCK`, else `~/.cache/dsj/suno.lock`."""
    configured = os.environ.get(LOCK_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "dsj" / "suno.lock"


def _read_holder(path: Path) -> dict[str, Any]:
    deadline = time.monotonic() + _HOLDER_WAIT_S
    while True:
        with contextlib.suppress(OSError, ValueError):
            holder = json.loads(path.read_text())
            if isinstance(holder, dict):
                return holder  # pyright: ignore[reportUnknownVariableType]
        if time.monotonic() >= deadline:
            return {}
        time.sleep(0.05)


def acquire(holder: dict[str, Any], path: Path | None = None) -> int:
    """Take the lock for this process, or raise AlreadyRunning naming who has it.

    `holder` is written into the file for a refused run to read. Returns the
    file descriptor that holds the lock; closing it, or the process ending,
    releases it.
    """
    path = path or lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise AlreadyRunning(path, _read_holder(path)) from None
    except BaseException:
        os.close(fd)
        raise
    # Truncated only once held: the previous holder's details stay readable
    # until the moment a new holder replaces them.
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(holder).encode())
    return fd
