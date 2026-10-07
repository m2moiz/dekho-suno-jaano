"""A transcript's edit list, read and saved by the page (#63, #66), and the words to bleep (#84).

#57 named this module for "marks, edit list, detectors". The work is in
dsj/ui/edits.py, dsj/ui/words.py and dsj.hatao; this file only turns requests
into their calls and their documents into the shapes dsj/ui/schemas.py
describes. The page never matches words or works out what to mute itself:
both are dsj.hatao's, the very code `dsj hatao` runs, so the app and the
terminal cannot disagree.
"""

from __future__ import annotations

__all__ = ["entries", "router"]

import math

from fastapi import APIRouter, HTTPException

from dsj import hatao
from dsj.ui import edits, words
from dsj.ui.schemas import (
    EditEntry,
    Edits,
    EditsUpdate,
    ItemEntry,
    Match,
    Matches,
    NamesUpdate,
    ParagraphEntry,
    WordAdded,
    WordRequest,
)

router = APIRouter(prefix="/api")


def _id(transcript_id: str) -> int:
    """The id as a number, or the same 404 the transcript route gives for anything else."""
    if not (transcript_id.isascii() and transcript_id.isdigit()):
        raise HTTPException(404, f"There is no transcript {transcript_id!r} in the library.")
    return int(transcript_id)


def _wire(opened: edits.Opened) -> Edits:
    content: list[EditEntry] = []
    for entry, confidence in zip(opened.doc.content, opened.confidence, strict=True):
        if isinstance(entry, hatao.Paragraph):
            content.append(
                ParagraphEntry(kind="paragraph", speaker=entry.speaker, language=entry.language)
            )
        else:
            content.append(
                ItemEntry(
                    kind="item",
                    source=entry.source,
                    sourceStart=entry.source_start,
                    length=entry.length,
                    text=entry.text,
                    muted=entry.muted,
                    confidence=confidence,
                )
            )
    spans: list[tuple[float, float]] | None = None
    unrenderable: str | None = None
    try:
        # A length the library never learned leaves the last span unclipped,
        # which plays the same: nothing is after the recording's end to mute.
        spans = hatao.spans_to_mute(
            opened.doc,
            duration_s=math.inf if opened.duration_s is None else opened.duration_s,
        )
    except hatao.RenderRefused as exc:
        unrenderable = str(exc)
    return Edits(
        content=content,
        names=dict(opened.doc.names),
        pad_s=hatao.PAD_S,
        edited_at=opened.edited_at,
        spans=spans,
        unrenderable=unrenderable,
    )


def _entry(wire: EditEntry) -> hatao.Entry:
    if isinstance(wire, ParagraphEntry):
        return hatao.Paragraph(speaker=wire.speaker, language=wire.language)
    return hatao.Item(wire.source, wire.sourceStart, wire.length, wire.text, wire.muted)


def entries(update: EditsUpdate) -> tuple[hatao.Entry, ...]:
    """The page's entries as dsj.hatao's, `confidence` left behind: it is not in the file."""
    return tuple(_entry(entry) for entry in update.content)


@router.get("/transcripts/{transcript_id}/edits")
def read_edits(transcript_id: str) -> Edits:
    """The transcript's edit list: as last saved, or as the transcript made it.

    A transcript without word end times (before v0.2.0, or a `dsj parho`
    import) has none, and is answered 422 with the reason: it still reads,
    but cannot be edited without guessing where each word stops.
    """
    return _wire(edits.open_edits(_id(transcript_id)))


@router.put("/transcripts/{transcript_id}/edits")
def save_edits(transcript_id: str, update: EditsUpdate) -> Edits:
    """Save the page's edit list in place of the last one, or refuse it whole, naming the entry."""
    return _wire(edits.save_edits(_id(transcript_id), entries(update)))


@router.put("/transcripts/{transcript_id}/names")
def save_names(transcript_id: str, update: NamesUpdate) -> Edits:
    """Save the speakers' names in the transcript's edit list, the words untouched (#243)."""
    return _wire(edits.save_names(_id(transcript_id), update.names))


@router.post("/transcripts/{transcript_id}/matches")
def find_matches(transcript_id: str, update: EditsUpdate) -> Matches:
    """Every word of the page's edit list a word list spells, by dsj.hatao.find itself.

    The page sends its list as it is now, so a word it has just retyped
    (#83) is matched as retyped. Nothing is saved.
    """
    opened = edits.open_edits(_id(transcript_id))
    doc = hatao.validate(hatao.Document(opened.doc.sources, entries(update)))
    found = hatao.find(doc, hatao.load_words(hatao.word_lists()))
    engine = edits.engine_of(_id(transcript_id))
    return Matches(
        matches=[
            Match(
                start=m.start,
                stop=m.stop,
                word=m.word,
                entry=m.entry,
                start_s=m.source_start,
                end_s=m.source_end,
            )
            for m in found.matches
        ],
        words_searched=found.words_searched,
        lists=[path.stem if path != hatao.user_words_path() else "user" for path in found.lists],
        recall=hatao.recall_line(engine),
    )


@router.post("/words")
def add_word(request: WordRequest) -> WordAdded:
    """Add a spelling to the user's own word list, the one `dsj hatao` reads too.

    A spelling some list already has is not written again; its entry is the answer.
    """
    added = words.add_word(request.word)
    return WordAdded(entry=added.entry, added=added.added)
