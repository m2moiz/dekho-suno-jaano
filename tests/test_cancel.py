"""Stopping a transcription from the page (#72).

A stop lands at the run's next report: for the chunk engines, after the chunk
in flight is banked, so the next run resumes from it; for whisper, when its
window loop next reports or when its decode is over. The status file says
`interrupted` with `cancel` for its signal, the way Ctrl-C says `SIGINT`
(#143), the job reads `cancelled`, and the machine is free for the next run.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from test_jobs import CHUNK, RATE, StubEngine, any_engine, engine, last_job, page, recording

from dsj import media as media_mod
from dsj import runlock, suno
from dsj.checkpoint import checkpoint_path_for
from dsj.ui import jobs as jobs_mod

__all__ = ["engine", "recording"]  # the fixtures, imported by name for pytest to find


def _started(client: TestClient, recording_id: int) -> dict[str, Any]:
    reply = client.post(f"/api/recordings/{recording_id}/transcribe", json={"diarize": False})
    assert reply.status_code == 202, reply.text
    started: dict[str, Any] = reply.json()
    return started


def _runner(client: TestClient) -> jobs_mod.Jobs:
    """The app's own job runner, for what the page is not told: the status and output paths."""
    return cast("jobs_mod.Jobs", cast("Any", client.app).state.jobs)


def test_a_stop_lands_after_the_chunk_in_flight_and_the_next_run_resumes_from_it(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    stub = engine(chunks=3, held=True)
    client = page()
    job = _started(client, recording[1])
    stub.release(0)
    last_job(client, lambda j: j["fraction"] >= round(1 / 3, 4))

    reply = client.post(f"/api/jobs/{job['id']}/cancel")
    assert reply.status_code == 202, reply.text
    assert reply.json()["state"] == "stopping"

    # The chunk in flight finishes and is banked; the run stops there, not after chunk 2.
    stub.release(1)
    stopped = last_job(client, lambda j: j["state"] == "cancelled")
    assert stopped["transcript_id"] is None
    assert stopped["error"] is None
    assert stopped["resumable"] is True
    assert len(stub.calls) == 1

    # The status file says what Ctrl-C's says, naming the stop as the signal (#143).
    runner = _runner(client)
    frame = json.loads(runner.all()[-1].status_path.read_text())
    assert frame["state"] == "interrupted"
    assert frame["signal"] == "cancel"
    assert frame["during"] == "running"

    # The checkpoint names the second chunk's end, and the next run starts there.
    out = runner.all()[-1].out
    banked = json.loads(checkpoint_path_for(out).read_text())
    assert banked["next_start"] == 2 * (3 * CHUNK * RATE) // 3
    assert not out.exists()
    os.close(runlock.acquire({"pid": os.getpid()}))  # the machine is free again

    again = engine(chunks=3)
    _started(client, recording[1])
    assert last_job(client, lambda j: j["state"] == "done")["transcript_id"] is not None
    assert again.calls[-1]["skip_before"] == banked["next_start"]


def test_a_stop_on_a_run_that_is_over_is_refused_and_an_unknown_job_is_404(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine(chunks=1)
    client = page()
    job = _started(client, recording[1])
    last_job(client, lambda j: j["state"] == "done")
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409
    assert client.post("/api/jobs/999/cancel").status_code == 404
    assert client.post("/api/jobs/x/cancel").status_code == 404


def test_a_stop_asked_twice_is_one_stop(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    stub = engine(chunks=2, held=True)
    client = page()
    job = _started(client, recording[1])
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 202
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 202
    stub.release(0)
    assert last_job(client, lambda j: j["state"] == "cancelled")["state"] == "cancelled"
    os.close(runlock.acquire({"pid": os.getpid()}))


def test_whisper_is_said_to_start_over(
    monkeypatch: pytest.MonkeyPatch, recording: tuple[Path, int]
) -> None:
    """The whisper engine banks nothing until its decode is over; the page says so before a stop."""
    gate = threading.Event()

    def held(
        media: Path, out: Path, *, on_progress: Callable[[suno.Progress, str], None], **_: object
    ) -> dict[str, object]:
        assert gate.wait(20)
        # whisper's window loop reporting, with the stop already asked for.
        on_progress(suno.Progress(0.0, 2.0, 1.0), "running")
        raise AssertionError("the report should have raised")

    monkeypatch.setattr(suno, "transcribe", held)
    monkeypatch.setattr(jobs_mod, "get_engine", any_engine)
    client = page()
    reply = client.post(f"/api/recordings/{recording[1]}/transcribe", json={"engine": "whisper"})
    assert reply.status_code == 202, reply.text
    assert reply.json()["resumable"] is False
    assert client.post(f"/api/jobs/{reply.json()['id']}/cancel").status_code == 202
    gate.set()
    assert last_job(client, lambda j: j["state"] == "cancelled")["error"] is None
    os.close(runlock.acquire({"pid": os.getpid()}))


def test_transcribe_stops_at_its_next_report_and_writes_the_cancel(
    engine: Callable[..., StubEngine], tmp_path: Path
) -> None:
    """The run itself, with no server: the stop is a KeyboardInterrupt, so every cleanup runs."""
    from test_jobs import wav

    stub = engine(chunks=2, held=True)
    stub.release_all()
    media = wav(tmp_path / "a.wav")
    out = tmp_path / "out" / "a.json"
    out.parent.mkdir()
    status = tmp_path / "a.status.json"

    def stop(_progress: suno.Progress, _state: str) -> None:
        raise suno.Cancelled

    with pytest.raises(suno.Cancelled):
        suno.transcribe(media, out, status_path=status, diarize=False, on_progress=stop)
    frame = json.loads(status.read_text())
    assert frame["state"] == "interrupted"
    assert frame["signal"] == "cancel"
    assert not out.exists()


def test_a_stop_during_extraction_leaves_no_ffmpeg_behind(tmp_path: Path) -> None:
    """The extraction's own callback raises; ffmpeg's pipe closes and it exits (media._reap)."""
    source = tmp_path / "long.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=600", "-ar", "44100", "-ac", "2", str(source)],
        check=True,
    )
    dest = tmp_path / "audio-16k.wav"

    def stop(_done_s: float) -> None:
        raise suno.Cancelled

    with pytest.raises(suno.Cancelled):
        media_mod.extract_audio(source, dest, 16_000, on_progress=stop)
    # Nothing is still writing the destination: no ffmpeg names it.
    assert subprocess.run(["pgrep", "-f", str(dest)], capture_output=True).returncode == 1
