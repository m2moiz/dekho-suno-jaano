"""Starting a transcription from the page, and watching it (#113).

Each test runs the real server app, the real job runner, the real transcribe()
and the real library, against a real two-second wav made by ffmpeg. Only the
engine is a stand-in: no weights load, and its chunks are released one at a
time by the test, so progress can be watched between them.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import typing
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dsj import asr, chunking, cli, runlock, suno
from dsj.alignment import AlignedToken
from dsj.ui import jobs as jobs_mod
from dsj.ui.schemas import EngineName
from dsj.ui.server import Heartbeat, create_app
from dsj.ui.store import Library
from dsj.whisper import ANCHOR_CHUNK_S, DEFAULT_WHISPER_MODEL, ROMAN_URDU_PROMPT

RATE = 16_000
CHUNK = 105  # seconds of audio each stand-in chunk adds


def page() -> TestClient:
    """A fresh `dsj ui` launch, asked the way its page asks."""
    app, token = create_app(port=8721)
    return TestClient(
        app, base_url="http://127.0.0.1:8721", headers={"Authorization": f"Bearer {token}"}
    )


def wav(path: Path) -> Path:
    """Two seconds of tone, already 16 kHz mono, so nothing is extracted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=2", "-ar", str(RATE), "-ac", "1", str(path)],
        check=True,
    )
    return path


def add(media: Path) -> int:
    with Library.open() as library:
        return library.add_recording(media).id


