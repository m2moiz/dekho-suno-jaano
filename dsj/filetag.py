"""Keep a copy of a transcript on its recording, as a hidden file tag (#119).

The transcript JSON beside the recording is the truth. This module mirrors its
bytes into an extended attribute on the recording, `com.jaano.transcript`, so a
recording whose JSON went missing (deleted, left off a copy, swept up in a
downloads cleanup) can still find its transcript on this Mac.

It is a local safety net and nothing more. #117 measured three ordinary things
that drop the tag without a word: `ffmpeg -i X -c copy Y`, `avconvert` with
`PresetPassthrough` (what QuickTime Player's save goes through), and a trip
through Google Drive's servers. A plain `cp` or `mv` on the Mac keeps it.

Written with the C library's own setxattr through ctypes, macOS only:

  * `os.setxattr` is not there. Python ships it on Linux alone; `'setxattr' in
    dir(os)` is False under this project's Python on macOS (#127 trap 14).
  * `/usr/bin/xattr -w` takes the value as a command-line argument, so it is
    capped by ARG_MAX, 1,048,576 bytes here. Transcripts in this checkout's
    scratch/ already reach 2,433,766 bytes.
  * The `xattr` package from PyPI would be a new base dependency for one call.

Writing the tag changes neither the recording's bytes, its size nor its
`st_mtime_ns`, which is what keeps a checkpoint's fingerprint valid
(dsj/checkpoint.py keys on size and mtime).

A recording in a cloud-synced folder is never tagged (#202). What a sync client
does when a file it syncs gains a tag of several MB is not measured, and it may
upload the whole recording again; the owner chose to skip those files rather
than measure on their Drive. The transcript JSON is their only copy.
"""

from __future__ import annotations

__all__ = [
    "PROVIDER_DOMAIN_TAG",
    "TRANSCRIPT_TAG",
    "cloud_synced",
    "read_tag",
    "read_transcript",
    "sidecar_for",
    "tag_transcript",
    "write_tag",
]

import ctypes
import ctypes.util
import errno
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("dsj.suno")

TRANSCRIPT_TAG = "com.jaano.transcript"

# The tag macOS's File Provider puts on the root folder of each domain it syncs
# (Microsoft documents reading it with `xattr -p` on OneDrive's root). It is how
# a synced folder outside the two paths below shows itself: iCloud's Desktop &
# Documents keeps the ordinary ~/Desktop and ~/Documents paths. Not observed on
# a real iCloud folder: this Mac's Desktop and Documents are not synced (#202).
PROVIDER_DOMAIN_TAG = "com.apple.file-provider-domain-id"

# Under the home folder: where file provider clients (Google Drive, Dropbox,
# OneDrive) keep their folders, and where iCloud Drive keeps its own.
_SYNCED_UNDER_HOME = (("Library", "CloudStorage"), ("Library", "Mobile Documents"))


def _libc() -> ctypes.CDLL:
    """The C library, with macOS's six-argument getxattr and setxattr declared.

    macOS takes two arguments Linux does not, a position (resource forks only,
    always 0 here) and an options flag (0: follow a symlink to the recording).
    """
    if sys.platform != "darwin":
        raise OSError(
            errno.ENOTSUP,
            "dsj writes and reads file tags on macOS only; the transcript JSON is "
            "the only copy here",
        )
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    args = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_uint32, ctypes.c_int]
    libc.setxattr.argtypes = args
    libc.setxattr.restype = ctypes.c_int
    libc.getxattr.argtypes = args
    libc.getxattr.restype = ctypes.c_ssize_t
    return libc


def _raise_errno(path: Path) -> None:
    code = ctypes.get_errno()
    raise OSError(code, os.strerror(code), str(path))


def write_tag(path: Path, name: str, data: bytes) -> None:
    """Set the extended attribute `name` on `path` to `data`, replacing any earlier value."""
    libc = _libc()
    if libc.setxattr(os.fsencode(path), name.encode(), data, len(data), 0, 0) == -1:
        _raise_errno(path)


