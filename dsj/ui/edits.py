"""A library transcript's edit list (#63) as the app reads and saves it (#66).

The document is `dsj.hatao`'s: the same file `dsj hatao` could walk, written by
`dsj.hatao.save`, so an edit made in the app and a bleep made in the terminal
mean one thing. This module only says where each transcript's list lives, and
builds the untouched one from the transcript the first time it is asked for.

The list lives beside the library, in `edits/`, never beside the recording or
the transcript: the app does not write into the owner's folders. Its file is
named for the transcript's JSON path, not the library's row id, because the
library can be deleted and rebuilt (dsj/ui/store.py), and a rebuilt library
hands out ids again from 1: a list filed under an id would then open under some
other transcript. The same path is the same transcript after any rebuild.

The page never sees or sends a path (#112 rule 5). Its entries name their
source by id, and the server fills in which file that id is from the library
on every load and save, so a page cannot point a render at a file of its
choosing, and a recording re-pointed after a move (#110) is followed.

Plain Python, no fastapi: the routes are dsj/ui/routes/marks.py.
"""

from __future__ import annotations

__all__ = ["SOURCE", "NoSuchTranscript", "Opened", "edits_path", "open_edits", "save_edits"]

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dsj import hatao
from dsj.ui.store import Library, library_path

# The one source id a list built from a transcript plays from (hatao.from_transcript).
SOURCE = "0"


class NoSuchTranscript(LookupError):
    """The library has no transcript with this id, or its JSON file is gone."""


@dataclass(frozen=True)
class Opened:
    """A transcript's edit list, and what the page needs beside it."""

    doc: hatao.Document
    # When the list was last saved, or None for one built just now and never saved.
    edited_at: str | None
    # Each entry's confidence as the page tints it (#62), None for paragraphs,
    # pauses and words with none: see `_confidences`.
    confidence: list[float | None]


def edits_path(json_path: Path) -> Path:
    """Where the edit list of the transcript at `json_path` is kept."""
    key = hashlib.sha256(str(json_path.resolve()).encode()).hexdigest()[:24]
    return library_path().parent / "edits" / f"{key}.json"


@dataclass(frozen=True)
class _Row:
    json_path: Path
    media: Path
    duration_s: float | None
    language: str | None


def _row(transcript_id: int) -> _Row:
    with Library.open() as library:
        found = library.transcript(transcript_id)
        if found is None:
            raise NoSuchTranscript(f"There is no transcript {transcript_id} in the library.")
        recording = library.recording(found.recording_id)
    assert recording is not None  # transcripts.recording_id is a foreign key
    return _Row(found.json_path, recording.path, recording.duration_s, found.language)


def _payload(row: _Row, transcript_id: int) -> dict[str, Any]:
    try:
        return cast("dict[str, Any]", json.loads(row.json_path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise NoSuchTranscript(
            f"Transcript {transcript_id} was last seen at {row.json_path}, and that file is "
            f"gone. The library is only an index; the JSON file is the transcript."
        ) from None


def _confidences(payload: dict[str, Any], doc: hatao.Document) -> list[float | None]:
    """Each entry's confidence: its token's `c`, or 1.0 for a word edited by hand.

    The edit list carries no confidence of its own, so it is looked up in the
    transcript: an item with exactly the start, length and text
    hatao.from_transcript gave a token has that token's `c`. An item with text
    that matches no token was retyped (#83) or had its edges dragged (#85) by a
    person, and a word a person has checked is sure: 1.0 clears the
    low-confidence tint (#62), which is what #83 asks. Worked out on every
    read, so it never goes stale against the file.
    """
    known: dict[tuple[float, float, str], float | None] = {}
    for sentence in cast("list[dict[str, Any]]", payload.get("sentences") or []):
        for token in cast("list[dict[str, Any]]", sentence.get("tokens") or []):
            if "e" not in token:
                continue
            start = float(token["t"])
            # The very arithmetic hatao.from_transcript uses for an item's length.
            length = round(max(float(token["e"]) - start, 0.0), 3)
            c = token.get("c")
            known[(start, length, str(token["w"]))] = None if c is None else float(c)
    out: list[float | None] = []
    for entry in doc.content:
        if not isinstance(entry, hatao.Item) or not entry.text:
            out.append(None)
            continue
        key = (entry.source_start, entry.length, entry.text)
        out.append(known.get(key, 1.0))
    return out


def _edited_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def open_edits(transcript_id: int) -> Opened:
    """The transcript's saved edit list, or its untouched one built from the transcript.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        dsj.hatao.TranscriptUnusable: the transcript has no word end times,
            so no list can be built without guessing where words stop.
        dsj.hatao.InvalidDocument: the saved list is broken, named.
    """
    row = _row(transcript_id)
    payload = _payload(row, transcript_id)
    path = edits_path(row.json_path)
    if path.is_file():
        saved = hatao.load(path)
        doc = hatao.validate(hatao.Document({SOURCE: str(row.media.resolve())}, saved.content))
        edited_at: str | None = _edited_at(path)
    else:
        doc = hatao.from_transcript(
            payload, row.media, duration_s=row.duration_s, language=row.language
        )
        edited_at = None
    return Opened(doc, edited_at, _confidences(payload, doc))


def save_edits(transcript_id: int, content: tuple[hatao.Entry, ...]) -> Opened:
    """Save the page's entries as the transcript's edit list, whole or not at all.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        dsj.hatao.InvalidDocument: the entries are broken, named; nothing is written.
    """
    row = _row(transcript_id)
    payload = _payload(row, transcript_id)
    doc = hatao.validate(hatao.Document({SOURCE: str(row.media.resolve())}, content))
    path = edits_path(row.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    hatao.save(doc, path)
    return Opened(doc, _edited_at(path), _confidences(payload, doc))
