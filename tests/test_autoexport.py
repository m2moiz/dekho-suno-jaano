"""A transcript is exported when its job finishes, without being asked (#132).

The formats and the overwrite policy are settings (dsj/ui/settings.py); the
destination is beside the recording. Each job records what happened to each
format: exported, skipped (a file was there and overwriting is off), or
failed, with why. The job itself never fails over an export.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_jobs import StubEngine, engine, last_job, page, recording

from dsj.ui import autoexport, settings

__all__ = ["engine", "recording"]  # the fixtures, imported by name for pytest to find


def _run(client: Any, recording_id: int) -> dict[str, Any]:
    reply = client.post(f"/api/recordings/{recording_id}/transcribe", json={"diarize": False})
    assert reply.status_code == 202, reply.text
    job: dict[str, Any] = last_job(client, lambda j: j["state"] in ("done", "failed"))
    return job


def test_nothing_is_written_until_a_format_is_turned_on(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine()
    media, rid = recording
    job = _run(page(), rid)
    assert job["state"] == "done"
    assert job["exports"] == []
    assert sorted(p.name for p in media.parent.iterdir()) == [media.name]


def test_the_configured_formats_land_beside_the_recording_when_the_job_is_done(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine()
    media, rid = recording
    client = page()
    reply = client.put("/api/settings", json={"export_formats": ["srt", "txt"]})
    assert reply.status_code == 200, reply.text
    assert reply.json()["export_formats"] == ["srt", "txt"]
    job = _run(client, rid)
    assert job["state"] == "done"
    srt, txt = media.with_suffix(".srt"), media.with_suffix(".txt")
    assert [(e["format"], e["outcome"], e["path"]) for e in job["exports"]] == [
        ("srt", "exported", str(srt)),
        ("txt", "exported", str(txt)),
    ]
    assert "Hello." in txt.read_text()
    assert "-->" in srt.read_text()
    assert not media.with_suffix(".vtt").exists()


def test_a_file_already_there_is_skipped_or_overwritten_as_the_setting_says(
    engine: Callable[..., StubEngine], recording: tuple[Path, int]
) -> None:
    engine()
    media, rid = recording
    client = page()
    client.put("/api/settings", json={"export_formats": ["txt"]})
    txt = media.with_suffix(".txt")
    txt.write_text("someone's own notes\n")
    job = _run(client, rid)
    (result,) = job["exports"]
    assert result["outcome"] == "skipped"
    assert "already there" in result["reason"]
    assert txt.read_text() == "someone's own notes\n"

    engine()
    client.put("/api/settings", json={"export_overwrite": True})
    job = _run(client, rid)
    (result,) = job["exports"]
    assert result["outcome"] == "exported"
    assert "Hello." in txt.read_text()


def test_an_export_that_fails_is_recorded_with_why_and_the_job_still_finishes(
    engine: Callable[..., StubEngine], recording: tuple[Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_path: Path, _text: str, **_: Any) -> None:
        raise PermissionError("read-only folder")

    monkeypatch.setattr(autoexport, "atomic_write_text", refuse)
    engine()
    _media, rid = recording
    client = page()
    client.put("/api/settings", json={"export_formats": ["vtt"]})
    job = _run(client, rid)
    assert job["state"] == "done"
    assert job["transcript_id"] is not None
    (result,) = job["exports"]
    assert result["outcome"] == "failed"
    assert "PermissionError: read-only folder" in result["reason"]


def test_a_format_dsj_cannot_write_is_refused_before_it_is_kept() -> None:
    client = page()
    assert client.put("/api/settings", json={"export_formats": ["docx"]}).status_code == 422
    assert settings.read_settings().export_formats == ()


def test_the_export_formats_and_policy_are_settings_with_the_other_keys() -> None:
    found = settings.write_settings(export_formats=["vtt"], export_overwrite=True)
    assert found.export_formats == ("vtt",)
    assert found.export_overwrite is True
    on_disk = json.loads(settings.settings_path().read_text())
    assert on_disk["export_formats"] == ["vtt"]
    # A list holding anything but a format dsj writes reads as nothing turned on.
    settings.settings_path().write_text(json.dumps({**on_disk, "export_formats": ["srt", 3]}))
    assert settings.read_settings().export_formats == ()
