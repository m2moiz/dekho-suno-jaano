"""Marks on a transcript that are still there tomorrow (#67).

A mark is a stretch of the recording, in seconds, with a kind, a note and the
words it covered when it was made. Seconds, not character positions (#106,
#83): a correction keeps a word's time, and a re-run of the same recording
with the same words gives the same times, so the mark sits on the same words
in both. Marks hang off the recording, so every transcript of it shows them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from test_ui_library import page, transcript, two_recordings, wav

from dsj.ui import store
from dsj.ui.store import Library

__all__ = ["two_recordings"]


def _recording(client: TestClient, name: str) -> int:
    rows = client.get("/api/recordings").json()
    (row,) = [r for r in rows if Path(r["path"]).name == name]
    found: int = row["id"]
    return found


def test_a_mark_is_made_listed_changed_and_removed(two_recordings: dict[str, Path]) -> None:
    client = page()
    rid = _recording(client, "review.wav")
    assert client.get(f"/api/recordings/{rid}/highlights").json() == []
    reply = client.post(
        f"/api/recordings/{rid}/highlights",
        json={"start_s": 0.4, "end_s": 1.1, "kind": "key", "text": "the number"},
    )
    assert reply.status_code == 201, reply.text
    made = reply.json()
    assert made["kind"] == "key"
    assert made["note"] == ""
    assert made["text"] == "the number"
    assert made["start_s"] == 0.4
    (listed,) = client.get(f"/api/recordings/{rid}/highlights").json()
    assert listed == made

    reply = client.patch(
        f"/api/highlights/{made['id']}", json={"note": "ask again", "kind": "question"}
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["note"] == "ask again"
    assert reply.json()["kind"] == "question"
    assert reply.json()["text"] == "the number"

    assert client.delete(f"/api/highlights/{made['id']}").status_code == 204
    assert client.get(f"/api/recordings/{rid}/highlights").json() == []
    assert client.delete(f"/api/highlights/{made['id']}").status_code == 404


def test_a_mark_survives_a_new_launch_and_a_new_run_of_the_same_recording(
    two_recordings: dict[str, Path], tmp_path: Path
) -> None:
    client = page()
    rid = _recording(client, "review.wav")
    made = client.post(
        f"/api/recordings/{rid}/highlights", json={"start_s": 0.4, "end_s": 1.1, "kind": "key"}
    ).json()
    # Transcribed again, same words: a new transcript row on the same recording.
    from datetime import UTC, datetime

    again = transcript(tmp_path / "review-again.json", two_recordings["new"], datetime.now(UTC))
    with Library.open() as library:
        library.record_run(again, engine="parakeet", language=None)
    # A new launch reads the same library.
    assert page().get(f"/api/recordings/{rid}/highlights").json() == [made]


def test_what_is_refused(two_recordings: dict[str, Path]) -> None:
    client = page()
    rid = _recording(client, "review.wav")
    path = f"/api/recordings/{rid}/highlights"
    assert client.post(path, json={"start_s": 2.0, "end_s": 1.0, "kind": "key"}).status_code == 422
    assert client.post(path, json={"start_s": 0.0, "end_s": 1.0, "kind": "neon"}).status_code == 422
    assert (
        client.post(
            "/api/recordings/999/highlights", json={"start_s": 0.0, "end_s": 1.0, "kind": "key"}
        ).status_code
        == 404
    )
    assert client.get("/api/recordings/x/highlights").status_code == 404
    assert client.patch("/api/highlights/999", json={"note": "x"}).status_code == 404


def test_marks_export_as_markdown_with_timestamps(two_recordings: dict[str, Path]) -> None:
    client = page()
    rid = _recording(client, "review.wav")
    path = f"/api/recordings/{rid}/highlights"
    client.post(
        path,
        json={
            "start_s": 65.0,
            "end_s": 70.5,
            "kind": "question",
            "text": "why is it late",
            "note": "ask Ali",
        },
    )
    client.post(
        path, json={"start_s": 1.25, "end_s": 2.0, "kind": "key", "text": "the number is nine"}
    )
    reply = client.get(f"{path}.md")
    assert reply.status_code == 200, reply.text
    assert reply.headers["content-type"].startswith("text/markdown")
    lines = reply.text.splitlines()
    assert lines[0] == "# Marks: review"
    # In the order of the recording, each with its time, kind, words and note.
    assert "- **0:01** key: the number is nine" in lines
    assert "- **1:05** question: why is it late" in lines
    assert "  ask Ali" in lines


def test_a_version_7_library_gains_the_highlights_table_and_keeps_its_rows(tmp_path: Path) -> None:
    media = wav(tmp_path / "old.wav", 440)
    with Library.open() as library:
        rid = library.add_recording(media).id
    with sqlite3.connect(store.library_path()) as con:
        con.execute("DROP TABLE highlights")
        con.execute("PRAGMA user_version = 7")
    with Library.open() as library:
        assert library.recording(rid) is not None
        assert library.highlights(rid) == []
        made = library.add_highlight(rid, 0.0, 1.0, "key", "", "hello")
        assert library.highlights(rid) == [made]
    with sqlite3.connect(store.library_path()) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION == 8
