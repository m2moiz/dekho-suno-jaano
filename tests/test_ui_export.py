"""The edited transcript exported from the reader's menu (#244).

The same recording and transcript as tests/test_ui_edits.py (the `seeded` fixture in
tests/conftest.py): two seconds of tone ffmpeg makes and two sentences written here,
never a real recording.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from conftest import page

from dsj.ui.edits import display_name

# WebVTT's inline word times, which likho writes ahead of each later word.
_TIME_TAG = re.compile(r"<\d\d:\d\d:\d\d\.\d{3}>")


def test_an_export_carries_the_corrections_and_the_names(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    there = next(i for i, e in enumerate(content) if e.get("text") == " there")
    content[there]["text"] = " their"
    client.put(f"{route}/edits", json={"content": content})
    client.put(f"{route}/names", json={"names": {"SPEAKER_00": "Ali"}})
    reply = client.get(f"{route}/export/srt")
    assert reply.status_code == 200, reply.text
    name = f'attachment; filename="transcript-{seeded["id"]}.srt"'
    assert reply.headers["content-disposition"] == name
    assert "Hello their." in reply.text
    assert "Ali" in reply.text
    # The second speaker has no name, so they are the diarizer's second speaker.
    assert "Speaker 2" in reply.text


@pytest.mark.parametrize("fmt", ["vtt", "txt"])
def test_every_likho_format_exports(seeded: dict[str, Any], fmt: str) -> None:
    reply = page().get(f"/api/transcripts/{seeded['id']}/export/{fmt}")
    assert reply.status_code == 200
    # WebVTT stamps each later word with its start, between "Fine" and ".".
    assert "Fine." in _TIME_TAG.sub("", reply.text)


def test_a_format_likho_does_not_write_is_404(seeded: dict[str, Any]) -> None:
    reply = page().get(f"/api/transcripts/{seeded['id']}/export/docx")
    assert reply.status_code == 404
    assert "srt" in reply.json()["detail"]


def test_nothing_is_written_beside_the_recording(seeded: dict[str, Any]) -> None:
    page().get(f"/api/transcripts/{seeded['id']}/export/srt")
    assert sorted(p.name for p in seeded["audio"].parent.iterdir()) == ["talk.json", "talk.wav"]


def test_a_speaker_added_in_review_is_numbered_after_the_transcripts_own() -> None:
    labels = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
    assert display_name("SPEAKER_02", labels, {}) == "Speaker 3"
    assert display_name("SPEAKER_02", labels, {"SPEAKER_02": "Sana"}) == "Sana"
    # A label that is not a diarizer's is already a name.
    assert display_name("Host", ["Host"], {}) == "Host"
    assert display_name(None, labels, {}) is None
