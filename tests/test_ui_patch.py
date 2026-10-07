"""One change saved, not the whole list (#251): the PATCH routes of the edit list and the review.

A 2.5 h transcript's edit list is about 3.5 MB, and every correction in Review
uploaded all of it, and downloaded it again in the answer (#251, measured). A
splice says only what changed: `delete` entries at `start` replaced by
`insert`, against the list the page last saw, named by its sha. Two patches
made against the same list never both apply.

The recording and transcript are tests/conftest.py's `seeded`: " Hello there."
from 0.2 to 0.9 s by SPEAKER_00 and " Fine." from 1.2 to 1.6 s by SPEAKER_01.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

import pytest
from conftest import page

from dsj import hatao
from dsj.ui import edits
from dsj.ui.edits import edits_path
from dsj.ui.review import review_path


def sha(seeded: dict[str, Any]) -> str:
    return hashlib.sha256(seeded["json"].read_bytes()).hexdigest()


def opened(seeded: dict[str, Any]) -> dict[str, Any]:
    reply = page().get(f"/api/transcripts/{seeded['id']}/edits")
    assert reply.status_code == 200, reply.text
    return reply.json()


def retype(content: list[dict[str, Any]], word: str, to: str) -> tuple[int, dict[str, Any]]:
    """Where `word` is in the list, and its entry retyped as `to`, as a correction leaves it."""
    at = next(i for i, e in enumerate(content) if e.get("text") == word)
    return at, {**content[at], "text": to}


def splice(seeded: dict[str, Any], body: dict[str, Any], start: int, delete: int,
           insert: list[dict[str, Any]]) -> dict[str, Any]:
    return {"transcript_sha": sha(seeded), "list_sha": body["list_sha"], "start": start,
            "delete": delete, "insert": insert}


# -- the edit list ---------------------------------------------------------------------


def test_a_list_names_its_own_sha_and_an_untouched_one_is_the_transcripts_list(
    seeded: dict[str, Any],
) -> None:
    body = opened(seeded)
    built = edits.open_edits(seeded["id"]).doc
    assert body["list_sha"] == edits.list_sha(built)
    # The same list read again is the same sha: nothing in it is the time of the read.
    assert opened(seeded)["list_sha"] == body["list_sha"]


def test_a_patch_replaces_only_its_entries_and_answers_small(seeded: dict[str, Any]) -> None:
    body = opened(seeded)
    at, their = retype(body["content"], " there", " their")
    route = f"/api/transcripts/{seeded['id']}/edits"
    reply = page().patch(route, json=splice(seeded, body, at, 1, [their]))
    assert reply.status_code == 200, reply.text
    answer = reply.json()
    # Never the content: on a 2.5 h transcript that was the 3.5 MB download (#251).
    assert sorted(answer) == ["edited_at", "list_sha", "spans", "unrenderable"]
    assert len(reply.content) < 300
    again = opened(seeded)
    expected = [{**their, "confidence": 1.0} if i == at else e
                for i, e in enumerate(body["content"])]
    assert again["content"] == expected
    assert again["list_sha"] == answer["list_sha"] != body["list_sha"]
    assert again["edited_at"] == answer["edited_at"]
    # Written as a PUT writes it: dsj hatao's own file, beside the library.
    assert " their" in [e.text for e in hatao.load(edits_path(seeded["json"])).content
                        if isinstance(e, hatao.Item)]


def test_a_patch_can_insert_at_the_start_and_delete_at_the_end(seeded: dict[str, Any]) -> None:
    body = opened(seeded)
    route = f"/api/transcripts/{seeded['id']}/edits"
    content = body["content"]
    opening = {"kind": "paragraph", "speaker": "SPEAKER_01", "language": None}
    first = page().patch(route, json=splice(seeded, body, 0, 0, [opening]))
    assert first.status_code == 200, first.text
    last = page().patch(
        route,
        json={**splice(seeded, body, len(content), 1, []), "list_sha": first.json()["list_sha"]},
    )
    assert last.status_code == 200, last.text
    def plain(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in e.items() if k != "confidence"} for e in entries]

    assert plain(opened(seeded)["content"]) == [opening, *plain(content[:-1])]


def test_a_patch_against_a_list_changed_elsewhere_is_refused_and_writes_nothing(
    seeded: dict[str, Any],
) -> None:
    body = opened(seeded)
    route = f"/api/transcripts/{seeded['id']}/edits"
    at, their = retype(body["content"], " there", " their")
    assert page().patch(route, json=splice(seeded, body, at, 1, [their])).status_code == 200
    saved = edits_path(seeded["json"]).read_bytes()
    # Another tab, still holding the list as it was before.
    _, other = retype(body["content"], " there", " where")
    reply = page().patch(route, json=splice(seeded, body, at, 1, [other]))
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"] == "ListChanged"
    assert "another tab" in reply.json()["message"]
    assert edits_path(seeded["json"]).read_bytes() == saved


def test_a_patch_against_a_transcript_made_again_is_the_existing_refusal(
    seeded: dict[str, Any],
) -> None:
    body = opened(seeded)
    route = f"/api/transcripts/{seeded['id']}/edits"
    at, their = retype(body["content"], " there", " their")
    patch = splice(seeded, body, at, 1, [their])
    payload = dict(seeded["payload"])
    payload["text"] = " Hello world. Fine."
    seeded["json"].write_text(json.dumps(payload))
    reply = page().patch(route, json=patch)
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"] == "TranscriptChanged"
    assert "Reload the page" in reply.json()["message"]
    assert not edits_path(seeded["json"]).exists()


@pytest.mark.parametrize(("start", "delete"), [(-1, 0), (99, 0), (3, 99), (0, -1)])
def test_a_patch_outside_the_list_is_refused_naming_the_numbers(
    seeded: dict[str, Any], start: int, delete: int
) -> None:
    body = opened(seeded)
    reply = page().patch(
        f"/api/transcripts/{seeded['id']}/edits", json=splice(seeded, body, start, delete, [])
    )
    assert reply.status_code == 422, reply.text
    message = reply.json()["message"]
    assert f"start {start}" in message and f"delete {delete}" in message
    assert str(len(body["content"])) in message
    assert not edits_path(seeded["json"]).exists()


def test_a_patch_that_breaks_the_list_is_refused_naming_the_entry(seeded: dict[str, Any]) -> None:
    body = opened(seeded)
    # The opening paragraph taken away: the list would open with an item.
    reply = page().patch(
        f"/api/transcripts/{seeded['id']}/edits", json=splice(seeded, body, 0, 1, [])
    )
    assert reply.status_code == 422, reply.text
    assert reply.json()["error"] == "InvalidDocument"
    assert "entry 0" in reply.json()["message"]
    assert not edits_path(seeded["json"]).exists()


def slow_saves(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> None:
    """Make `module.name` sleep before it writes, so two requests overlap if nothing stops them."""
    write = getattr(module, name)

    def slow(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.05)
        return write(*args, **kwargs)

    monkeypatch.setattr(module, name, slow)


def both_at_once(route: str, bodies: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """PATCH each body to `route` from its own client and thread, released together.

    Each answer as its status and its JSON, in the order of `bodies`.
    """
    gate = threading.Barrier(len(bodies))
    replies: dict[int, tuple[int, dict[str, Any]]] = {}

    def one(k: int) -> None:
        client = page()
        gate.wait()
        reply = client.patch(route, json=bodies[k])
        replies[k] = (reply.status_code, reply.json())

    threads = [threading.Thread(target=one, args=(k,)) for k in range(len(bodies))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [replies[k] for k in range(len(bodies))]


def test_two_patches_against_the_same_list_never_both_apply(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    body = opened(seeded)
    route = f"/api/transcripts/{seeded['id']}/edits"
    slow_saves(monkeypatch, hatao, "save")
    at, their = retype(body["content"], " there", " their")
    _, where = retype(body["content"], " there", " where")
    fine = next(i for i, e in enumerate(body["content"]) if e.get("text") == " Fine")
    bodies = [splice(seeded, body, at, 1, [their]),
              splice(seeded, body, fine, 1, [{**body["content"][fine], "muted": True}]),
              splice(seeded, body, at, 1, [where])]
    replies = both_at_once(route, bodies)
    assert sorted(code for code, _ in replies) == [200, 409, 409], replies
    assert all(body["error"] == "ListChanged" for code, body in replies if code == 409)
    won = next(k for k, (code, _) in enumerate(replies) if code == 200)
    now = opened(seeded)
    assert now["list_sha"] == replies[won][1]["list_sha"]
    words = [e["text"] for e in now["content"] if e["kind"] == "item"]
    muted = [e["muted"] for e in now["content"] if e["kind"] == "item"]
    # Exactly the winner's change, none of the others'.
    assert (" their" in words, " where" in words, any(muted)) == (won == 0, won == 2, won == 1)


def test_a_rename_changes_the_list_sha_and_its_answer_names_the_new_one(
    seeded: dict[str, Any],
) -> None:
    body = opened(seeded)
    reply = page().put(f"/api/transcripts/{seeded['id']}/names",
                       json={"names": {"SPEAKER_00": "Ali"}})
    assert reply.status_code == 200, reply.text
    renamed = reply.json()["list_sha"]
    assert renamed != body["list_sha"]
    assert opened(seeded)["list_sha"] == renamed
    # A patch made before the rename is a patch against another list.
    at, their = retype(body["content"], " there", " their")
    route = f"/api/transcripts/{seeded['id']}/edits"
    assert page().patch(route, json=splice(seeded, body, at, 1, [their])).status_code == 409
    after = page().patch(route, json={**splice(seeded, body, at, 1, [their]), "list_sha": renamed})
    assert after.status_code == 200, after.text
    assert hatao.load(edits_path(seeded["json"])).names == {"SPEAKER_00": "Ali"}


# -- the review --------------------------------------------------------------------------


def document(digest: str) -> dict[str, Any]:
    return {
        "version": 1,
        "transcript_sha": digest,
        "review_pass": "every",
        "cursor_s": 0.2,
        "started_at": "2026-10-07T10:00:00+00:00",
        "updated_at": "2026-10-07T10:05:00+00:00",
        "segments": [
            {"start": a, "end": b, "state": "unchecked", "flags": [], "speaker": None,
             "edited": False}
            for a, b in [(0.2, 0.9), (1.2, 1.6)]
        ],
        "corrections": [],
    }


def created(seeded: dict[str, Any]) -> dict[str, Any]:
    """Save a review whole, as the page does once, and answer its sha."""
    route = f"/api/transcripts/{seeded['id']}/review"
    reply = page().put(route, json=document(sha(seeded)))
    assert reply.status_code == 200, reply.text
    return reply.json()


def review_patch(seeded: dict[str, Any], review_sha: str | None, **fields: Any) -> dict[str, Any]:
    segment = document(sha(seeded))["segments"][0]
    return {
        "transcript_sha": sha(seeded),
        "review_sha": review_sha,
        "start": 0,
        "delete": 1,
        "insert": [{**segment, "state": "checked", "edited": True}],
        "corrections": [{"at": "2026-10-07T10:06:00+00:00", "start": 0.2, "end": 0.9,
                         "before": "Hello there.", "after": "Hello their."}],
        "review_pass": "likely",
        "cursor_s": 1.2,
        **fields,
    }


def test_a_review_names_its_sha_on_read_and_on_save(seeded: dict[str, Any]) -> None:
    route = f"/api/transcripts/{seeded['id']}/review"
    assert page().get(route).json()["review_sha"] is None
    saved = created(seeded)
    assert sorted(saved) == ["review_sha", "updated_at"]
    assert page().get(route).json()["review_sha"] == saved["review_sha"]


def test_a_review_patch_splices_appends_and_answers_small(seeded: dict[str, Any]) -> None:
    route = f"/api/transcripts/{seeded['id']}/review"
    saved = created(seeded)
    reply = page().patch(route, json=review_patch(seeded, saved["review_sha"]))
    assert reply.status_code == 200, reply.text
    assert sorted(reply.json()) == ["review_sha", "updated_at"]
    assert len(reply.content) < 200
    read = page().get(route).json()
    assert read["review_sha"] == reply.json()["review_sha"] != saved["review_sha"]
    doc = read["document"]
    assert [s["state"] for s in doc["segments"]] == ["checked", "unchecked"]
    assert doc["segments"][0]["edited"] is True
    assert [c["after"] for c in doc["corrections"]] == ["Hello their."]
    assert (doc["review_pass"], doc["cursor_s"]) == ("likely", 1.2)
    assert doc["started_at"] == "2026-10-07T10:00:00+00:00"
    assert doc["updated_at"] == reply.json()["updated_at"]
    # A second patch appends its corrections after the first's.
    more = review_patch(seeded, reply.json()["review_sha"], start=1, delete=0, insert=[])
    assert page().patch(route, json=more).status_code == 200
    assert len(page().get(route).json()["document"]["corrections"]) == 2


def test_a_review_patch_against_another_review_is_refused(seeded: dict[str, Any]) -> None:
    route = f"/api/transcripts/{seeded['id']}/review"
    # None saved yet: there is nothing for a patch to be against.
    none = page().patch(route, json=review_patch(seeded, "0" * 64))
    assert none.status_code == 409, none.text
    assert none.json()["error"] == "ReviewChanged"
    saved = created(seeded)
    assert page().patch(route, json=review_patch(seeded, saved["review_sha"])).status_code == 200
    kept = review_path(seeded["json"]).read_bytes()
    stale = page().patch(route, json=review_patch(seeded, saved["review_sha"], cursor_s=0.2))
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "ReviewChanged"
    assert "another tab" in stale.json()["message"]
    assert review_path(seeded["json"]).read_bytes() == kept


def test_a_review_patch_against_a_transcript_made_again_is_refused(seeded: dict[str, Any]) -> None:
    route = f"/api/transcripts/{seeded['id']}/review"
    saved = created(seeded)
    patch = review_patch(seeded, saved["review_sha"])
    kept = review_path(seeded["json"]).read_bytes()
    payload = dict(seeded["payload"])
    payload["text"] = " Hello world. Fine."
    seeded["json"].write_text(json.dumps(payload))
    reply = page().patch(route, json=patch)
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"] == "TranscriptChanged"
    assert review_path(seeded["json"]).read_bytes() == kept


def test_a_review_patch_that_breaks_the_review_is_refused_by_name(seeded: dict[str, Any]) -> None:
    route = f"/api/transcripts/{seeded['id']}/review"
    saved = created(seeded)
    kept = review_path(seeded["json"]).read_bytes()
    out = page().patch(route, json=review_patch(seeded, saved["review_sha"], start=3))
    assert out.status_code == 422, out.text
    assert "start 3" in out.json()["message"] and "of 2" in out.json()["message"]
    overlap = review_patch(seeded, saved["review_sha"])
    overlap["insert"][0]["end"] = 1.4
    broken = page().patch(route, json=overlap)
    assert broken.status_code == 422, broken.text
    assert broken.json()["error"] == "InvalidReview"
    assert "segment 1" in broken.json()["message"]
    assert review_path(seeded["json"]).read_bytes() == kept


def test_two_review_patches_against_the_same_review_never_both_apply(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from dsj.ui import review

    route = f"/api/transcripts/{seeded['id']}/review"
    saved = created(seeded)
    slow_saves(monkeypatch, review, "atomic_write_text")
    bodies = [review_patch(seeded, saved["review_sha"], cursor_s=s) for s in (0.3, 0.4)]
    replies = both_at_once(route, bodies)
    assert sorted(code for code, _ in replies) == [200, 409], replies
    assert next(body for code, body in replies if code == 409)["error"] == "ReviewChanged"
    won = next(k for k, (code, _) in enumerate(replies) if code == 200)
    doc = page().get(route).json()["document"]
    assert doc["cursor_s"] == bodies[won]["cursor_s"]
    assert len(doc["corrections"]) == 1


def test_the_whole_review_put_still_works_for_any_caller(seeded: dict[str, Any]) -> None:
    saved = created(seeded)
    again = page().put(f"/api/transcripts/{seeded['id']}/review", json=document(sha(seeded)))
    assert again.status_code == 200
    # The same document sent whole again is the same review, so the same sha.
    assert again.json()["review_sha"] == saved["review_sha"]
