"""Review mode's backend (#248): review document, answer key, stale edit list (#249).

The recording and transcript are tests/conftest.py's `seeded`: two seconds of
tone ffmpeg makes and two sentences written there, " Hello there." from 0.2 to
0.9 s by SPEAKER_00 and " Fine." from 1.2 to 1.6 s by SPEAKER_01.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import page, tokens, update

from dsj import hatao
from dsj.ui import edits, review
from dsj.ui.edits import edits_path, source_path
from dsj.ui.review import review_path
from dsj.ui.schemas import ReviewDocument


def sha(seeded: dict[str, Any]) -> str:
    return hashlib.sha256(seeded["json"].read_bytes()).hexdigest()


def document(digest: str, *states: str, flags: tuple[list[str], ...] = ([], [])) -> dict[str, Any]:
    spans = [(0.2, 0.9), (1.2, 1.6)]
    return {
        "version": 1,
        "transcript_sha": digest,
        "review_pass": "every",
        "cursor_s": 1.2,
        "started_at": "2026-10-07T10:00:00+00:00",
        "updated_at": "2026-10-07T10:05:00+00:00",
        "segments": [
            {"start": a, "end": b, "state": state, "flags": flag, "speaker": None, "edited": False}
            for (a, b), state, flag in zip(spans, states, flags, strict=False)
        ],
        "corrections": [],
    }


def transcribe_again(seeded: dict[str, Any]) -> None:
    """Write the transcript again at the same path, "there" heard as "world" this time."""
    payload = dict(seeded["payload"])
    payload["sentences"] = [
        {"start": 0.2, "end": 0.9, "speaker": 0, "text": " Hello world.",
         "tokens": tokens((0.2, 0.5, " Hello", 0.99), (0.56, 0.8, " world", 0.9),
                          (0.8, 0.88, ".", 0.97))},
        {"start": 1.2, "end": 1.6, "speaker": 1, "text": " Fine.",
         "tokens": tokens((1.2, 1.5, " Fine", 0.9), (1.5, 1.6, ".", 0.95))},
    ]
    seeded["json"].write_text(json.dumps(payload))


def correct_there(seeded: dict[str, Any]) -> None:
    """Retype " there" as " their" in the transcript's edit list, through the page's route."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = client.get(route).json()["content"]
    next(e for e in content if e.get("text") == " there")["text"] = " their"
    assert client.put(route, json=update(seeded, content)).status_code == 200


def test_a_transcript_with_no_review_says_so_and_names_its_own_sha(
    seeded: dict[str, Any],
) -> None:
    reply = page().get(f"/api/transcripts/{seeded['id']}/review")
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"document": None, "transcript_sha": sha(seeded), "review_sha": None}


