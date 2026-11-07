"""The first-run gate (#70): ffmpeg, an engine and its model, asked before a run starts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dsj.ui import download, readiness
from dsj.ui.server import create_app

LOOPBACK = "http://127.0.0.1:8721"


def _nowhere(_name: str) -> str | None:
    """Stands in for shutil.which on a Mac with no ffmpeg."""
    return None


def _homebrew(name: str) -> str | None:
    """Stands in for shutil.which on a Mac with ffmpeg from Homebrew."""
    return f"/opt/homebrew/bin/{name}"


def test_a_missing_ffmpeg_is_named_with_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness.shutil, "which", _nowhere)
    found = readiness.tool_state("ffmpeg")
    assert not found.ok
    assert found.path is None
    assert found.reason is not None
    assert "ffmpeg is not on PATH" in found.reason
    assert "brew install ffmpeg" in found.reason


def test_a_present_ffmpeg_says_where(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness.shutil, "which", _homebrew)
    found = readiness.tool_state("ffprobe")
    assert found.ok
    assert found.path == "/opt/homebrew/bin/ffprobe"
    assert found.reason is None


def _hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "hub"
    cache.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    return cache


def _repo(cache: Path, model: str, *, whole: bool) -> Path:
    repo = cache / f"models--{model.replace('/', '--')}"
    (repo / "snapshots" / "abc").mkdir(parents=True)
    (repo / "blobs").mkdir()
    (repo / "blobs" / "0123").write_bytes(b"weights")
    if not whole:
        (repo / "blobs" / "4567.incomplete").write_bytes(b"half")
    return repo


def test_a_model_is_missing_until_its_first_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hub(tmp_path, monkeypatch)
    found = readiness.model_state("parakeet", "mlx-community/parakeet-tdt-0.6b-v3")
    assert found.state == "missing"
    assert "the first run downloads it" in found.reason


def test_a_whole_model_is_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _hub(tmp_path, monkeypatch)
    _repo(cache, "mlx-community/whisper-large-v3-turbo", whole=True)
    found = readiness.model_state("whisper", "mlx-community/whisper-large-v3-turbo")
    assert found.state == "present"


def test_a_truncated_download_is_seen_before_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `.incomplete` blob is a download that stopped; the engine would resume it mid-run."""
    cache = _hub(tmp_path, monkeypatch)
    _repo(cache, "mlx-community/parakeet-tdt-0.6b-v3", whole=False)
    found = readiness.model_state("parakeet", "mlx-community/parakeet-tdt-0.6b-v3")
    assert found.state == "partial"
    assert "did not finish" in found.reason


def test_the_hub_cache_follows_hf_home_when_hf_hub_cache_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert download._hub_cache() == tmp_path / "hf" / "hub"  # pyright: ignore[reportPrivateUsage]


def test_a_sherpa_model_is_a_folder_on_disk(tmp_path: Path) -> None:
    assert readiness.model_state("sherpa", str(tmp_path / "nope")).state == "missing"
    (tmp_path / "model").mkdir()
    assert readiness.model_state("sherpa", str(tmp_path / "model")).state == "present"


def test_the_readiness_route_answers_all_three_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness.shutil, "which", _nowhere)
    app, token = create_app(port=8721)
    reply = TestClient(app, base_url=LOOPBACK).get(
        "/api/readiness", headers={"Authorization": f"Bearer {token}"}
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert [t["name"] for t in body["tools"]] == ["ffmpeg", "ffprobe"]
    assert all(not t["ok"] for t in body["tools"])
    assert body["ready"] is False
    assert {e["name"] for e in body["engines"]} >= {"parakeet", "whisper", "sherpa"}
    # One model row per engine that can run here, none for one that cannot.
    runnable = {e["name"] for e in body["engines"] if e["reason"] is None}
    assert {m["engine"] for m in body["models"]} == runnable
