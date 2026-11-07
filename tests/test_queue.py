"""A queue of transcriptions (#90): start several, walk away, come back to all of them.

One job runs at a time on the one worker thread; the rest wait their turn
behind it and read `queued` until it comes. A job that fails records its
error and the next one starts all the same. A stop (#72) on a queued job
takes it out of the line without running it. A terminal run holding the
machine still refuses the start outright: nothing of ours is in flight to
wait behind.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_jobs import StubEngine, add, engine, page, recording, wav

from dsj import runlock
from dsj.ui.store import Library

__all__ = ["engine", "recording"]  # the fixtures, imported by name for pytest to find


def _start(client: TestClient, recording_id: int) -> dict[str, Any]:
    reply = client.post(f"/api/recordings/{recording_id}/transcribe", json={"diarize": False})
    assert reply.status_code == 202, reply.text
    started: dict[str, Any] = reply.json()
    return started


def _job(
    client: TestClient, job_id: int, until: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 20
    while True:
        listed: list[dict[str, Any]] = client.get("/api/jobs").json()
        (found,) = [j for j in listed if j["id"] == job_id]
        if until(found):
            return found
        assert time.monotonic() < deadline, f"waited 20 s; job {job_id} reads {found}"
        time.sleep(0.02)


def test_a_second_recording_waits_its_turn_and_then_runs(
    engine: Callable[..., StubEngine], recording: tuple[Path, int], tmp_path: Path
) -> None:
    stub = engine(chunks=1, held=True)
    second = add(wav(tmp_path / "second.wav"))
    client = page()
    first = _start(client, recording[1])
    queued = _start(client, second)
    assert queued["state"] == "queued"
    assert queued["id"] == first["id"] + 1
    # Still queued while the first holds the machine.
    assert _job(client, queued["id"], lambda j: True)["state"] == "queued"
    stub.release_all()
    assert _job(client, first["id"], lambda j: j["state"] == "done")["transcript_id"] is not None
    assert _job(client, queued["id"], lambda j: j["state"] == "done")["transcript_id"] is not None
    assert len(client.get("/api/jobs").json()) == 2
    os.close(runlock.acquire({"pid": os.getpid()}))  # the machine is free again


def test_a_failure_records_its_error_and_the_next_one_still_starts(
    engine: Callable[..., StubEngine],
    recording: tuple[Path, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = engine(chunks=1, held=True)
    second = add(wav(tmp_path / "second.wav"))
    client = page()
    first = _start(client, recording[1])
    queued = _start(client, second)
    # The first dies once released, writing its library row; the second's write is the real one.
    real = Library.record_run

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        monkeypatch.setattr(Library, "record_run", real)
        raise RuntimeError("the model exploded")

    monkeypatch.setattr(Library, "record_run", explode)
    stub.release_all()
    failed = _job(client, first["id"], lambda j: j["state"] == "failed")
    assert failed["error"] == "RuntimeError: the model exploded"
    assert _job(client, queued["id"], lambda j: j["state"] == "done")["state"] == "done"
    os.close(runlock.acquire({"pid": os.getpid()}))


def test_a_stop_on_a_queued_job_takes_it_out_of_the_line_without_running_it(
    engine: Callable[..., StubEngine], recording: tuple[Path, int], tmp_path: Path
) -> None:
    stub = engine(chunks=1, held=True)
    second = add(wav(tmp_path / "second.wav"))
    client = page()
    first = _start(client, recording[1])
    queued = _start(client, second)
    assert client.post(f"/api/jobs/{queued['id']}/cancel").status_code == 202
    stub.release_all()
    assert _job(client, first["id"], lambda j: j["state"] == "done")["state"] == "done"
    gone = _job(client, queued["id"], lambda j: j["state"] == "cancelled")
    assert gone["transcript_id"] is None
    assert gone["error"] is None
    assert len(stub.calls) == 1  # the chunk loop ran once: the first job's
    os.close(runlock.acquire({"pid": os.getpid()}))


def test_a_terminal_run_holding_the_machine_still_refuses_the_start(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine()
    held = runlock.acquire({"pid": 4242, "out": "/tmp/terminal-run.json"})
    try:
        client = page()
        reply = client.post(f"/api/recordings/{recording[1]}/transcribe", json={})
        assert reply.status_code == 409, reply.text
        assert "pid 4242" in reply.json()["message"]
        assert client.get("/api/jobs").json() == []
    finally:
        os.close(held)