def test_a_saved_review_comes_back_and_lives_beside_the_library(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/review"
    saved = client.put(route, json=document(sha(seeded), "checked", "unchecked"))
    assert saved.status_code == 200, saved.text
    assert client.get(route).json()["document"]["segments"][0]["state"] == "checked"
    assert review_path(seeded["json"]).is_file()
    assert sorted(p.name for p in seeded["audio"].parent.iterdir()) == ["talk.json", "talk.wav"]
    # And the library row shows how far it got.
    listed = client.get("/api/recordings").json()[0]["transcripts"][0]
    assert (listed["review_checked"], listed["review_total"]) == (1, 2)


def test_overlapping_segments_are_refused_by_name(seeded: dict[str, Any]) -> None:
    broken = document(sha(seeded), "unchecked", "unchecked")
    broken["segments"][1]["start"] = 0.5
    reply = page().put(f"/api/transcripts/{seeded['id']}/review", json=broken)
    assert reply.status_code == 422
    assert reply.json()["error"] == "InvalidReview"
    assert "segment 1" in reply.json()["message"]
    assert not review_path(seeded["json"]).exists()


def test_a_review_of_a_transcript_not_in_the_library_is_404() -> None:
    reply = page().get("/api/transcripts/99/review")
    assert reply.status_code == 404
    assert reply.json()["error"] == "NoSuchTranscript"


def test_an_answer_key_is_refused_while_sentences_are_unchecked_and_says_how_many(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    client.put(f"{route}/review", json=document(sha(seeded), "checked", "unchecked"))
    reply = client.post(f"/api/transcripts/{seeded['id']}/reference", json={})
    assert reply.status_code == 409
    assert reply.json()["error"] == "ReviewIncomplete"
    assert "1 of 2 sentences are not checked" in reply.json()["message"]
    assert not (seeded["json"].parent / "talk.reference.json").exists()
    partial = client.post(f"{route}/reference", json={"allow_partial": True})
    assert partial.status_code == 200, partial.text
    assert partial.json() == {
        "files": ["talk.reference.json", "talk.reference.txt"], "segments": 2, "unchecked": 1,
    }
    key = json.loads((seeded["json"].parent / "talk.reference.json").read_text())
    assert key["complete"] is False
    text = (seeded["json"].parent / "talk.reference.txt").read_text()
    assert text.endswith("Speaker 2: Fine. [not checked]\n")


def test_an_answer_key_with_no_review_is_refused(seeded: dict[str, Any]) -> None:
    reply = page().post(f"/api/transcripts/{seeded['id']}/reference", json={})
    assert reply.status_code == 409
    assert "no review yet" in reply.json()["message"]


def test_the_answer_key_holds_the_corrected_words_names_and_flags(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    correct_there(seeded)
    client.put(f"{route}/names", json={"names": {"SPEAKER_00": "Ali"}})
    both = document(sha(seeded), "checked", "checked", flags=([], ["overlap"]))
    client.put(f"{route}/review", json=both)
    assert client.post(f"{route}/reference", json={}).status_code == 200
    key = json.loads((seeded["json"].parent / "talk.reference.json").read_text())
    assert key["format"] == "dsj-reference"
    assert key["transcript"] == "talk.json"
    assert key["model"] == "mlx-community/parakeet-tdt-0.6b-v3"
    assert key["complete"] is True
    assert [(s["speaker"], s["text"], s["flags"]) for s in key["segments"]] == [
        ("Ali", "Hello their.", []),
        ("Speaker 2", "Fine.", ["overlap"]),
    ]
    text = (seeded["json"].parent / "talk.reference.txt").read_text()
    assert text == "[0:00] Ali: Hello their.\n[0:01] Speaker 2: Fine. (overlapping talk)\n"


def test_transcribed_again_the_old_edit_list_is_moved_aside_not_applied(
    seeded: dict[str, Any],
) -> None:
    """Review Focus 4: a run from the app with the same settings writes the same JSON path."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    correct_there(seeded)
    old = sha(seeded)
    client.put(f"{route}/review", json=document(old, "checked", "checked"))

    transcribe_again(seeded)

    edits = client.get(f"{route}/edits").json()
    words = "".join(e["text"] for e in edits["content"] if e["kind"] == "item")
    assert "world" in words and "their" not in words
    assert edits["replaced"] is not None and "made again" in edits["replaced"]
    listed = edits_path(seeded["json"])
    aside = listed.with_name(f"{listed.stem}.{old[:12]}.json")
    assert aside.is_file()
    assert "their" in aside.read_text()
    # The review is kept; the page sees its sha no longer matches and re-checks by span.
    review = client.get(f"{route}/review").json()
    assert review["document"]["transcript_sha"] == old
    assert review["transcript_sha"] == sha(seeded) != old
    # Opened again, the list is the new transcript's: nothing more is moved, nothing replaced.
    again = client.get(f"{route}/edits").json()
    assert again["replaced"] is None
    assert sorted(p.name for p in listed.parent.iterdir() if p.name.startswith(listed.stem)) == [
        aside.name, f"{aside.stem}.source.json"
    ]


def test_transcribed_again_the_speakers_keep_their_names(seeded: dict[str, Any]) -> None:
    """Names belong to the voices, not the words: they come across to the fresh list."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    correct_there(seeded)
    client.put(f"{route}/names", json={"names": {"SPEAKER_00": "Ali"}})

    transcribe_again(seeded)

    edits = client.get(f"{route}/edits").json()
    assert edits["names"] == {"SPEAKER_00": "Ali"}
    assert edits["replaced"] is not None
    # Kept in the fresh list itself, so the next open still has them and moves nothing.
    assert hatao.load(edits_path(seeded["json"])).names == {"SPEAKER_00": "Ali"}
    again = client.get(f"{route}/edits").json()
    assert (again["names"], again["replaced"]) == ({"SPEAKER_00": "Ali"}, None)
    assert "world" in "".join(e["text"] for e in again["content"] if e["kind"] == "item")


def test_a_list_saved_before_its_source_was_kept_is_trusted_and_gains_one(
    seeded: dict[str, Any],
) -> None:
    """A list from before #249 has no note of its source: it opens as it always did."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    correct_there(seeded)
    note = source_path(edits_path(seeded["json"]))
    assert json.loads(note.read_text()) == {"transcript_sha": sha(seeded)}
    note.unlink()
    opened = client.get(route).json()
    assert opened["replaced"] is None
    assert " their" in [e.get("text") for e in opened["content"]]
    client.put(route, json=update(seeded, opened["content"]))
    assert note.is_file()


# -- fix round 1: what a re-transcription must never do ---------------------------------


def test_a_page_loaded_before_the_transcript_was_made_again_cannot_save_over_it(
    seeded: dict[str, Any],
) -> None:
    """The reviewer's probe, inverted: the old words are refused, kept aside, and not trusted."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    correct_there(seeded)
    loaded = client.get(route).json()
    old = loaded["transcript_sha"]
    assert old == sha(seeded)

    transcribe_again(seeded)

    reply = client.put(route, json={"content": loaded["content"], "transcript_sha": old})
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"] == "TranscriptChanged"
    assert "Reload the page" in reply.json()["message"]
    # The new transcript's words open; the old ones were not saved over them.
    opened = client.get(route).json()
    words = "".join(e["text"] for e in opened["content"] if e["kind"] == "item")
    assert "world" in words and "their" not in words
    assert opened["transcript_sha"] == sha(seeded)
    # Nothing typed is lost: the saved list and the page's own copy are both kept aside.
    listed = edits_path(seeded["json"])
    kept = [listed.with_name(f"{listed.stem}.{old[:12]}{n}.json") for n in ("", "-2")]
    assert all("their" in path.read_text() for path in kept)
    assert reply.json()["message"].count(kept[1].name) == 1


def test_an_answer_key_of_a_review_checked_before_the_transcript_was_made_again_is_refused(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    correct_there(seeded)
    client.put(f"{route}/review", json=document(sha(seeded), "checked", "checked"))
    transcribe_again(seeded)
    for asked in ({}, {"allow_partial": True}):
        reply = client.post(f"{route}/reference", json=asked)
        assert reply.status_code == 409, reply.text
        assert reply.json()["error"] == "TranscriptChanged"
        assert "Open Review" in reply.json()["message"]
    assert not (seeded["json"].parent / "talk.reference.json").exists()
    # Refused before the list was opened: nothing was put aside behind the page's back.
    listed = edits_path(seeded["json"])
    assert sorted(p.name for p in listed.parent.iterdir()) == [
        listed.name,
        source_path(listed).name,
    ]


def test_a_word_starting_before_its_sentence_span_is_still_in_the_answer_key(
    seeded: dict[str, Any],
) -> None:
    """" Hello" starts at 0.2 s; the sentence a person split starts at 0.3 s."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    late = document(sha(seeded), "checked", "checked")
    late["segments"][0]["start"] = 0.3
    client.put(f"{route}/review", json=late)
    assert client.post(f"{route}/reference", json={}).status_code == 200
    key = json.loads((seeded["json"].parent / "talk.reference.json").read_text())
    assert [s["text"] for s in key["segments"]] == ["Hello there.", "Fine."]
    assert key["complete"] is True


def test_a_list_put_aside_by_an_export_is_still_told_to_the_page_once(
    seeded: dict[str, Any],
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    correct_there(seeded)
    transcribe_again(seeded)
    exported = client.get(f"{route}/export/txt")
    assert exported.status_code == 200
    assert "world" in exported.text
    told = client.get(f"{route}/edits").json()["replaced"]
    assert told is not None and "made again" in told
    assert client.get(f"{route}/edits").json()["replaced"] is None


def test_a_note_that_does_not_read_leaves_the_list_trusted(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/edits"
    correct_there(seeded)
    note = source_path(edits_path(seeded["json"]))
    for broken in ("{not json", '{"other": 1}', "[]"):
        note.write_text(broken)
        opened = client.get(route)
        assert opened.status_code == 200, opened.text
        assert opened.json()["replaced"] is None
        assert " their" in [e.get("text") for e in opened.json()["content"]]


def test_a_partial_answer_key_keeps_the_complete_one_before_it(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    folder = seeded["json"].parent
    client.put(f"{route}/review", json=document(sha(seeded), "checked", "checked"))
    assert client.post(f"{route}/reference", json={}).status_code == 200
    client.put(f"{route}/review", json=document(sha(seeded), "checked", "unchecked"))
    assert client.post(f"{route}/reference", json={"allow_partial": True}).status_code == 200
    assert json.loads((folder / "talk.reference.json").read_text())["complete"] is False
    assert json.loads((folder / "talk.reference-2.json").read_text())["complete"] is True
    assert "[not checked]" not in (folder / "talk.reference-2.txt").read_text()
    # A second partial replaces the first partial; the complete key stays where it was.
    assert client.post(f"{route}/reference", json={"allow_partial": True}).status_code == 200
    assert not (folder / "talk.reference-3.json").exists()


def test_the_transcript_is_read_without_the_lock_and_saves_still_take_turns(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Drive download must not hold every request up; two saves still never interleave."""
    reads_free: list[bool] = []
    read = edits._read_stamped  # pyright: ignore[reportPrivateUsage]

    def watched(transcript_id: int) -> tuple[dict[str, Any], str, tuple[int, int]]:
        # Another thread can take the lock while the transcript is being read.
        got: list[bool] = []

        def other() -> None:
            got.append(edits.WRITING.acquire(timeout=0))
            if got[0]:
                edits.WRITING.release()

        thread = threading.Thread(target=other)
        thread.start()
        thread.join()
        reads_free.append(got[0])
        return read(transcript_id)

    active, most = [0], [0]
    save = hatao.save

    def slow(doc: hatao.Document, path: Path) -> None:
        active[0] += 1
        most[0] = max(most[0], active[0])
        time.sleep(0.05)
        save(doc, path)
        active[0] -= 1

    monkeypatch.setattr(edits, "_read_stamped", watched)
    monkeypatch.setattr(hatao, "save", slow)
    opened = edits.open_edits(seeded["id"])
    content = tuple(
        replace(e, text=" their") if isinstance(e, hatao.Item) and e.text == " there" else e
        for e in opened.doc.content
    )
    workers = [
        threading.Thread(
            target=edits.save_edits, args=(seeded["id"], content, opened.transcript_sha)
        ),
        threading.Thread(target=edits.save_names, args=(seeded["id"], {"SPEAKER_00": "Ali"})),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert most[0] == 1
    assert reads_free and all(reads_free)
    doc = hatao.load(edits_path(seeded["json"]))
    assert doc.names == {"SPEAKER_00": "Ali"}
    assert " their" in [e.text for e in doc.content if isinstance(e, hatao.Item)]


def test_two_answer_keys_written_at_once_never_fail_or_mismatch(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A double click, on the server's thread pool: every pair on disk is one write's pair.

    Each rename sleeps a millisecond, which lets the other thread run there:
    without it the GIL hands the threads turns so rarely inside the write that
    a race shows about one run in five (observed, with the key lock removed).
    """
    rename = os.replace

    def slow(src: Any, dst: Any) -> None:
        time.sleep(0.001)
        rename(src, dst)

    monkeypatch.setattr(os, "replace", slow)
    complete = ReviewDocument.model_validate(document(sha(seeded), "checked", "checked"))
    partial = ReviewDocument.model_validate(document(sha(seeded), "checked", "unchecked"))
    failures: list[BaseException] = []

    def writer(doc: ReviewDocument) -> None:
        try:
            for _ in range(40):
                review.save_review(seeded["id"], doc)
                review.reference(seeded["id"], allow_partial=True)
        except BaseException as exc:  # collected, then asserted empty
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(d,)) for d in (complete, partial)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    folder = seeded["json"].parent
    keys = sorted(folder.glob("talk.reference*.json"))
    assert keys
    for key in keys:
        whole = json.loads(key.read_text())["complete"]
        text = key.with_suffix(".txt").read_text()
        assert whole is ("[not checked]" not in text), key.name
    assert not list(folder.glob(".*.tmp"))


def test_a_sha_that_is_not_one_is_refused_as_a_bad_request(seeded: dict[str, Any]) -> None:
    """It names a file the refused edits are kept in: a "/" in it must never reach the disk."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    for bad in ("../../x", sha(seeded).upper(), sha(seeded)[:63], ""):
        edited = client.put(f"{route}/edits", json={"content": content, "transcript_sha": bad})
        assert edited.status_code == 422, (bad, edited.text)
        broken = {**document(sha(seeded)), "transcript_sha": bad}
        reviewed = client.put(f"{route}/review", json=broken)
        assert reviewed.status_code == 422, (bad, reviewed.text)
    listed = edits_path(seeded["json"])
    assert not listed.parent.exists() or not any(listed.parent.iterdir())


def test_a_transcript_written_again_while_it_was_read_is_read_again(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read happens before the lock: a re-make landing in between must not be missed."""
    read = edits._read_stamped  # pyright: ignore[reportPrivateUsage]
    calls: list[int] = []

    def remade_after_the_first(transcript_id: int) -> tuple[dict[str, Any], str, tuple[int, int]]:
        got = read(transcript_id)
        calls.append(transcript_id)
        if len(calls) == 1:
            transcribe_again(seeded)
            # A different size as well as a later time, so the stamp differs on any file system.
            payload = json.loads(seeded["json"].read_text())
            seeded["json"].write_text(json.dumps({**payload, "remade": True}))
        return got

    correct_there(seeded)
    monkeypatch.setattr(edits, "_read_stamped", remade_after_the_first)
    opened = edits.open_edits(seeded["id"])
    assert len(calls) == 2
    assert opened.transcript_sha == sha(seeded)
    assert " world" in [e.text for e in opened.doc.content if isinstance(e, hatao.Item)]
    assert opened.replaced is not None
