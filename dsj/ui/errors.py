"""What the page is told when a request fails: dsj's own sentence, never a bare 500 (#82).

dsj's errors already carry their remedy in their message (`FFmpegNotFound`
says to `brew install ffmpeg`). Left to FastAPI, every one of them would reach
the page as "Internal Server Error" and that sentence would be lost. So every
failure is answered with one shape, which the page's error dialog shows and
copies:

    {"error": "<class name>", "message": "<the message, unchanged>", "request": "<path>"}

The message is passed through as Python wrote it, never reworded: the remedy
sentences are written once, beside the code that raises them. The class name
always travels with it, because that is what makes a pasted error searchable.

Plain Python, no fastapi: dsj/ui/server.py registers `describe` as the
handler, and everything under dsj.ui but the server must import without the
`ui` extra.
"""

from __future__ import annotations

__all__ = ["STATUS", "describe", "status_of"]

from dsj.asr import EngineUnavailable
from dsj.dekho import MarkError
from dsj.diarize import DiarizationUnavailable
from dsj.hatao import InvalidDocument, RenderRefused, TranscriptUnusable, WordListError
from dsj.media import FFmpegNotFound, MediaError, NoAudioStream, NoVideoStream
from dsj.runlock import AlreadyRunning
from dsj.ui import UIUnavailable
from dsj.ui.edits import NoSuchTranscript
from dsj.ui.jobs import NotStarted
from dsj.ui.pick import NoFilePicker, PickerBusy
from dsj.ui.store import NotATranscript, NotTheSameRecording
from dsj.whisper import WhisperUnavailable

# Looked up along the raised class's MRO, so a subclass not listed takes its
# nearest listed parent's status: FFmpegNotFound is a MediaError, and its own
# 503 is found before MediaError's 500.
STATUS: dict[type[Exception], int] = {
    # This machine cannot do it right now, and installing something fixes it.
    EngineUnavailable: 503,
    WhisperUnavailable: 503,
    DiarizationUnavailable: 503,
    FFmpegNotFound: 503,
    UIUnavailable: 503,
    NoFilePicker: 503,
    # The file is wrong for what was asked.
    NoAudioStream: 422,
    NoVideoStream: 422,
    MarkError: 422,
    NotATranscript: 422,
    NotTheSameRecording: 422,
    # A transcript with no word ends cannot become an edit list, and a broken
    # list is refused whole, the entry named (#63, #66).
    TranscriptUnusable: 422,
    InvalidDocument: 422,
    # A list holding a cut or a move, which a render does not make (#215).
    RenderRefused: 422,
    # A spelling with no letters, or a user word list that is broken, named (#84).
    WordListError: 422,
    # No such transcript, or its file is gone: the routes' own 404, said by name.
    NoSuchTranscript: 404,
    # Gone from where the library last saw it (#113).
    NotStarted: 422,
    # Another transcription holds the machine; the request was fine, the moment was not.
    AlreadyRunning: 409,
    # The Mac's file dialog is already open for an earlier click (#110).
    PickerBusy: 409,
    # ffmpeg failed on the file in a way nobody named. Genuinely unexpected.
    MediaError: 500,
}


def status_of(exc: BaseException) -> int:
    """The HTTP status for `exc`: its nearest listed class's, else 500."""
    for cls in type(exc).__mro__:
        if cls in STATUS:
            return STATUS[cls]
    return 500


def describe(exc: BaseException, request: str) -> tuple[int, dict[str, str]]:
    """The status and the body the page is sent for `exc`, raised serving `request`."""
    return status_of(exc), {
        "error": type(exc).__name__,
        "message": str(exc),
        "request": request,
    }
