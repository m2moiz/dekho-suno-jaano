"""The library page's routes (#156), against a real library of real files.

Each test's library is its own (conftest points DSJ_LIBRARY into a temporary
directory), its recordings are two seconds of tone made by ffmpeg, and its
transcripts are JSON files written the way `dsj suno` writes them.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dsj.ui.server import create_app
from dsj.ui.store import Library

LONG_AGO = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
LATER = datetime(2026, 9, 20, 17, 5, tzinfo=UTC)


def page() -> TestClient:
    """A fresh `dsj ui` launch, asked the way its page asks."""
    app, token = create_app(port=8721)
    return TestClient(
        app, base_url="http://127.0.0.1:8721", headers={"Authorization": f"Bearer {token}"}
    )


def wav(path: Path, hz: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency={hz}:duration=2", str(path)],
        check=True,
    )
    return path


def transcript(path: Path, audio: Path, when: datetime, **extra: Any) -> Path:
    payload: dict[str, Any] = {
        "audio": str(audio),
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "text": " Hello.",
        "unclear": [],
        "sentences": [{"start": 0.0, "end": 1.0, "text": " Hello.", "tokens": []}],
    }
    path.write_text(json.dumps(payload | extra))
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


@pytest.fixture
def two_recordings(tmp_path: Path) -> dict[str, Path]:
    """An older recording adopted, with one speaker labelled; a newer one run from the app."""
    old = wav(tmp_path / "standup.wav", 440)
    new = wav(tmp_path / "review.wav", 660)
    labelled = transcript(
        tmp_path / "standup.json", old, LONG_AGO,
        speakers=[{"id": "SPEAKER_00"}], diarization={"model": "senko"},
    )
    unlabelled = transcript(tmp_path / "review.json", new, LATER)
    with Library.open() as library:
        assert not library.adopt([labelled]).refused
        library.record_run(unlabelled, engine="whisper", language="ur")
    return {"old": old, "new": new, "labelled": labelled, "unlabelled": unlabelled}


def test_two_recordings_newest_first_with_date_engine_and_model(
    two_recordings: dict[str, Path],
) -> None:
    reply = page().get("/api/recordings")
    assert reply.status_code == 200, reply.text
    rows = reply.json()
    assert [Path(r["path"]).name for r in rows] == ["review.wav", "standup.wav"]
    newer, older = rows
    (run,) = newer["transcripts"]
    assert run["engine"] == "whisper"
    assert run["language"] == "ur"
    assert run["model"] == "mlx-community/parakeet-tdt-0.6b-v3"
    # record_run stamps the moment it was told, which is now, not the file's mtime.
    assert datetime.fromisoformat(run["finished_at"]) > LATER
    (adopted,) = older["transcripts"]
    assert adopted["finished_at"] == LONG_AGO.isoformat()
    # Adopted, so nobody saw which engine ran: unknown, not guessed from the model.
    assert adopted["engine"] is None
    assert not newer["missing"]
    assert not older["missing"]
    assert older["duration_s"] == pytest.approx(2.0, abs=0.1)


def test_speakers_not_labelled_is_not_one_speaker(two_recordings: dict[str, Path]) -> None:
    newer, older = page().get("/api/recordings").json()
    (unlabelled,) = newer["transcripts"]
    (labelled,) = older["transcripts"]
    assert unlabelled["diarized"] is False
    assert unlabelled["speaker_count"] is None
    assert labelled["diarized"] is True
    assert labelled["speaker_count"] == 1


def test_restarting_dsj_ui_shows_the_same_list(two_recordings: dict[str, Path]) -> None:
    first = page().get("/api/recordings").json()
    # A second launch: a new app, a new token, the same library file.
    second = page().get("/api/recordings").json()
    assert first == second
    assert len(first) == 2


def test_a_missing_recording_stays_listed_with_its_last_known_path(
    two_recordings: dict[str, Path],
) -> None:
    gone = two_recordings["old"]
    gone.unlink()
    rows = page().get("/api/recordings").json()
    (row,) = [r for r in rows if r["path"] == str(gone)]
    assert row["missing"] is True
    assert row["transcripts"], "its transcripts stay with it"


def test_a_recording_already_gone_when_adopted_is_listed_missing(tmp_path: Path) -> None:
    never = tmp_path / "deleted-before-adoption.m4a"
    with Library.open() as library:
        library.adopt([transcript(tmp_path / "orphan.json", never, LONG_AGO)])
    (row,) = page().get("/api/recordings").json()
    assert row["missing"] is True
    assert row["path"] == str(never)
    assert row["duration_s"] is None


def test_a_transcript_is_sent_exactly_as_its_file_holds_it(
    two_recordings: dict[str, Path],
) -> None:
    client = page()
    rows = client.get("/api/recordings").json()
    assert len(rows) == 2, "with no rows this test would check nothing"
    for row in rows:
        (meta,) = row["transcripts"]
        reply = client.get(f"/api/transcripts/{meta['id']}")
        assert reply.status_code == 200
        assert reply.headers["content-type"] == "application/json"
        wanted = two_recordings["unlabelled" if meta["engine"] else "labelled"]
        assert reply.content == wanted.read_bytes()


@pytest.mark.parametrize(
    "bad", ["..", "%2e%2e", "1%2F2", "..%2F1", "1/..", "-1", "1.0", "abc", " 1", "99999", "\uff11"]
)
def test_an_id_that_is_not_a_known_number_is_404(
    bad: str, two_recordings: dict[str, Path]
) -> None:
    # "\uff11" is a fullwidth digit one: str.isdigit() says yes, int() would take it.
    reply = page().get(f"/api/transcripts/{bad}")
    assert reply.status_code == 404, (bad, reply.status_code, reply.text)
    for path in two_recordings.values():
        if path.suffix == ".json":
            assert reply.content != path.read_bytes()


def test_a_transcript_whose_file_is_gone_says_so(two_recordings: dict[str, Path]) -> None:
    client = page()
    ids = [row["transcripts"][0]["id"] for row in client.get("/api/recordings").json()]
    two_recordings["labelled"].unlink()
    replies = [client.get(f"/api/transcripts/{i}") for i in ids]
    assert sorted(r.status_code for r in replies) == [200, 404]
    (gone,) = [r for r in replies if r.status_code == 404]
    assert "is gone" in gone.json()["detail"]


def test_an_empty_library_is_an_empty_list() -> None:
    assert page().get("/api/recordings").json() == []
