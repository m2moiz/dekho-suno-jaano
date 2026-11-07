"""A first run's model download shows its progress on the job (#337).

The engines fetch their models through huggingface_hub inside the load, which
says nothing to the job. While the job is still loading, a watcher reads how
many bytes the hub cache holds for the model, finished blobs and `.incomplete`
ones alike, and the job carries it as `download_mb`, so a first run on a slow
connection reads as a download, not as a hang.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_jobs import StubEngine, engine, last_job, page, recording

from dsj.ui import download
from dsj.ui.jobs import DEFAULT_MODELS

__all__ = ["engine", "recording"]


def _repo(cache: Path, model: str) -> Path:
    repo = cache / f"models--{model.replace('/', '--')}"
    (repo / "blobs").mkdir(parents=True)
    (repo / "snapshots").mkdir()
    return repo


def test_the_bytes_in_the_cache_count_finished_and_unfinished_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert download.downloaded_bytes("org/model") is None
    repo = _repo(tmp_path, "org/model")
    assert download.downloaded_bytes("org/model") == 0
    (repo / "blobs" / "aa").write_bytes(b"x" * 1000)
    (repo / "blobs" / "bb.incomplete").write_bytes(b"y" * 500)
    assert download.downloaded_bytes("org/model") == 1500


def test_a_job_says_how_much_of_its_model_has_come_while_it_loads(
    engine: Callable[..., StubEngine],
    recording: tuple[Path, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(download, "EVERY_S", 0.02)
    gate = threading.Event()
    engine(load_gate=gate)
    client: TestClient = page()
    reply = client.post(f"/api/recordings/{recording[1]}/transcribe", json={"diarize": False})
    assert reply.status_code == 202, reply.text
    job_id = reply.json()["id"]
    assert reply.json()["download_mb"] is None
    try:
        # The hub starts writing the model's blobs while the engine loads.
        repo = _repo(tmp_path, DEFAULT_MODELS["parakeet"])
        (repo / "blobs" / "cc.incomplete").write_bytes(b"z" * 3_000_000)
        seen = _job(client, job_id, lambda j: (j["download_mb"] or 0) >= 2.9)
        assert seen["state"] == "starting"
        assert seen["download_mb"] == pytest.approx(3.0, abs=0.1)
    finally:
        gate.set()
    assert last_job(client, lambda j: j["state"] == "done")["state"] == "done"


def test_an_engine_without_a_hub_model_shows_no_download(
    engine: Callable[..., StubEngine],
    recording: tuple[Path, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    engine()
    client = page()
    reply = client.post(
        f"/api/recordings/{recording[1]}/transcribe", json={"engine": "sherpa", "diarize": False}
    )
    assert reply.status_code == 202, reply.text
    assert last_job(client, lambda j: j["state"] == "done")["download_mb"] is None


def _job(
    client: TestClient, job_id: int, until: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while True:
        listed: list[dict[str, Any]] = client.get("/api/jobs").json()
        (found,) = [j for j in listed if j["id"] == job_id]
        if until(found):
            return found
        assert time.monotonic() < deadline, f"waited 20 s; job {job_id} reads {found}"
        time.sleep(0.02)
