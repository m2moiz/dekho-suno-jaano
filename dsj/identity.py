"""Which recording is this? One answer, for everything in dsj that has to ask.

Three parts of dsj need to know whether two files are the same recording: the
resume checkpoint, the library (#105) and the transcript sidecar (#119). Built
separately they would compute three ids for one file and disagree in silence the
day it is renamed, moved or copied, so the id is defined once, here (#120).

Content, not path. A path changes on every rename and move, and a modification
time changes on a plain `cp` (measured on #118: `st_mtime_ns` went from
1786023654125128407 to 1790108267751402073), while the bytes of the recording do
not change at all.

Not in dsj/media.py, which is the module that talks to ffmpeg. This reads bytes
and runs nothing, so a caller that only wants an id does not import ffmpeg's
error surface to get one.
"""

from __future__ import annotations

__all__ = ["EDGE_BYTES", "content_id"]

import hashlib
from pathlib import Path

# How much of each end of the file is hashed: 1 MiB. Every caller of content_id
# shares this number, which is the point of it living here; a library that hashed
# a different span would never find a checkpoint's recording.
EDGE_BYTES = 1 << 20


def content_id(media: Path) -> str:
    """Name the recording by its contents: its size, then a SHA-256 of its two ends.

    The id is `"<size in bytes>-<64 hex digits>"`, the digest taken over the
    first and the last EDGE_BYTES of the file. A file of two edges or less is
    hashed whole, every byte once.

    The cost is bounded to a 2 MiB read, whatever the size of the file, so asking
    for the id of a 1.25 GB screen recording costs what asking for a 2 MB one
    does. Measured 2026-09-23 on #117's 1.25 GB .mov: 3.3 ms on the first call
    and 1.7 ms on the four after it. The page cache was not purged first, so a
    cold spinning disk is not in those numbers; two seeks are.

    That bound is also the one thing this id cannot see: an edit confined to the
    middle of the file that leaves its size exactly as it was. Judged, not
    measured: trimming or appending changes the size, a re-encode almost always
    does, and QuickTime and MP4 keep the sample index a re-encode rewrites at one
    end of the file or the other.
    """
    size = media.stat().st_size
    digest = hashlib.sha256()
    with media.open("rb") as f:
        digest.update(f.read(EDGE_BYTES))
        # Never seek back into the head: between one and two edges long the tail
        # starts where the head stopped, so no byte is hashed twice or skipped.
        if size > EDGE_BYTES:
            f.seek(max(size - EDGE_BYTES, EDGE_BYTES))
            digest.update(f.read(EDGE_BYTES))
    return f"{size}-{digest.hexdigest()}"
