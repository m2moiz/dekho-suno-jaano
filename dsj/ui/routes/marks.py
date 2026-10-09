"""A transcript's edit list, read and saved by the page (#63, #66), and the words to bleep (#84).

#57 named this module for "marks, edit list, detectors". The work is in
dsj/ui/edits.py, dsj/ui/words.py and dsj.hatao; this file only turns requests
into their calls and their documents into the shapes dsj/ui/schemas.py
describes. The page never matches words or works out what to mute itself:
both are dsj.hatao's, the very code `dsj hatao` runs, so the app and the
terminal cannot disagree.
"""

from __future__ import annotations

__all__ = ["entries", "router", "transcript_number"]

import math

from fastapi import APIRouter, HTTPException, Response

from dsj import hatao, likho
from dsj.ui import edits, words
from dsj.ui.schemas import (
    EditEntry,
    Edits,
    EditsPatch,
    EditsSaved,
    EditsUpdate,
    ItemEntry,
    ListContent,
    Match,
    Matches,
    NamesUpdate,
    ParagraphEntry,
    WordAdded,
    WordRequest,
)

router = APIRouter(prefix="/api")


def transcript_number(transcript_id: str) -> int:
    """The id as a number, or the same 404 the transcript route gives for anything else."""
    if not (transcript_id.isascii() and transcript_id.isdigit()):
        raise HTTPException(404, f"There is no transcript {transcript_id!r} in the library.")
    return int(transcript_id)


def _renderable(doc: hatao.Document, duration_s: float | None) -> tuple[
    list[tuple[float, float]] | None, str | None
]:
    """The stretches a render of `doc` silences, or None and why it cannot be rendered."""
    try:
        # A length the library never learned leaves the last span unclipped,
        # which plays the same: nothing is after the recording's end to mute.
        spans = hatao.spans_to_mute(doc, duration_s=math.inf if duration_s is None else duration_s)
    except hatao.RenderRefused as exc:
        return None, str(exc)
    return spans, None


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
    spans, unrenderable = _renderable(opened.doc, opened.duration_s)
    return Edits(
        content=content,
        names=dict(opened.doc.names),
        pad_s=hatao.PAD_S,
        edited_at=opened.edited_at,
        spans=spans,
        unrenderable=unrenderable,
        replaced=opened.replaced,
        transcript_sha=opened.transcript_sha,
        list_sha=edits.list_sha(opened.doc),
    )


def _entry(wire: EditEntry) -> hatao.Entry:
    if isinstance(wire, ParagraphEntry):
        return hatao.Paragraph(speaker=wire.speaker, language=wire.language)
    return hatao.Item(wire.source, wire.sourceStart, wire.length, wire.text, wire.muted)


def entries(update: ListContent) -> tuple[hatao.Entry, ...]:
    """The page's entries as dsj.hatao's, `confidence` left behind: it is not in the file."""
    return tuple(_entry(entry) for entry in update.content)


@router.get("/transcripts/{transcript_id}/edits")
def read_edits(transcript_id: str) -> Edits:
    """The transcript's edit list: as last saved, or as the transcript made it.

    A transcript without word end times (before v0.2.0, or a `dsj parho`
    import) has none, and is answered 422 with the reason: it still reads,
    but cannot be edited without guessing where each word stops.

    This is the page's own read of the list, so it is the one that hands on,
    and clears, the sentence saying a list was put aside because the
    transcript was made again (#249), whichever route put it aside.
    """
    return _wire(edits.open_edits(transcript_number(transcript_id), report=True))


@router.put("/transcripts/{transcript_id}/edits")
def save_edits(transcript_id: str, update: EditsUpdate) -> Edits:
    """Save the page's edit list in place of the last one, or refuse it whole, naming the entry."""
    found = transcript_number(transcript_id)
    return _wire(edits.save_edits(found, entries(update), update.transcript_sha))


@router.patch("/transcripts/{transcript_id}/edits")
def patch_edits(transcript_id: str, change: EditsPatch) -> EditsSaved:
    """Save one change to the edit list, made against the list `list_sha` names (#251).

    The answer is the new list's sha and what a render would mute, never the
    entries: on a 2.5 h transcript those were 3.5 MB each way per correction.
    """
    saved = edits.patch_edits(
        transcript_number(transcript_id),
        change.transcript_sha,
        change.list_sha,
        change.start,
        change.delete,
        tuple(_entry(entry) for entry in change.insert),
    )
    spans, unrenderable = _renderable(saved.doc, saved.duration_s)
    return EditsSaved(
        list_sha=edits.list_sha(saved.doc),
        edited_at=saved.edited_at,
        spans=spans,
        unrenderable=unrenderable,
    )


@router.put("/transcripts/{transcript_id}/names")
def save_names(transcript_id: str, update: NamesUpdate) -> Edits:
    """Save the speakers' names in the transcript's edit list, the words untouched (#243).

    Made against the list `list_sha` names, as a patch is (#274): a rename is
    a change to the list, and the page takes the sha it answers as its own.
    """
    found = transcript_number(transcript_id)
    return _wire(edits.save_names(found, update.names, update.transcript_sha, update.list_sha))


@router.get(
    "/transcripts/{transcript_id}/export/{fmt}",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}, "text/vtt": {}}}},
)
def export(transcript_id: str, fmt: str) -> Response:
    """The transcript as edited, as SRT, WebVTT or plain text, by dsj likho's own writers (#244).

    A download, by the transcript's id: nothing is written on this machine,
    and no path reaches the page (#112 rule 5).
    """
    write = likho.EXPORTERS.get(fmt)
    if write is None:
        known = ", ".join(sorted(likho.EXPORTERS))
        raise HTTPException(404, f"There is no export format {fmt!r}; there are {known}.")
    found = transcript_number(transcript_id)
    text = write(edits.as_payload(edits.open_edits(found)))
    return Response(
        content=text,
        media_type="text/vtt; charset=utf-8" if fmt == "vtt" else "text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="transcript-{found}.{fmt}"'},
    )


@router.post("/transcripts/{transcript_id}/matches")
def find_matches(transcript_id: str, update: ListContent) -> Matches:
    """Every word of the page's edit list a word list spells, by dsj.hatao.find itself.

    The page sends its list as it is now, so a word it has just retyped
    (#83) is matched as retyped. Nothing is saved.
    """
    opened = edits.open_edits(transcript_number(transcript_id))
    doc = hatao.validate(hatao.Document(opened.doc.sources, entries(update)))
    found = hatao.find(doc, hatao.load_words(hatao.word_lists()))
    engine = edits.engine_of(transcript_number(transcript_id))
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