def last_job(client: TestClient, until: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """The newest job, once `until` holds for it. Fails, saying what it saw, after 20 s."""
    deadline = time.monotonic() + 20
    while True:
        reply = client.get("/api/jobs")
        assert reply.status_code == 200, reply.text
        listed: list[dict[str, Any]] = reply.json()
        if listed and until(listed[-1]):
            return listed[-1]
        assert time.monotonic() < deadline, f"waited 20 s; the jobs read {listed}"
        time.sleep(0.02)


def any_engine(_name: str) -> None:
    """Stands in for get_engine where transcribe() itself is stood in for."""


def finished(job: dict[str, Any]) -> bool:
    return job["state"] in ("done", "failed")


class StubEngine:
    """A chunk engine with no weights, whose chunks wait for the test to release them.

    `chunks` chunks of CHUNK seconds each. Chunk k is banked and reported, the
    way the real chunk loop does it, once `release(k)` has been called.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, chunks: int = 1, held: bool = False,
                 load_raises: Exception | None = None) -> None:
        self.gates = [threading.Event() for _ in range(chunks)]
        if not held:
            for gate in self.gates:
                gate.set()
        self.load_raises = load_raises
        self.total = chunks * CHUNK * RATE
        self.module = SimpleNamespace(
            DEFAULT_MODEL="stub-model",
            MEASURES_END_AND_CONFIDENCE=True,
            load=self.load,
            fingerprint_fields=lambda: {"stub": "0"},
        )
        monkeypatch.setattr(suno, "get_engine", self.get_engine)
        monkeypatch.setattr(jobs_mod, "get_engine", self.get_engine)
        monkeypatch.setattr(chunking, "transcribe_chunked", self.transcribe_chunked)

    def get_engine(self, name: str) -> tuple[asr.EngineSpec, Any]:
        return asr.EngineSpec(name, "tests.test_jobs", "chunk"), self.module

    def load(self, _model_id: str) -> SimpleNamespace:
        if self.load_raises is not None:
            raise self.load_raises
        return SimpleNamespace(sample_rate=RATE, load_audio=self.load_audio)

    def load_audio(self, _path: Path) -> Any:
        return np.zeros(self.total, dtype=np.float32)

    def release(self, k: int) -> None:
        self.gates[k].set()

    def release_all(self) -> None:
        for gate in self.gates:
            gate.set()

    def transcribe_chunked(self, _engine: Any, _audio: Any, *, on_chunk: Any, **_: Any) -> Any:
        for k, gate in enumerate(self.gates):
            assert gate.wait(20), f"chunk {k} was never released"
            done = (k + 1) * self.total // len(self.gates)
            on_chunk(done, done, self.total, [])
        token = AlignedToken(id=0, text=" Hello.", start=0.0, duration=1.0)
        return SimpleNamespace(
            text=" Hello.",
            sentences=[SimpleNamespace(start=0.0, end=1.0, text=" Hello.", tokens=[token])],
        )


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., StubEngine]]:
    made: list[StubEngine] = []

    def install(**kwargs: Any) -> StubEngine:
        made.append(StubEngine(monkeypatch, **kwargs))
        return made[-1]

    yield install
    # A test that failed with a chunk still held must not leave the worker blocked.
    for stub in made:
        stub.release_all()


@pytest.fixture
def recording(tmp_path: Path) -> tuple[Path, int]:
    media = wav(tmp_path / "standup.wav")
    return media, add(media)


# -- the picker ---------------------------------------------------------------


def test_the_picker_lists_the_three_engines_and_nothing_else() -> None:
    reply = page().get("/api/engines")
    assert reply.status_code == 200, reply.text
    assert [e["name"] for e in reply.json()] == list(asr.ENGINES)
    assert typing.get_args(EngineName.__value__) == asr.ENGINES


def test_an_engine_that_cannot_run_is_listed_with_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dsj.whisper

    monkeypatch.setattr(dsj.whisper, "available", lambda: "mlx-whisper is not installed here")
    listed = {e["name"]: e for e in page().get("/api/engines").json()}
    assert "mlx-whisper is not installed here" in listed["whisper"]["reason"]
    assert listed["whisper"]["default_model"] == DEFAULT_WHISPER_MODEL


def test_starting_an_engine_that_cannot_run_is_refused_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, recording: tuple[Path, int]
) -> None:
    import dsj.whisper

    monkeypatch.setattr(dsj.whisper, "available", lambda: "mlx-whisper is not installed here")
    client = page()
    reply = client.post(f"/api/recordings/{recording[1]}/transcribe", json={"engine": "whisper"})
    assert reply.status_code == 503, reply.text
    assert reply.json()["error"] == "EngineUnavailable"
    assert "mlx-whisper is not installed here" in reply.json()["message"]
    assert client.get("/api/jobs").json() == []


# -- a run, start to finish -----------------------------------------------------


def test_a_run_from_the_page_writes_what_dsj_suno_writes_and_adds_a_library_row(
    engine: Callable[..., StubEngine], recording: tuple[Path, int], tmp_path: Path
) -> None:
    engine()
    media, recording_id = recording
    client = page()
    reply = client.post(
        f"/api/recordings/{recording_id}/transcribe", json={"engine": "parakeet", "diarize": False}
    )
    assert reply.status_code == 202, reply.text
    job = last_job(client, finished)
    assert job["state"] == "done", job
    assert job["error"] is None

    # The same keys as the same run from the terminal, over the same stand-in.
    written = jobs_mod.transcript_path(recording_id, "parakeet", job["model"], None)
    from_app = json.loads(written.read_text())
    terminal = tmp_path / "terminal.json"
    assert cli.main(["suno", str(media), "-o", str(terminal), "--no-diarize"]) == 0
    assert set(from_app) == set(json.loads(terminal.read_text()))
    assert {"audio", "model", "text", "sentences"} <= set(from_app)

    rows = client.get("/api/recordings").json()
    (row,) = [r for r in rows if r["id"] == recording_id]
    # The terminal run above records itself too (#208), so the recording has
    # two transcripts, one row each: the job was recorded once, not twice.
    (transcript,) = [t for t in row["transcripts"] if t["id"] == job["transcript_id"]]
    assert transcript["engine"] == "parakeet"
    with Library.open() as library:
        paths = [t.json_path for t in library.transcripts(recording_id)]
    assert sorted(paths) == sorted([written.resolve(), terminal.resolve()])


def test_progress_moves_once_per_finished_chunk(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    stub = engine(chunks=3, held=True)
    client = page()
    client.post(f"/api/recordings/{recording[1]}/transcribe", json={"diarize": False})
    seen: list[float] = []
    for k in range(3):
        stub.release(k)
        job = last_job(client, lambda j, k=k: j["fraction"] >= round((k + 1) / 3, 4))
        seen.append(job["fraction"])
        assert job["reports_progress"] is True
    assert seen == [round(1 / 3, 4), round(2 / 3, 4), 1.0]
    assert last_job(client, finished)["state"] == "done"


def test_a_run_that_crashes_shows_as_failed_with_its_error(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine(load_raises=RuntimeError("model exploded"))
    client = page()
    client.post(f"/api/recordings/{recording[1]}/transcribe", json={"diarize": False})
    job = last_job(client, finished)
    assert job["state"] == "failed"
    assert job["error"] == "RuntimeError: model exploded"
    assert job["transcript_id"] is None
    # The run let go of the machine: the next one is not refused.
    os.close(runlock.acquire({"pid": os.getpid()}))


def test_a_job_shows_as_finished_only_after_it_lets_go_of_the_lock(
    engine: Callable[..., StubEngine],
    recording: tuple[Path, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page that sees a job finish and starts the next at once is not refused by it.

    Under `just verify`'s load the worker thread published `failed` before it
    closed the lock, and the next acquire was refused. Closing the lock slowly
    here makes that order fail every time, not one run in many.
    """
    real_close = os.close

    def slow_close(fd: int) -> None:
        time.sleep(0.3)
        real_close(fd)

    monkeypatch.setattr(jobs_mod.os, "close", slow_close)
    engine(load_raises=RuntimeError("model exploded"))
    client = page()
    client.post(f"/api/recordings/{recording[1]}/transcribe", json={"diarize": False})
    assert last_job(client, finished)["state"] == "failed"
    real_close(runlock.acquire({"pid": os.getpid()}))


def test_labelling_that_cannot_run_is_a_note_on_a_finished_run(
    engine: Callable[..., StubEngine],
    recording: tuple[Path, int],
    fake_turns: Callable[..., list[Path]],
) -> None:
    from dsj.diarize import DiarizationUnavailable

    engine()
    fake_turns(raises=DiarizationUnavailable("no diarizer here"))
    client = page()
    client.post(f"/api/recordings/{recording[1]}/transcribe", json={})
    job = last_job(client, finished)
    assert job["state"] == "done"
    assert any("no diarizer here" in note for note in job["notes"]), job["notes"]
    (row,) = client.get("/api/recordings").json()
    assert row["transcripts"][0]["diarized"] is False


# -- whisper's options ----------------------------------------------------------


def test_roman_urdu_from_the_page_passes_what_dsj_suno_roman_urdu_passes(
    monkeypatch: pytest.MonkeyPatch, recording: tuple[Path, int], tmp_path: Path
) -> None:
    """Engine, language, prompt, anchor_s and model, from one definition (trap 15 of #127)."""
    calls: list[dict[str, Any]] = []

    def record(media: Path, out: Path, model_id: str | None = None, **kw: Any) -> dict[str, Any]:
        calls.append({"model_id": model_id, **kw})
        payload: dict[str, Any] = {
            "audio": str(media), "model": model_id, "text": "", "sentences": [],
        }
        out.write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(suno, "transcribe", record)
    monkeypatch.setattr(jobs_mod, "get_engine", any_engine)
    media, recording_id = recording
    client = page()
    reply = client.post(
        f"/api/recordings/{recording_id}/transcribe",
        json={"engine": "parakeet", "roman_urdu": True, "diarize": False},
    )
    assert reply.status_code == 202, reply.text
    assert reply.json()["reports_progress"] is True
    assert last_job(client, finished)["state"] == "done"
    assert cli.main(["suno", str(media), "-o", str(tmp_path / "t.json"), "--roman-urdu",
                     "--no-diarize"]) == 0

    app, terminal = calls
    keys = ("engine", "language", "prompt", "anchor_s", "model_id")
    assert {k: app[k] for k in keys} == {k: terminal[k] for k in keys} == {
        "engine": "whisper",
        "language": "ur",
        "prompt": ROMAN_URDU_PROMPT,
        "anchor_s": ANCHOR_CHUNK_S,
        "model_id": DEFAULT_WHISPER_MODEL,
    }


def test_whisper_without_roman_urdu_says_progress_comes_only_at_the_end(
    monkeypatch: pytest.MonkeyPatch, recording: tuple[Path, int]
) -> None:
    done = threading.Event()

    def held(media: Path, out: Path, **_: Any) -> dict[str, Any]:
        assert done.wait(20)
        out.write_text(json.dumps({"audio": str(media), "model": "m", "sentences": []}))
        return {}

    monkeypatch.setattr(suno, "transcribe", held)
    monkeypatch.setattr(jobs_mod, "get_engine", any_engine)
    client = page()
    try:
        reply = client.post(
            f"/api/recordings/{recording[1]}/transcribe", json={"engine": "whisper"}
        )
        assert reply.json()["reports_progress"] is False
    finally:
        done.set()
    assert last_job(client, finished)["state"] == "done"
    assert suno.reports_progress("parakeet", None, None)
    assert suno.reports_progress("sherpa", None, None)
    assert not suno.reports_progress("whisper", "a prompt", None)
    assert suno.reports_progress("whisper", "a prompt", ANCHOR_CHUNK_S)


# -- what is refused, before anything runs -------------------------------------


def test_a_second_job_is_refused_naming_the_first_ones_pid(
    engine: Callable[..., StubEngine], recording: tuple[Path, int], tmp_path: Path
) -> None:
    stub = engine(held=True)
    client = page()
    path = f"/api/recordings/{recording[1]}/transcribe"
    assert client.post(path, json={"diarize": False}).status_code == 202

    again = client.post(path, json={"diarize": False})
    assert again.status_code == 409, again.text
    assert again.json()["error"] == "AlreadyRunning"
    assert f"pid {os.getpid()}" in again.json()["message"]
    # And the terminal is refused too, before anything loads.
    assert cli.main(["suno", str(recording[0]), "-o", str(tmp_path / "t.json")]) == 75

    stub.release_all()
    assert last_job(client, finished)["state"] == "done"
    assert len(client.get("/api/jobs").json()) == 1


def test_a_job_is_refused_while_a_terminal_run_holds_the_machine(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine()
    held = runlock.acquire({"pid": 4242, "out": "/tmp/terminal-run.json"})
    try:
        client = page()
        reply = client.post(f"/api/recordings/{recording[1]}/transcribe", json={})
        assert reply.status_code == 409, reply.text
        assert "pid 4242" in reply.json()["message"]
        assert "/tmp/terminal-run.json" in reply.json()["message"]
        assert client.get("/api/jobs").json() == []
    finally:
        os.close(held)


def test_a_recording_in_a_cloud_synced_folder_is_transcribed_and_left_untagged(
    engine: Callable[..., StubEngine], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A cloud file is transcribed like any other; it just carries no tag (#202).

    The folder is a fake one under a temporary home, never the real
    ~/Library/CloudStorage.
    """
    from dsj.filetag import TRANSCRIPT_TAG, read_tag

    engine()
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    drive = home / "Library" / "CloudStorage" / "GoogleDrive-someone" / "My Drive"
    media = wav(drive / "standup.wav")
    recording_id = add(media)
    client = page()
    reply = client.post(f"/api/recordings/{recording_id}/transcribe", json={"diarize": False})
    assert reply.status_code == 202, reply.text
    job = last_job(client, finished)
    assert job["state"] == "done", job
    assert any("cloud-synced folder" in note for note in job["notes"]), job["notes"]
    assert read_tag(media, TRANSCRIPT_TAG) is None
    # Nothing was written beside it: the transcript sits beside the library.
    assert sorted(p.name for p in drive.iterdir()) == ["standup.wav"]
    assert jobs_mod.transcript_path(recording_id, job["engine"], job["model"], None).is_file()


def test_a_recording_whose_file_is_gone_is_refused(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine()
    media, recording_id = recording
    media.unlink()
    reply = page().post(f"/api/recordings/{recording_id}/transcribe", json={})
    assert reply.status_code == 422, reply.text
    assert "is not there any more" in reply.json()["message"]


@pytest.mark.parametrize("given", ["99", "abc", "-1"])
def test_a_recording_the_library_does_not_have_is_404(given: str) -> None:
    reply = page().post(f"/api/recordings/{given}/transcribe", json={})
    assert reply.status_code == 404, reply.text


# -- the server stays up under a run -------------------------------------------


def test_a_running_job_keeps_the_server_from_stopping_idle() -> None:
    now = [0.0]
    beats = Heartbeat(clock=lambda: now[0])
    with beats.hold():
        now[0] = 1000.0
        assert beats.idle_s() == 0.0
    # The idle minute starts when the run ends, not when the page last beat.
    now[0] = 1010.0
    assert beats.idle_s() == 10.0