def read_tag(path: Path, name: str) -> bytes | None:
    """The extended attribute `name` on `path`, or None when the file carries none."""
    libc = _libc()
    raw_path, raw_name = os.fsencode(path), name.encode()
    # Asked for its size first: a buffer guessed too small is ERANGE, not a short read.
    size = libc.getxattr(raw_path, raw_name, None, 0, 0, 0)
    if size == -1:
        if ctypes.get_errno() == errno.ENOATTR:
            return None
        _raise_errno(path)
    buffer = ctypes.create_string_buffer(size)
    read = libc.getxattr(raw_path, raw_name, buffer, size, 0, 0)
    if read == -1:
        _raise_errno(path)
    return buffer.raw[:read]


def cloud_synced(path: Path) -> str | None:
    """Why `path` lies in a cloud-synced folder, or None when nothing says it does.

    Two signals, both read on this Mac with no network and no download: the
    path (under ~/Library/CloudStorage or ~/Library/Mobile Documents, symlinks
    resolved), then a File Provider domain tag on any folder above the file.
    The folders are asked, never the file: a tag copied out of a synced folder
    along with a recording must not make a local copy count as synced.
    """
    resolved = path.resolve()
    home = Path.home().resolve()
    for parts in _SYNCED_UNDER_HOME:
        root = home.joinpath(*parts)
        if resolved.is_relative_to(root):
            return f"it is under {root}"
    for folder in resolved.parents:
        try:
            domain = read_tag(folder, PROVIDER_DOMAIN_TAG)
        except OSError:
            # A folder this process may not look at (macOS privacy), or no
            # tags at all off a Mac: no signal from it either way.
            continue
        if domain is not None:
            return f"{folder} is synced by a file provider ({domain.decode(errors='replace')})"
    return None


def tag_transcript(recording: Path, transcript: Path) -> None:
    """Mirror the transcript's bytes onto the recording, or say on stderr why not.

    Read back from `transcript` rather than serialised again, so the tag holds
    exactly the bytes on disk, labelled or not. A failure is a warning and not
    an error: the transcript is already written and is the truth, and failing
    a finished run over its safety net would throw the transcript away.

    A recording in a cloud-synced folder is not tagged at all (#202).
    """
    synced = cloud_synced(recording)
    if synced is not None:
        logger.warning(
            "transcript not tagged onto %s, so only %s holds it: %s, and dsj does not "
            "tag files in a cloud-synced folder (#202)",
            recording, transcript, synced,
        )
        return
    try:
        write_tag(recording, TRANSCRIPT_TAG, transcript.read_bytes())
    except OSError as exc:
        logger.warning(
            "transcript not tagged onto %s, so only %s holds it: %s",
            recording, transcript, exc.strerror or exc,
        )


def sidecar_for(recording: Path) -> Path:
    """Where a recording's transcript is looked for first: `<stem>.dsj.json` beside it."""
    return recording.with_name(f"{recording.stem}.dsj.json")


def read_transcript(recording: Path) -> dict[str, Any]:
    """The recording's transcript, parsed: the sidecar if it is there, else the tag.

    The sidecar always wins, because it is the truth and the tag only a copy
    of it. The tag does not survive `ffmpeg -c copy`, `avconvert`'s
    PresetPassthrough, or a trip through Google Drive's servers (#117), so a
    recording that went through any of those has only the sidecar.

    Raises FileNotFoundError, naming both places, when neither holds one.
    """
    sidecar = sidecar_for(recording)
    if sidecar.is_file():
        data = sidecar.read_bytes()
    else:
        tagged = read_tag(recording, TRANSCRIPT_TAG)
        if tagged is None:
            raise FileNotFoundError(
                f"no transcript for {recording}: {sidecar} does not exist and the "
                f"recording carries no {TRANSCRIPT_TAG} tag. Transcribe it with "
                f"`dsj suno {recording} -o {sidecar}`."
            )
        data = tagged
    return cast("dict[str, Any]", json.loads(data))
