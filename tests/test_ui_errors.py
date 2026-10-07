"""A failed request reaches the page as dsj's own sentence, never a bare 500 (#82).

The routes that will raise these (import, #110; transcription, #113) do not
exist yet, so each test adds one that does what such a route would, in front
of the page, and asks for it the way the page does.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dsj.asr import EngineUnavailable
from dsj.dekho import MarkError
from dsj.diarize import DiarizationUnavailable
from dsj.hatao import InvalidDocument, RenderRefused, TranscriptUnusable, WordListError
from dsj.media import FFmpegNotFound, MediaError, NoAudioStream, NoVideoStream, probe
from dsj.runlock import AlreadyRunning
from dsj.ui import UIUnavailable
from dsj.ui.edits import NoSuchTranscript
from dsj.ui.errors import STATUS, describe, status_of
from dsj.ui.jobs import NotStarted
from dsj.ui.pick import NoFilePicker, PickerBusy
from dsj.ui.review import InvalidReview, ReviewIncomplete
from dsj.ui.server import create_app
from dsj.ui.store import NotATranscript, NotTheSameRecording
from dsj.whisper import WhisperUnavailable


def page_with(endpoint: Callable[[], object], path: str = "/api/probe") -> TestClient:
    """The app, with one more route ahead of the page, asked as the page asks."""
    app, token = create_app(port=8721)
    app.add_api_route(path, endpoint, methods=["GET"])
    # Ahead of the static mount at "/", which would otherwise answer first.
    app.router.routes.insert(0, app.router.routes.pop())
    return TestClient(
        app,
        base_url="http://127.0.0.1:8721",
        headers={"Authorization": f"Bearer {token}"},
        # So a 500 arrives as the response the page would get, not an exception.
        raise_server_exceptions=False,
    )


def test_ffmpeg_off_path_answers_503_with_its_own_remedy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The issue's first line: a route that calls ffmpeg, with ffmpeg gone."""
    media = tmp_path / "recording.m4a"
    media.write_bytes(b"not read: ffprobe is looked for first")
    monkeypatch.setenv("PATH", str(tmp_path))

    def calls_ffprobe() -> object:
        return probe(media)

    reply = page_with(calls_ffprobe).get("/api/probe")
    assert reply.status_code == 503, reply.text
    body = reply.json()
    assert body == {
        "error": "FFmpegNotFound",
        "message": "ffprobe is not on PATH. dsj reads video through ffmpeg; "
        "install it with `brew install ffmpeg`.",
        "request": "/api/probe",
    }
    assert "Traceback" not in reply.text


def build(cls: type[BaseException]) -> BaseException:
    """One instance of `cls`, with a message only it would carry."""
    if cls is AlreadyRunning:
        return AlreadyRunning(Path("/tmp/suno.lock"), {"pid": 4242, "out": "/tmp/x.json"})
    return cls(f"the {cls.__name__} sentence, with its remedy")


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (EngineUnavailable, 503),
        (WhisperUnavailable, 503),
        (DiarizationUnavailable, 503),
        (FFmpegNotFound, 503),
        (UIUnavailable, 503),
        (NoFilePicker, 503),
        (NoAudioStream, 422),
        (NoVideoStream, 422),
        (MarkError, 422),
        (NotATranscript, 422),
        (NotTheSameRecording, 422),
        (NotStarted, 422),
        (TranscriptUnusable, 422),
        (InvalidDocument, 422),
        (WordListError, 422),
        (RenderRefused, 422),
        (InvalidReview, 422),
        (NoSuchTranscript, 404),
        (AlreadyRunning, 409),
        (PickerBusy, 409),
        (ReviewIncomplete, 409),
        (MediaError, 500),
    ],
)
def test_each_named_error_keeps_its_name_and_its_words(
    cls: type[BaseException], status: int
) -> None:
    exc = build(cls)

    def raises() -> object:
        raise exc

    reply = page_with(raises).get("/api/probe")
    assert reply.status_code == status, reply.text
    # Not reworded, not wrapped: the sentence Python wrote, and the class name.
    assert reply.json() == {"error": cls.__name__, "message": str(exc), "request": "/api/probe"}


def test_the_table_above_is_the_whole_table() -> None:
    """A class added to STATUS without a test here would be a status nobody checked."""
    tested = {
        EngineUnavailable, WhisperUnavailable, DiarizationUnavailable, FFmpegNotFound,
        UIUnavailable, NoAudioStream, NoVideoStream, MarkError, NotATranscript,
        NotTheSameRecording, NotStarted, AlreadyRunning, MediaError, NoFilePicker, PickerBusy,
        TranscriptUnusable, InvalidDocument, NoSuchTranscript, WordListError, RenderRefused,
        InvalidReview, ReviewIncomplete,
    }
    assert set(STATUS) == tested


def test_an_error_nobody_listed_still_reaches_the_page_with_its_own_text() -> None:
    class SomethingNew(Exception):
        pass

    def raises() -> object:
        raise SomethingNew("a sentence nobody planned for")

    reply = page_with(raises).get("/api/probe")
    assert reply.status_code == 500
    assert reply.json() == {
        "error": "SomethingNew",
        "message": "a sentence nobody planned for",
        "request": "/api/probe",
    }


def test_a_subclass_takes_its_nearest_listed_parents_status() -> None:
    class Silent(NoAudioStream):
        pass

    assert status_of(Silent("x")) == 422
    # FFmpegNotFound is a MediaError, and its own 503 wins over MediaError's 500.
    assert status_of(FFmpegNotFound("x")) == 503
    assert status_of(KeyError("x")) == 500


def test_describe_is_the_shape_the_dialog_reads() -> None:
    status, body = describe(NoVideoStream("no picture in a.m4a"), "/api/x")
    assert status == 422
    assert body == {"error": "NoVideoStream", "message": "no picture in a.m4a", "request": "/api/x"}


def test_a_request_without_the_token_is_told_how_to_get_one() -> None:
    app, _ = create_app(port=8721)
    reply = TestClient(app, base_url="http://127.0.0.1:8721").get("/api/recordings")
    assert reply.status_code == 401
    body = reply.json()
    assert body["error"] == "Unauthorized"
    assert "dsj ui" in body["message"]
    assert body["request"] == "/api/recordings"


def test_the_handlers_are_on_the_app_dsj_ui_serves() -> None:
    """Every listed class, and Exception, so nothing reaches FastAPI's bare 500."""
    app: FastAPI = create_app(port=8721)[0]
    assert set(STATUS) | {Exception} <= set(app.exception_handlers)
