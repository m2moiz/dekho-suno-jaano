"""A transcript's edit list through the page's routes (#63, #66).

Each test's library is its own (conftest points DSJ_LIBRARY into a temporary
directory), its recording two seconds of tone made by ffmpeg, its transcript
written the way `dsj suno` writes one, every token with `t`, `e` and `c`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import page, update

from dsj import hatao
from dsj.ui.edits import edits_path
from dsj.ui.store import Library, library_path


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
    saved = client.put(route, json=update(seeded, content))
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
    client.put(route, json=update(seeded, client.get(route).json()["content"]))
    path = edits_path(seeded["json"])
    assert path.parent == library_path().parent / "edits"
    assert path.is_file()
    assert sorted(p.name for p in seeded["audio"].parent.iterdir()) == ["talk.json", "talk.wav"]


def test_a_broken_list_is_refused_whole_naming_the_entry(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    content[2]["length"] = -1.0
    reply = client.put(route, json=update(seeded, content))
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
    reply = client.put(route, json=update(seeded, content))
    assert reply.status_code == 422
    assert "no such source" in reply.json()["message"]


def test_a_word_edited_by_hand_reads_as_sure(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    there = next(i for i, e in enumerate(content) if e.get("text") == " there")
    content[there]["text"] = " their"
    body = client.put(route, json=update(seeded, content)).json()
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
    client.put(route, json=update(seeded, content))
    library_path().unlink()
    with Library.open() as library:
        rebuilt = library.adopt([seeded["json"]]).transcripts[0]
    assert page().get(f"/api/transcripts/{rebuilt}/edits").json()["content"][1]["muted"] is True


# -- the words to bleep (#84) ---------------------------------------------------


def user_list(*names: str) -> None:
    """The user's own list (conftest's DSJ_WORDS) holding each of `names`, Roman spelling."""
    hatao.user_words_path().write_text(
        "".join(f'[[entry]]\nname = "{n}"\nroman = ["{n}"]\n' for n in names)
    )


def test_matches_come_from_dsj_hatao_find_with_their_entry_and_times(
    seeded: dict[str, Any],
) -> None:
    user_list("there")
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    body = client.post(f"{route}/matches", json={"content": content}).json()
    assert [(m["word"], m["entry"], m["start_s"], m["end_s"]) for m in body["matches"]] == [
        ("there.", "user:there", 0.56, 0.88)
    ]
    match = body["matches"][0]
    assert [e.get("text") for e in content[match["start"]:match["stop"]]] == [" there", "."]
    assert body["words_searched"] == 3
    assert body["lists"] == [*hatao.SHIPPED_LISTS, "user"]
    assert "unmeasured" in body["recall"]


def test_a_word_retyped_on_the_page_is_matched_as_retyped(seeded: dict[str, Any]) -> None:
    user_list("fine")
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    fine = next(i for i, e in enumerate(content) if e.get("text") == " Fine")
    hello = next(i for i, e in enumerate(content) if e.get("text") == " Hello")
    content[hello]["text"] = " Fine"
    body = client.post(f"{route}/matches", json={"content": content}).json()
    assert [m["start"] for m in body["matches"]] == [hello, fine]


def test_no_match_is_an_empty_list_with_the_count_searched(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    body = client.post(f"{route}/matches", json={"content": content}).json()
    assert body["matches"] == []
    assert body["words_searched"] == 3


def test_a_word_added_from_the_app_goes_in_the_user_file_and_matches_next_pass(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    reply = client.post("/api/words", json={"word": " Hello "})
    assert reply.json() == {"entry": "user:Hello", "added": True}
    # The file dsj hatao reads, in #64's own format.
    lists = hatao.load_words(hatao.word_lists())
    assert lists.spellings["hello"] == "user:Hello"
    assert 'roman = ["Hello"]' in hatao.user_words_path().read_text()
    content = client.get(f"{route}/edits").json()["content"]
    matched = client.post(f"{route}/matches", json={"content": content}).json()["matches"]
    assert [m["entry"] for m in matched] == ["user:Hello"]
    # Asked again, it is not written twice.
    assert client.post("/api/words", json={"word": "hello"}).json() == {
        "entry": "user:Hello", "added": False,
    }
    assert hatao.user_words_path().read_text().count("[[entry]]") == 1


def test_a_word_in_its_own_script_is_filed_as_script_and_punctuation_is_refused() -> None:
    client = page()
    assert client.post("/api/words", json={"word": "یار"}).json()["added"] is True
    assert 'script = ["یار"]' in hatao.user_words_path().read_text()
    refused = client.post("/api/words", json={"word": "..."})
    assert refused.status_code == 422
    assert refused.json()["error"] == "WordListError"


def test_a_user_list_already_broken_is_named_and_left_as_it_was() -> None:
    hatao.user_words_path().write_text("[[entry]]\nname = 3\n")
    reply = page().post("/api/words", json={"word": "bravo"})
    assert reply.status_code == 422
    assert hatao.user_words_path().read_text() == "[[entry]]\nname = 3\n"


def test_the_spans_a_render_would_mute_come_with_every_list(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    opened = client.get(route).json()
    assert opened["spans"] == []
    content = opened["content"]
    there = next(i for i, e in enumerate(content) if e.get("text") == " there")
    content[there]["muted"] = True
    saved = client.put(route, json=update(seeded, content)).json()
    # hatao.spans_to_mute's own answer: the word, padded PAD_S each side.
    assert saved["spans"] == [[0.46, 0.9]]
    assert saved["unrenderable"] is None


def test_a_list_a_render_would_refuse_says_why(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    content[2], content[3] = content[3], content[2]
    saved = client.put(route, json=update(seeded, content)).json()
    assert saved["spans"] is None
    assert "deleted or moved" in saved["unrenderable"]


# -- corrected by hand (#83) ------------------------------------------------------


def test_saving_an_edit_marks_the_transcript_edited_in_the_library(
    seeded: dict[str, Any],
) -> None:
    client = page()
    listed = client.get("/api/recordings").json()[0]["transcripts"][0]
    assert listed["last_edited_at"] is None
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    content[2]["text"] = " Hullo"
    saved = client.put(route, json=update(seeded, content)).json()
    listed = client.get("/api/recordings").json()[0]["transcripts"][0]
    assert listed["last_edited_at"] == saved["edited_at"]
    # The transcript's own file is never written.
    assert json.loads(seeded["json"].read_text()) == seeded["payload"]


def test_a_version_2_library_gains_last_edited_at_and_keeps_its_rows(
    seeded: dict[str, Any],
) -> None:
    import sqlite3

    with sqlite3.connect(library_path()) as con:
        con.execute("ALTER TABLE transcripts DROP COLUMN last_edited_at")
        con.execute("ALTER TABLE recordings DROP COLUMN title")
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 2")
    with Library.open() as library:
        found = library.transcript(seeded["id"])
        assert found is not None
        assert found.last_edited_at is None
        library.mark_edited(seeded["id"], "2026-10-03T00:00:00+00:00")
        again = library.transcript(seeded["id"])
    assert again is not None
    assert again.last_edited_at == "2026-10-03T00:00:00+00:00"
    with sqlite3.connect(library_path()) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5


# -- speaker names (#243) ---------------------------------------------------------


def test_a_name_given_to_a_speaker_is_kept_and_sent_back(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    assert client.get(f"{route}/edits").json()["names"] == {}
    reply = client.put(f"{route}/names", json={"names": {"SPEAKER_00": "  Ali  "}})
    assert reply.status_code == 200, reply.text
    assert reply.json()["names"] == {"SPEAKER_00": "Ali"}
    assert page().get(f"{route}/edits").json()["names"] == {"SPEAKER_00": "Ali"}
    # In the file `dsj hatao` reads, beside the library.
    assert hatao.load(edits_path(seeded["json"])).names == {"SPEAKER_00": "Ali"}


def test_saving_the_words_keeps_the_names(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    client.put(f"{route}/names", json={"names": {"SPEAKER_01": "Sara"}})
    content = client.get(f"{route}/edits").json()["content"]
    content[2]["muted"] = True
    saved = client.put(f"{route}/edits", json=update(seeded, content)).json()
    assert saved["names"] == {"SPEAKER_01": "Sara"}


def test_a_blank_name_gives_the_speaker_its_own_label_back(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/names"
    client.put(route, json={"names": {"SPEAKER_00": "Ali", "SPEAKER_01": "Sara"}})
    cleared = client.put(route, json={"names": {"SPEAKER_00": "", "SPEAKER_01": "Sara"}}).json()
    assert cleared["names"] == {"SPEAKER_01": "Sara"}
