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

A list is made from one transcript, but the transcript's path outlives it: a
run from the app with the same settings writes the same JSON again (#249).
So each saved list keeps, beside it as `<key>.source.json`, the sha256 of the
transcript it was saved against. Opened against a transcript that no longer
has that sha, the list is moved aside, never deleted, and a fresh one is built
from the new words, keeping only the speakers' names, which belong to the
voices and not to the words.

Plain Python, no fastapi: the routes are dsj/ui/routes/marks.py.
"""

from __future__ import annotations

__all__ = [
    "SOURCE",
    "WRITING",
    "ListChanged",
    "NoSuchTranscript",
    "Opened",
    "Saved",
    "TranscriptChanged",
    "as_payload",
    "display_name",
    "edits_path",
    "engine_of",
    "kept_with",
    "labels_of",
    "list_sha",
    "notice_path",
    "open_edits",
    "patch_edits",
    "save_edits",
    "save_names",
    "source_path",
    "transcript_sha",
]

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dsj import hatao
from dsj.atomic import atomic_write_text
from dsj.ui.store import Library, library_path

_log = logging.getLogger(__name__)

# The one source id a list built from a transcript plays from (hatao.from_transcript).
SOURCE = "0"

# Held while a save reads the list and writes it back. The page saves its
# entries and its speaker names by two routes (#243), each keeping what the
# other last wrote, and the server runs requests on a thread pool: without it
# a rename landing during an entries save could write back the names, or the
# entries, from before. Also held while a stale list is moved aside (#249),
# while a review is saved (dsj/ui/review.py, #248), and while a run moves a
# transcript's files to another name (dsj/ui/jobs.py, keep_earlier_roman_run),
# so none of them reads a path the other is moving. Never held while the
# transcript itself is read (see _read), which may be a Google Drive download.
# Re-entrant, so code holding it may call a function that takes it.
WRITING = threading.RLock()


class NoSuchTranscript(LookupError):
    """The library has no transcript with this id, or its JSON file is gone."""


class TranscriptChanged(RuntimeError):
    """The transcript was made again since the page, or the review, was made from it (#249)."""


class ListChanged(RuntimeError):
    """A patch was made against an edit list the server no longer holds (#251)."""


@dataclass(frozen=True)
class Opened:
    """A transcript's edit list, and what the page needs beside it."""

    doc: hatao.Document
    # When the list was last saved, or None for one built just now and never saved.
    edited_at: str | None
    # Each entry's confidence as the page tints it (#62), None for paragraphs,
    # pauses and words with none: see `_confidences`.
    confidence: list[float | None]
    # The recording's length as the library knows it, or None when unknown.
    duration_s: float | None
    # The sha256 of the transcript JSON the list was opened or saved against (#249).
    transcript_sha: str
    # The transcript's own speaker labels, in its order: what "Speaker n" counts by.
    legend: tuple[str, ...] = ()
    # Why a saved list was put aside, when the transcript was made again (#249).
    replaced: str | None = None


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


# A file's size and modification time: what says it is the file that was read.
type _Stamp = tuple[int, int]


def _stamp(path: Path) -> _Stamp:
    found = path.stat()
    return found.st_size, found.st_mtime_ns


def _gone(transcript_id: int, json_path: Path) -> NoSuchTranscript:
    return NoSuchTranscript(
        f"Transcript {transcript_id} was last seen at {json_path}, and that file is "
        f"gone. The library is only an index; the JSON file is the transcript."
    )


def _read_stamped(transcript_id: int) -> tuple[dict[str, Any], str, _Stamp]:
    """The transcript's payload, its sha and its stamp, from one open, so none can disagree."""
    row = _row(transcript_id)
    try:
        with row.json_path.open("rb") as f:
            found = os.fstat(f.fileno())
            raw = f.read()
    except FileNotFoundError:
        raise _gone(transcript_id, row.json_path) from None
    stamp = (found.st_size, found.st_mtime_ns)
    return cast("dict[str, Any]", json.loads(raw)), hashlib.sha256(raw).hexdigest(), stamp


def _read(transcript_id: int) -> tuple[dict[str, Any], str]:
    """The transcript's payload and its sha, from one read, so the two cannot disagree."""
    payload, digest, _ = _read_stamped(transcript_id)
    return payload, digest


# How many times a transcript rewritten while it was being read is read again
# before the last read is used as it is. A run writes its transcript once, at
# the end, so a second read is already rare.
_REREADS = 3


@contextmanager
def _held(transcript_id: int) -> Generator[tuple[_Row, dict[str, Any], str]]:
    """WRITING, with the transcript's row, payload and sha as they are while it is held.

    The transcript is read before WRITING is taken, never under it: it may sit
    in an online-only Google Drive folder, and its download must not hold up
    every other request. Under the lock only the row (the library's, local) and
    the file's size and modification time are looked at again: a run that
    moved the file (keep_earlier_roman_run) moved its bytes unchanged, so the
    row says where, and a stamp that differs means the transcript was written
    again while it was read, so it is read again.
    """
    for attempt in range(1, _REREADS + 1):
        payload, digest, stamp = _read_stamped(transcript_id)
        with WRITING:
            row = _row(transcript_id)
            try:
                now = _stamp(row.json_path)
            except FileNotFoundError:
                raise _gone(transcript_id, row.json_path) from None
            if now == stamp or attempt == _REREADS:
                if now != stamp:
                    _log.warning("%s kept changing while it was read", row.json_path)
                yield row, payload, digest
                return


def _payload(transcript_id: int) -> dict[str, Any]:
    return _read(transcript_id)[0]


def transcript_sha(json_path: Path) -> str:
    """The sha256 of the transcript JSON's bytes: what an edit list and a review are made from."""
    return hashlib.sha256(json_path.read_bytes()).hexdigest()


def source_path(path: Path) -> Path:
    """Where the sha of the transcript the edit list at `path` was made from is kept (#249)."""
    return path.with_name(f"{path.stem}.source.json")


def notice_path(path: Path) -> Path:
    """Where the sentence saying the list at `path` was put aside waits for the page (#249)."""
    return path.with_name(f"{path.stem}.replaced.txt")


def kept_with(json_path: Path) -> tuple[Path, ...]:
    """Every file the app keeps for the transcript at `json_path` under its key, but the review.

    A run that moves the transcript to another name moves these with it
    (dsj/ui/jobs.py, keep_earlier_roman_run).
    """
    path = edits_path(json_path)
    return path, source_path(path), notice_path(path)


def _made_from(path: Path) -> str | None:
    """The sha the list at `path` was saved against, or None when that is not known.

    None for a list saved before #249, which has no note, and for a note that
    no longer reads, which is logged: either way the list is trusted as lists
    were before #249, and its next save writes the note again. A broken note
    must not make the transcript unopenable.
    """
    try:
        raw = json.loads(source_path(path).read_text(encoding="utf-8"))
        return str(cast("dict[str, Any]", raw)["transcript_sha"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log.warning("the note %s could not be read, so the list is trusted: %s", path, exc)
        return None


def _note_source(path: Path, digest: str) -> None:
    """Keep beside the list at `path` the sha of the transcript it was saved against."""
    atomic_write_text(source_path(path), json.dumps({"transcript_sha": digest}), fsync=True)


def _aside(path: Path, digest: str) -> Path:
    """A free name beside `path` for a list made from the transcript with sha `digest`.

    A transcript made again to the very words of an earlier one has the same
    sha, so an earlier list kept under it is never written over: the later one
    takes the next free numbered name.
    """
    aside, n = path.with_name(f"{path.stem}.{digest[:12]}.json"), 1
    while aside.exists():
        n += 1
        aside = path.with_name(f"{path.stem}.{digest[:12]}-{n}.json")
    return aside


def _put_aside(path: Path, made_from: str) -> None:
    """Move a stale list and its note aside, never deleting them, and leave word for the page.

    The sentence waits beside the list until a GET of the list hands it to
    the page (`open_edits(report=True)`), so a list put aside by an export, a
    match or a render, which show the page no such sentence, is still told.
    """
    aside = _aside(path, made_from)
    path.replace(aside)
    source_path(path).replace(source_path(aside))
    said = (
        "This transcript was made again after it was last edited, so the old edits no longer "
        f"fit its words. They are kept beside the library as {aside.name}; this list starts "
        "again from the new transcript."
    )
    atomic_write_text(notice_path(path), said, fsync=True)


def _names_of_stale(path: Path) -> dict[str, str]:
    """The speakers' names in a stale list, to carry to the fresh one; {} when it cannot be read.

    The list is being put aside whole, so one that no longer reads loses
    nothing by it: only its names are not carried, and that is logged.
    """
    try:
        return dict(hatao.load(path).names)
    except hatao.InvalidDocument as exc:
        _log.warning("the speaker names in %s could not be carried to the new list: %s", path, exc)
        return {}


def _settle(row: _Row, payload: dict[str, Any], digest: str) -> Path:
    """Put the transcript's list aside if it was made from other words; where the list lives.

    Held under WRITING. A list with speaker names gets a fresh list in its
    place holding them, since names belong to the voices and not to the words,
    so the next open finds them and has nothing to put aside.
    """
    path = edits_path(row.json_path)
    made_from = _made_from(path) if path.is_file() else None
    if made_from is None or made_from == digest:
        return path
    names = _names_of_stale(path)
    _put_aside(path, made_from)
    if names:
        fresh = hatao.from_transcript(
            payload, row.media, duration_s=row.duration_s, language=row.language
        )
        hatao.save(hatao.Document(fresh.sources, fresh.content, names), path)
        _note_source(path, digest)
    return path


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


def _legend(payload: dict[str, Any]) -> tuple[str, ...]:
    """The transcript's speaker labels, text only: an old file's non-text entries are skipped."""
    return tuple(s for s in cast("list[Any]", payload.get("speakers") or []) if isinstance(s, str))


def _edited_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def _current(row: _Row, payload: dict[str, Any], path: Path) -> tuple[hatao.Document, str | None]:
    """The list at `path` and when it was saved, or the untouched one built from `payload`."""
    if path.is_file():
        saved = hatao.load(path)
        doc = hatao.validate(
            hatao.Document({SOURCE: str(row.media.resolve())}, saved.content, saved.names)
        )
        return doc, _edited_at(path)
    doc = hatao.from_transcript(
        payload, row.media, duration_s=row.duration_s, language=row.language
    )
    return doc, None


def open_edits(transcript_id: int, *, report: bool = False) -> Opened:
    """The transcript's saved edit list, or its untouched one built from the transcript.

    A list made from a transcript since made again is put aside first (#249).
    The sentence saying so waits until it is reported: `report` is the page's
    own GET of the list, which hands it on and clears it. Every other caller
    (export, matches, render, the answer key) leaves it waiting.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        dsj.hatao.TranscriptUnusable: the transcript has no word end times,
            so no list can be built without guessing where words stop.
        dsj.hatao.InvalidDocument: the saved list is broken, named.
    """
    with _held(transcript_id) as (row, payload, digest):
        path = _settle(row, payload, digest)
        notice = notice_path(path)
        replaced = notice.read_text(encoding="utf-8") if notice.is_file() else None
        if report and replaced is not None:
            notice.unlink()
        doc, edited_at = _current(row, payload, path)
    return Opened(
        doc,
        edited_at,
        _confidences(payload, doc),
        row.duration_s,
        digest,
        _legend(payload),
        replaced,
    )


def list_sha(doc: hatao.Document) -> str:
    """The sha256 of an edit list as the server holds it: its entries and its speaker names (#251).

    The one serialisation the sha is taken over, so a list read again, or
    saved and loaded back, has the same sha: each entry as a row of its
    fields, in the file's order, and the names sorted by label, as compact
    JSON. The sources are left out: they are the server's to fill in (a
    recording moved, #110, is the same list), never the page's to change.
    A patch names the list it was made against by this sha, so a list changed
    by another tab, or by a rename, is never patched as if it were not.
    """
    rows: list[list[Any]] = []
    for entry in doc.content:
        if isinstance(entry, hatao.Paragraph):
            rows.append(["paragraph", entry.speaker, entry.language])
        else:
            rows.append(
                ["item", entry.source, entry.source_start, entry.length, entry.text, entry.muted]
            )
    names = sorted(doc.names.items())
    canonical = json.dumps([rows, names], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _write(
    transcript_id: int,
    row: _Row,
    content: tuple[hatao.Entry, ...],
    names: Mapping[str, str],
    digest: str,
) -> tuple[hatao.Document, str]:
    """Write `content` and `names` as the transcript's edit list, whole or not at all; and when.

    Held under WRITING, with the row as read under it and the transcript as
    read before it was taken (`_held`).
    """
    doc = hatao.validate(hatao.Document({SOURCE: str(row.media.resolve())}, content, dict(names)))
    path = edits_path(row.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    hatao.save(doc, path)
    _note_source(path, digest)
    edited_at = _edited_at(path)
    # So the library list can say this transcript was corrected by hand (#83).
    with Library.open() as library:
        library.mark_edited(transcript_id, edited_at)
    return doc, edited_at


def _save(
    transcript_id: int,
    row: _Row,
    content: tuple[hatao.Entry, ...],
    names: Mapping[str, str],
    payload: dict[str, Any],
    digest: str,
) -> Opened:
    """Write the list as `_write` does, and answer it as the page opens it."""
    doc, edited_at = _write(transcript_id, row, content, names, digest)
    return Opened(
        doc, edited_at, _confidences(payload, doc), row.duration_s, digest, _legend(payload)
    )


@dataclass(frozen=True)
class Saved:
    """What a patch leaves on the server, and no more: never the entries (#251)."""

    doc: hatao.Document
    edited_at: str
    # The recording's length as the library knows it, for the spans a render would mute.
    duration_s: float | None


def patch_edits(
    transcript_id: int,
    transcript_sha: str,
    against: str,
    start: int,
    delete: int,
    insert: Sequence[hatao.Entry],
) -> Saved:
    """Put `insert` in place of `delete` entries at `start` of the list whose sha is `against`.

    One change, not the whole list (#251). The spliced list is checked and
    written exactly as `save_edits` writes one (validated whole, the entry
    named when it is broken; atomic, fsynced, under WRITING), so a patch is
    never a weaker save. Two patches made against the same list cannot both
    apply: the second finds the list changed and is refused.

    A patch against a transcript made again is refused as `save_edits`
    refuses one, but keeps nothing aside: the page holds the whole list, and
    sends it whole to be kept (editing.ts, useSave).

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        TranscriptChanged: the transcript was made again since the page loaded the list.
        ListChanged: the list is not the one the patch was made against.
        dsj.hatao.InvalidDocument: `start` and `delete` reach outside the list,
            or the spliced list is broken, named; nothing is written.
    """
    with _held(transcript_id) as (row, payload, digest):
        path = _settle(row, payload, digest)
        if transcript_sha != digest:
            raise TranscriptChanged(
                "This transcript was made again while it was open, so this change is to words "
                "it no longer has. Reload the page to see the new transcript."
            )
        doc, _ = _current(row, payload, path)
        if list_sha(doc) != against:
            raise ListChanged(
                "This transcript's edits were changed in another tab or window after this page "
                "loaded them, so this change was not saved. Reload the page to load them again."
            )
        size = len(doc.content)
        if not (0 <= start <= size and 0 <= delete <= size - start):
            raise hatao.InvalidDocument(
                f"the change replaces entries from start {start}, delete {delete}, of a list "
                f"of {size}; it must lie inside the list"
            )
        content = (*doc.content[:start], *insert, *doc.content[start + delete :])
        saved, edited_at = _write(transcript_id, row, content, doc.names, digest)
    return Saved(saved, edited_at, row.duration_s)


def save_edits(
    transcript_id: int, content: tuple[hatao.Entry, ...], transcript_sha: str
) -> Opened:
    """Save the page's entries as the transcript's edit list, keeping the speaker names it has.

    `transcript_sha` is the sha of the transcript the page loaded the list
    against. When the transcript has been made again since (#249), the page's
    entries are words the transcript no longer has: they are kept aside under
    their own name, nothing typed is lost, and the save is refused so the page
    reloads, rather than saved over the new transcript and trusted.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        dsj.hatao.InvalidDocument: the entries are broken, named; nothing is written.
        TranscriptChanged: the transcript was made again since the page loaded the list.
    """
    with _held(transcript_id) as (row, payload, digest):
        path = _settle(row, payload, digest)
        names: Mapping[str, str] = hatao.load(path).names if path.is_file() else {}
        if transcript_sha != digest:
            doc = hatao.validate(
                hatao.Document({SOURCE: str(row.media.resolve())}, content, dict(names))
            )
            aside = _aside(path, transcript_sha)
            aside.parent.mkdir(parents=True, exist_ok=True)
            hatao.save(doc, aside)
            _note_source(aside, transcript_sha)
            raise TranscriptChanged(
                "This transcript was made again while it was open, so these edits are to "
                f"words it no longer has. They are kept beside the library as {aside.name}. "
                "Reload the page to see the new transcript."
            )
        return _save(transcript_id, row, content, names, payload, digest)


def save_names(
    transcript_id: int, names: Mapping[str, str], transcript_sha: str, against: str
) -> Opened:
    """Save the names a person gave the speakers (#243), keeping the entries as they are.

    Names are trimmed, and a blank one is left out, so that speaker shows its
    own label ("Speaker 2") again.

    Made against the list whose sha is `against`, and refused as a patch is
    when the server holds another (#274, final review C1). Unguarded, a rename
    made on a laptop after a phone's patch was saved, and answered the phone's
    list sha: the laptop took that sha as its own while holding the list from
    before, so its next correction passed the check and was spliced by index
    into a list of another shape. It also replaced the phone's names whole.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        TranscriptChanged: the transcript was made again since the page loaded the list.
        ListChanged: the list is not the one the rename was made against.
        dsj.hatao.InvalidDocument: a label is blank; nothing is written.
    """
    kept = {label: name.strip() for label, name in names.items() if name.strip()}
    with _held(transcript_id) as (row, payload, digest):
        path = _settle(row, payload, digest)
        if transcript_sha != digest:
            raise TranscriptChanged(
                "This transcript was made again while it was open, so these names were not "
                "saved. Reload the page to see the new transcript."
            )
        doc, _ = _current(row, payload, path)
        if list_sha(doc) != against:
            raise ListChanged(
                "This transcript's edits were changed in another tab or window after this page "
                "loaded them, so these names were not saved. Reload the page to load them again."
            )
        return _save(transcript_id, row, doc.content, kept, payload, digest)


def engine_of(transcript_id: int) -> str:
    """The engine that wrote the transcript, as `dsj hatao` names it in its recall line.

    The library's record of the run first, then the file's own `engine`, then its model id.
    """
    with Library.open() as library:
        found = library.transcript(transcript_id)
    if found is not None and found.engine:
        return found.engine
    payload = _payload(transcript_id)
    return str(payload.get("engine") or payload.get("model") or "this engine")


# A diarizer's own label, which the page shows as "Speaker n" by its place in
# the transcript's list (ui/src/features/transcript/document.ts, speakerName).
_DIARIZER_LABEL = re.compile(r"SPEAKER_\d+")

# What an exported file says where a word was muted.
_MASK = "[bleep]"


def labels_of(opened: Opened) -> list[str]:
    """The transcript's speaker labels, then any the list uses that it lacks, in order of first use.

    The page reads speakers the same way (readContent.ts, speakerLabels), so a
    speaker a person added in Review is "Speaker 3" in both.
    """
    labels = list(opened.legend)
    for entry in opened.doc.content:
        if isinstance(entry, hatao.Paragraph) and entry.speaker and entry.speaker not in labels:
            labels.append(entry.speaker)
    return labels


def display_name(label: str | None, labels: Sequence[str], names: Mapping[str, str]) -> str | None:
    """The name a person gave `label`, else "Speaker n" for a diarizer's label, else the label."""
    if label is None:
        return None
    if label in names:
        return names[label]
    if _DIARIZER_LABEL.fullmatch(label) and label in labels:
        return f"Speaker {list(labels).index(label) + 1}"
    return label


def as_payload(opened: Opened) -> dict[str, Any]:
    """The edit list as a transcript dsj likho can write (#244).

    One sentence per paragraph mark, its words as edited (a correction, #83,
    reads as corrected), each speaker under the name a person gave them.
    Paragraphs with no words are left out, as likho leaves them out. A muted
    word is written as `[bleep]`: a word a person chose to silence must not
    come back in a subtitle file or a text. A paragraph whose speaker is blank
    has no speaker, as the page shows it.
    """
    labels = labels_of(opened)
    sentences: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] | None = None
    speaker: int | None = None

    def close() -> None:
        if tokens:
            sentences.append(
                {
                    "start": tokens[0]["t"],
                    "end": max(t["e"] for t in tokens),
                    "text": "".join(t["w"] for t in tokens),
                    "speaker": speaker,
                    "tokens": tokens,
                }
            )

    for entry in opened.doc.content:
        if isinstance(entry, hatao.Paragraph):
            close()
            tokens = []
            speaker = labels.index(entry.speaker) if entry.speaker else None
            continue
        if tokens is not None and entry.text:
            # The word's leading space stays, so the line still breaks between words.
            lead = entry.text[: len(entry.text) - len(entry.text.lstrip())]
            word = lead + _MASK if entry.muted else entry.text
            tokens.append({"t": entry.source_start, "e": entry.source_end, "w": word})
    close()
    payload: dict[str, Any] = {"sentences": sentences}
    if labels:
        payload["speakers"] = [display_name(label, labels, opened.doc.names) for label in labels]
    return payload
