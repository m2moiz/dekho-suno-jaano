"""Asking the person at this Mac for a file, through the Mac's own dialog (#110).

A browser tab is told a picked or dropped file's name, size and date, never
where it is on disk (#127 trap 16), and dsj reads every recording where it
lies rather than copying it in. So the page cannot hand the server a path, and
the server must not take one from a page anyway (#112 rule 5). The server asks
macOS instead: osascript's `choose file` opens the standard open dialog and
answers with the real path of what was chosen.

Plain Python, no fastapi: dsj/ui/errors.py maps these errors to statuses, and
everything under dsj.ui but the server must import without the `ui` extra.
"""

from __future__ import annotations

__all__ = ["NoFilePicker", "PickerBusy", "choose_file"]

import shutil
import subprocess
import threading
from pathlib import Path

# Any audio or video the Mac recognises: a recording, never a document.
_SCRIPT = (
    'POSIX path of (choose file of type {{"public.audiovisual-content"}} '
    'with prompt "{prompt}")'
)

# The error number AppleScript gives a dialog the person cancelled.
_CANCELLED = "(-128)"

# One dialog at a time. A second click while one is open would stack a second
# dialog behind the first, and the answer to the one would land in the other's
# request.
_open = threading.Lock()


class NoFilePicker(RuntimeError):
    """This machine has no file dialog dsj can open. Nothing was chosen."""


class PickerBusy(RuntimeError):
    """A file dialog from dsj is already open. Nothing new was opened."""


def choose_file(prompt: str) -> Path | None:
    """The file the person picks in the Mac's open dialog, or None if they cancel.

    Blocks until the dialog closes, however long that takes: a person is
    looking for a file.

    Raises:
        PickerBusy: another call's dialog is still open.
        NoFilePicker: osascript is not here (not a Mac), or it failed for a
            reason other than the person cancelling; its own words are kept.
    """
    osascript = shutil.which("osascript")
    if osascript is None:
        raise NoFilePicker(
            "adding a recording from the app opens the Mac's file dialog through "
            "osascript, and there is no osascript on this machine. Transcribe the file "
            "with `dsj suno` instead; its transcript can then be opened here."
        )
    if not _open.acquire(blocking=False):
        raise PickerBusy(
            "a file dialog from dsj is already open. Choose a file in it, or cancel it, "
            "then try again. It may be behind another window."
        )
    try:
        # `activate` first, so the dialog is asked to come up in front of the
        # browser rather than behind it.
        proc = subprocess.run(
            [osascript, "-e", "activate", "-e", _SCRIPT.format(prompt=prompt.replace('"', "'"))],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        _open.release()
    if proc.returncode != 0:
        if _CANCELLED in proc.stderr:
            return None
        raise NoFilePicker(f"the Mac's file dialog failed: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())
