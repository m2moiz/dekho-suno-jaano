"""A transcript's edit list, read and saved by the page (#63, #66).

#57 named this module for "marks, edit list, detectors". The work is in
dsj/ui/edits.py; this file only turns requests into its calls and its
documents into the shapes dsj/ui/schemas.py describes.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter, HTTPException

from dsj import hatao
from dsj.ui import edits
from dsj.ui.schemas import EditEntry, Edits, EditsUpdate, ItemEntry, ParagraphEntry

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
    return Edits(content=content, pad_s=hatao.PAD_S, edited_at=opened.edited_at)


def _entry(wire: EditEntry) -> hatao.Entry:
    if isinstance(wire, ParagraphEntry):
        return hatao.Paragraph(speaker=wire.speaker, language=wire.language)
    return hatao.Item(wire.source, wire.sourceStart, wire.length, wire.text, wire.muted)


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
    content = tuple(_entry(entry) for entry in update.content)
    return _wire(edits.save_edits(_id(transcript_id), content))
