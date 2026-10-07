"""Replace a file's contents without ever exposing a partial one.

Path.write_text truncates and then writes, so a reader that arrives in that
window gets an empty or half-written file. For the transcription heartbeat that
is not a cosmetic problem: the file exists to be trusted by an observer who
cannot see the job, and garbage that parses as "no progress" is worse than a
missing file, which at least announces itself.
"""

from __future__ import annotations

__all__ = [
    "atomic_write_text",
    "atomic_write_texts",
]

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, fsync: bool = False) -> None:
    """Make `path` contain `text`, atomically from a reader's point of view.

    A concurrent reader always resolves either the previous complete document
    or the new one.

    `fsync` additionally forces the bytes out of the page cache before the
    rename, which only matters across a power loss -- a process that merely
    dies leaves the page cache intact. Pass it for files whose loss costs real
    work, not for a progress heartbeat.
    """
    # rename(2) requires both paths on the same file system, so the temp file
    # is a sibling rather than something under /tmp -- on this machine those
    # are different volumes and the rename would fail with EXDEV.
    #
    # The pid is in the name so two processes writing the same status path
    # cannot hand each other a half-built temp file to rename into place.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        # Suppressed below: os.replace IS the atomicity primitive this module is
        # built on -- rename(2) semantics, documented above. Path.replace is the
        # same call with a nicer face, but naming os.replace is the point.
        os.replace(tmp, path)  # noqa: PTH105
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt mid-write is
        # exactly the case that would otherwise strand a temp file next to the
        # output, where the next run would find it and wonder.
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_texts(files: list[tuple[Path, str]], *, fsync: bool = False) -> None:
    """Make each path contain its text, writing every one before replacing any.

    For files that are one document in two shapes (an answer key as JSON and
    as text, dsj/ui/review.py): every temp file is written, and synced with
    `fsync`, before the first rename, so a failure while writing leaves all of
    them as they were, and only a crash between the renames, a window of a
    few system calls, can leave one new beside one old.
    """
    temps = [(path.with_name(f".{path.name}.{os.getpid()}.tmp"), path) for path, _ in files]
    try:
        for (tmp, _), (_, text) in zip(temps, files, strict=True):
            with tmp.open("w", encoding="utf-8") as f:
                f.write(text)
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())
        for tmp, path in temps:
            os.replace(tmp, path)  # noqa: PTH105  (see atomic_write_text)
    except BaseException:
        for tmp, _ in temps:
            tmp.unlink(missing_ok=True)
        raise
