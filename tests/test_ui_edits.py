"""A transcript's edit list through the page's routes (#63, #66).

Each test's library is its own (conftest points DSJ_LIBRARY into a temporary
directory), its recording two seconds of tone made by ffmpeg, its transcript
written the way `dsj suno` writes one, every token with `t`, `e` and `c`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dsj import hatao
from dsj.ui.edits import edits_path
from dsj.ui.server import create_app
from dsj.ui.store import Library, library_path


def page() -> TestClient:
    app, token = create_app(port=8721)
    return TestClient(
        app, base_url="http://127.0.0.1:8721", headers={"Authorization": f"Bearer {token}"}
    )


def tokens(*words: tuple[float, float, str, float]) -> list[dict[str, Any]]:
    return [{"t": t, "e": e, "w": w, "c": c} for t, e, w, c in words]


@pytest.fixture
def seeded(tmp_path: Path) -> dict[str, Any]:
    """One recording, one transcript of two sentences, in the library."""
    audio = tmp_path / "talk.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=2", str(audio)],
        check=True,
    )
    payload = {
        "audio": str(audio),
        "engine": "parakeet",
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "speakers": ["SPEAKER_00", "SPEAKER_01"],
        "diarization": "senko",
        "text": " Hello there. Fine.",
        "unclear": [],
        "sentences": [
            {"start": 0.2, "end": 0.9, "speaker": 0, "text": " Hello there.",
             "tokens": tokens((0.2, 0.5, " Hello", 0.99), (0.56, 0.8, " there", 0.4),
                              (0.8, 0.88, ".", 0.97))},
            {"start": 1.2, "end": 1.6, "speaker": 1, "text": " Fine.",
             "tokens": tokens((1.2, 1.5, " Fine", 0.9), (1.5, 1.6, ".", 0.95))},
        ],
    }
    json_path = tmp_path / "talk.json"
    json_path.write_text(json.dumps(payload))
    with Library.open() as library:
        row = library.record_run(json_path, engine="parakeet")
    return {"id": row.id, "audio": audio, "json": json_path, "payload": payload}


def test_an_untouched_list_is_built_from_the_transcripts_own_word_ends(
    seeded: dict[str, Any],
) -> None:
    reply = page().get(f"/api/transcripts/{seeded['id']}/edits")
    assert reply.status_code == 200
    body = reply.json()
    assert body["edited_at"] is None
    assert body["pad_s"] == hatao.PAD_S
    items = [e for e in body["content"] if e["kind"] == "item"]
    there = next(e for e in items if e["text"] == " there")
    # Its own end, 0.8, never the next token's start.
    assert (there["sourceStart"], there["length"]) == (0.56, 0.24)
    assert there["confidence"] == 0.4
    # A pause has no word, so nothing to be sure of.
    assert all(e["confidence"] is None for e in items if e["text"] == "")
    speakers = [e["speaker"] for e in body["content"] if e["kind"] == "paragraph"]
    assert speakers == ["SPEAKER_00", "SPEAKER_01"]
    # No path reaches the page (#112 rule 5).
    assert str(seeded["audio"]) not in reply.text


def test_a_saved_list_comes_back_as_it_was_saved_and_the_recording_is_untouched(
    seeded: dict[str, Any],
) -> None:
    before = hashlib.sha256(seeded["audio"].read_bytes()).hexdigest()
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    there = next(i for i, e in enumerate(content) if e.get("text") == " there")
    content[there]["muted"] = True
    saved = client.put(route, json={"content": content})
    assert saved.status_code == 200, saved.text
    assert saved.json()["edited_at"] is not None
    again = page().get(route).json()
    assert again["content"] == content
    assert again["edited_at"] == saved.json()["edited_at"]
    # The file is dsj hatao's own format, playing the recording the library knows.
    doc = hatao.load(edits_path(seeded["json"]))
    assert doc.sources == {"0": str(seeded["audio"].resolve())}
    assert [e.text for e in doc.content if isinstance(e, hatao.Item) and e.muted] == [" there"]
    assert hashlib.sha256(seeded["audio"].read_bytes()).hexdigest() == before


def test_the_list_is_kept_beside_the_library_and_never_beside_the_recording(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    client.put(route, json={"content": client.get(route).json()["content"]})
    path = edits_path(seeded["json"])
    assert path.parent == library_path().parent / "edits"
    assert path.is_file()
    assert sorted(p.name for p in seeded["audio"].parent.iterdir()) == ["talk.json", "talk.wav"]


def test_a_broken_list_is_refused_whole_naming_the_entry(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    content[2]["length"] = -1.0
    reply = client.put(route, json={"content": content})
    assert reply.status_code == 422
    assert reply.json()["error"] == "InvalidDocument"
    assert "entry 2" in reply.json()["message"]
    assert not edits_path(seeded["json"]).exists()


def test_a_page_cannot_name_a_source_the_server_did_not_give_it(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    content[1]["source"] = "/etc/passwd"
    reply = client.put(route, json={"content": content})
    assert reply.status_code == 422
    assert "no such source" in reply.json()["message"]


def test_a_word_edited_by_hand_reads_as_sure(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    there = next(i for i, e in enumerate(content) if e.get("text") == " there")
    content[there]["text"] = " their"
    body = client.put(route, json={"content": content}).json()
    assert body["content"][there]["confidence"] == 1.0
    hello = next(e for e in body["content"] if e.get("text") == " Hello")
    assert hello["confidence"] == 0.99


def test_a_transcript_without_word_ends_reads_but_cannot_be_edited(tmp_path: Path) -> None:
    json_path = tmp_path / "old.json"
    json_path.write_text(json.dumps({
        "audio": str(tmp_path / "gone.wav"), "model": "m", "text": " Hi.", "unclear": [],
        "sentences": [
            {"start": 0.0, "end": 1.0, "text": " Hi.", "tokens": [{"t": 0.0, "w": " Hi."}]}
        ],
    }))
    with Library.open() as library:
        transcript_id = library.adopt([json_path]).transcripts[0]
    reply = page().get(f"/api/transcripts/{transcript_id}/edits")
    assert reply.status_code == 422
    assert reply.json()["error"] == "TranscriptUnusable"


@pytest.mark.parametrize("transcript_id", ["99", "..", "-1", "1.0"])
def test_an_id_that_is_not_a_known_number_is_404(transcript_id: str) -> None:
    assert page().get(f"/api/transcripts/{transcript_id}/edits").status_code == 404


def test_a_rebuilt_library_finds_the_same_list(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    content[1]["muted"] = True
    client.put(route, json={"content": content})
    library_path().unlink()
    with Library.open() as library:
        rebuilt = library.adopt([seeded["json"]]).transcripts[0]
    assert page().get(f"/api/transcripts/{rebuilt}/edits").json()["content"][1]["muted"] is True
