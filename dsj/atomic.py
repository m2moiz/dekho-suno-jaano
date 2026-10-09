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
import uuid
from pathlib import Path


def _temp(path: Path) -> Path:
    """A temp file beside `path` that no other write, in this process or another, will name.

    The pid alone is not enough: two threads of one server writing the same
    file at once (a double click on a route the thread pool runs) would share
    it, and one would rename away the file the other was still writing.
    """
    return path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp")


def _sync_folders(paths: list[Path]) -> None:
    """Force the renames into each distinct parent folder of `paths` out to disk.

    A rename is a change to the folder, not to the file, so syncing the file's
    bytes leaves the new name in memory: after a power loss the folder can come
    back listing the old file, or neither (#285). An error here propagates,
    because a caller that asked for fsync wants to know the name is not durable.

    This is plain os.fsync, not F_FULLFSYNC. On macOS fsync(2) does not ask the
    drive to flush its own cache (`man 2 fsync` says F_FULLFSYNC does), so this
    narrows the window rather than closing it. The file bytes above use the
    same os.fsync, and a folder entry stronger than the data it names buys
    nothing; moving both to F_FULLFSYNC is one change, made for both at once.
    """
    for folder in dict.fromkeys(path.parent for path in paths):
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write_text(path: Path, text: str, *, fsync: bool = False) -> None:
    """Make `path` contain `text`, atomically from a reader's point of view.

    A concurrent reader always resolves either the previous complete document
    or the new one.

    `fsync` additionally forces the bytes out of the page cache before the
    rename, which only matters across a power loss -- a process that merely
    dies leaves the page cache intact. Pass it for files whose loss costs real
    work, not for a progress heartbeat. It also syncs the folder after the
    rename, so the new name survives the power loss as well as the bytes.
    """
    # rename(2) requires both paths on the same file system, so the temp file
    # is a sibling rather than something under /tmp -- on this machine those
    # are different volumes and the rename would fail with EXDEV.
    #
    # The name is unique to this write (_temp), and "x" refuses to open one
    # that exists, so two writers can never hand each other a half-built temp
    # file to rename into place.
    tmp = _temp(path)
    try:
        with tmp.open("x", encoding="utf-8") as f:
            f.write(text)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        # Suppressed below: os.replace IS the atomicity primitive this module is
        # built on -- rename(2) semantics, documented above. Path.replace is the
        # same call with a nicer face, but naming os.replace is the point.
        os.replace(tmp, path)  # noqa: PTH105
        if fsync:
            _sync_folders([path])
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
    few system calls, can leave one new beside one old. Two callers writing
    the same files at once can still interleave their renames: a caller that
    can be called twice at once holds a lock of its own around this.
    """
    temps = [(_temp(path), path) for path, _ in files]
    try:
        for (tmp, _), (_, text) in zip(temps, files, strict=True):
            with tmp.open("x", encoding="utf-8") as f:
                f.write(text)
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())
        for tmp, path in temps:
            os.replace(tmp, path)  # noqa: PTH105  (see atomic_write_text)
        if fsync:
            _sync_folders([path for _, path in temps])
    except BaseException:
        for tmp, _ in temps:
            tmp.unlink(missing_ok=True)
        raise
