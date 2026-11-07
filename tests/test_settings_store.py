"""The app's settings store (#69) and its versioned migrations (#131).

One JSON file beside the library, carrying a version number from its first
commit, typed keys with defaults, and a migration list run at every read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dsj.ui import settings
from dsj.ui.server import create_app
from dsj.ui.store import library_path


def page() -> TestClient:
    app, token = create_app(port=8721)
    return TestClient(
        app, base_url="http://127.0.0.1:8721", headers={"Authorization": f"Bearer {token}"}
    )


# -- the file ------------------------------------------------------------------


def test_the_store_sits_beside_the_library_and_is_not_written_until_a_change() -> None:
    assert settings.settings_path() == library_path().with_name("settings.json")
    found = settings.read_settings()
    assert found == settings.Settings()
    assert found.transcribe_answer == "mixed"
    assert found.transcribe_diarize is True
    assert not settings.settings_path().exists()


def test_a_change_is_written_with_the_version_and_read_back() -> None:
    saved = settings.write_settings(transcribe_answer="urdu", transcribe_diarize=False)
    assert saved == settings.Settings(transcribe_answer="urdu", transcribe_diarize=False)
    on_disk = json.loads(settings.settings_path().read_text())
    assert on_disk["version"] == settings.SETTINGS_VERSION
    assert on_disk["transcribe_answer"] == "urdu"
    assert settings.read_settings() == saved
    # A later change keeps what it did not touch.
    assert settings.write_settings(transcribe_diarize=True).transcribe_answer == "urdu"


def test_a_key_this_dsj_does_not_know_survives_a_write() -> None:
    """A newer dsj's key, or a hand edit, is kept as read, never dropped."""
    settings.settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path().write_text(
        json.dumps({"version": settings.SETTINGS_VERSION, "someday": {"a": 1}})
    )
    settings.write_settings(transcribe_answer="english")
    on_disk = json.loads(settings.settings_path().read_text())
    assert on_disk["someday"] == {"a": 1}
    assert on_disk["transcribe_answer"] == "english"


def test_a_value_the_key_does_not_allow_reads_as_the_default() -> None:
    settings.settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path().write_text(
        json.dumps({"version": settings.SETTINGS_VERSION, "transcribe_answer": "klingon",
                    "transcribe_diarize": "yes"})
    )
    found = settings.read_settings()
    assert found.transcribe_answer == "mixed"
    assert found.transcribe_diarize is True


def test_a_file_a_newer_dsj_wrote_is_refused_by_name() -> None:
    settings.settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path().write_text(json.dumps({"version": settings.SETTINGS_VERSION + 1}))
    with pytest.raises(settings.SettingsError, match="newer dsj"):
        settings.read_settings()


def test_a_file_that_is_not_json_is_refused_with_its_path() -> None:
    settings.settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path().write_text("{not json")
    with pytest.raises(settings.SettingsError, match=str(settings.settings_path())):
        settings.read_settings()


# -- migrations (#131) ---------------------------------------------------------


def _version_1(**keys: Any) -> Path:
    """A store file as the first commit writes it (version 1, the two transcribe keys)."""
    path = settings.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "transcribe_answer": "urdu",
                                "transcribe_diarize": False, **keys}))
    return path


def _rename_answer(raw: dict[str, Any]) -> dict[str, Any]:
    if "transcribe_answer" in raw:
        raw["answer"] = raw.pop("transcribe_answer")
    return raw


def _count_runs(raw: dict[str, Any]) -> dict[str, Any]:
    raw["runs"] = raw.get("runs", 0) + 1
    return raw


def test_the_first_commit_is_version_1_and_reads_with_no_migration_to_run() -> None:
    _version_1()
    assert settings.SETTINGS_VERSION == 1
    assert settings._MIGRATIONS == {}  # pyright: ignore[reportPrivateUsage]
    found = settings.read_settings()
    assert found == settings.Settings(transcribe_answer="urdu", transcribe_diarize=False)


def test_migrations_run_in_order_from_the_stored_version_and_stamp_each_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two steps, 1 to 2 and 2 to 3, each written to disk with its version as it lands."""
    stamped: list[int] = []
    real_write = settings._write  # pyright: ignore[reportPrivateUsage]

    def spy(path: Path, raw: dict[str, Any]) -> None:
        stamped.append(int(raw["version"]))
        real_write(path, raw)

    monkeypatch.setattr(settings, "_write", spy)
    monkeypatch.setattr(settings, "SETTINGS_VERSION", 3)
    monkeypatch.setattr(settings, "_MIGRATIONS", {1: _rename_answer, 2: _count_runs})
    _version_1()
    settings.read_settings()
    on_disk = json.loads(settings.settings_path().read_text())
    assert on_disk["version"] == 3
    assert on_disk["answer"] == "urdu"
    assert "transcribe_answer" not in on_disk
    assert on_disk["runs"] == 1
    assert stamped == [2, 3]


def test_a_migration_run_twice_leaves_the_store_as_running_it_once_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash right after a step's write: the next boot runs it again from the stamp it finds."""
    monkeypatch.setattr(settings, "SETTINGS_VERSION", 2)
    monkeypatch.setattr(settings, "_MIGRATIONS", {1: _rename_answer})
    _version_1()
    settings.read_settings()
    once = json.loads(settings.settings_path().read_text())
    # The crash: the file is back at version 1 with the step's work already in it.
    settings.settings_path().write_text(json.dumps({**once, "version": 1}))
    settings.read_settings()
    assert json.loads(settings.settings_path().read_text()) == once


def test_a_step_that_raises_leaves_the_file_at_the_version_before_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_raw: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("no")

    monkeypatch.setattr(settings, "SETTINGS_VERSION", 3)
    monkeypatch.setattr(settings, "_MIGRATIONS", {1: _rename_answer, 2: broken})
    _version_1()
    with pytest.raises(ValueError, match="no"):
        settings.read_settings()
    on_disk = json.loads(settings.settings_path().read_text())
    assert on_disk["version"] == 2
    assert on_disk["answer"] == "urdu"


# -- the route -----------------------------------------------------------------


def test_the_route_reads_the_defaults_and_keeps_a_change_across_launches() -> None:
    client = page()
    reply = client.get("/api/settings")
    assert reply.status_code == 200, reply.text
    assert reply.json() == {
        "version": 1, "transcribe_answer": "mixed", "transcribe_diarize": True,
        "export_formats": [], "export_overwrite": False,
    }
    reply = client.put("/api/settings", json={"transcribe_answer": "english"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["transcribe_answer"] == "english"
    assert reply.json()["transcribe_diarize"] is True
    # The next launch of `dsj ui` reads the same file.
    assert page().get("/api/settings").json()["transcribe_answer"] == "english"


def test_the_route_refuses_an_answer_the_dialog_does_not_offer() -> None:
    assert page().put("/api/settings", json={"transcribe_answer": "klingon"}).status_code == 422
