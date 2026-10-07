"""A transcript's review (Hashiya spec, Review mode, #248), and the answer key it becomes.

A review says which of a transcript's sentences a person has checked against
the audio, what they flagged, which speaker they set, and where they were. It
is a document of its own, beside the library in `reviews/`, under the same
key as the transcript's edit list (dsj/ui/edits.py, edits_path): the
transcript JSON's path, so a rebuilt library finds it again, and never beside
the recording. It never holds words: the words are the edit list's, where
Review's corrections go, so the reader shows them too. A sentence is a span of
the recording, which every edit keeps (a correction keeps its stretch's ends,
#83), so the review survives later corrections.

A transcript made again keeps its review (#249): the review names the sha of
the transcript it was made against, and the page, seeing it differ, keeps the
checked sentences whose span still matches and unchecks the rest.

The answer key is written beside the transcript JSON, as
`<name>.reference.json` (the sentences with their spans, speakers, final words
and flags, and the transcript and model they were checked against) and a plain
`<name>.reference.txt`. Scoring against it is sub-project E.

Plain Python, no fastapi: the routes are dsj/ui/routes/review.py.
"""

from __future__ import annotations

__all__ = [
    "InvalidReview",
    "ReviewIncomplete",
    "progress",
    "read_review",
    "reference",
    "review_path",
    "save_review",
]

import json
import logging
import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dsj import hatao
from dsj.atomic import atomic_write_text, atomic_write_texts
from dsj.suno import clock
from dsj.ui import edits
from dsj.ui.edits import NoSuchTranscript, TranscriptChanged, edits_path, transcript_sha
from dsj.ui.schemas import ReferenceWritten, ReviewDocument, ReviewSegment
from dsj.ui.store import Library, Transcript, library_path

_log = logging.getLogger(__name__)

# Half a millisecond: dsj/hatao.py rounds times to the millisecond.
EPS = 0.0005

# How the plain answer key says each flag.
_FLAG_WORDS = {
    "unclear": "can't make it out",
    "not_speech": "not speech",
    "overlap": "overlapping talk",
    "cut_off": "cut off",
}


class InvalidReview(ValueError):
    """A review document that is broken. The message names the segment and what is wrong."""


class ReviewIncomplete(ValueError):
    """An answer key asked for while sentences are unchecked, without allow_partial."""


def review_path(json_path: Path) -> Path:
    """Where the review of the transcript at `json_path` is kept."""
    return library_path().parent / "reviews" / edits_path(json_path).name


def progress(json_path: Path) -> tuple[int, int] | None:
    """How many of the review's sentences are checked, and how many it has; None with no review.

    A review file that cannot be read is logged and left out of the list: the
    library still lists every recording, and opening the review says what is
    wrong with it.
    """
    path = review_path(json_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        segments = cast("list[dict[str, Any]]", raw["segments"])
        checked = sum(1 for s in segments if s.get("state") == "checked")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        _log.warning("the review at %s could not be read for the library list: %s", path, exc)
        return None
    return checked, len(segments)


def _transcript(transcript_id: int) -> Transcript:
    """The library's row for the transcript, whose JSON file is where the row says."""
    with Library.open() as library:
        found = library.transcript(transcript_id)
    if found is None:
        raise NoSuchTranscript(f"There is no transcript {transcript_id} in the library.")
    if not found.json_path.is_file():
        raise NoSuchTranscript(
            f"Transcript {transcript_id} was last seen at {found.json_path}, and that file is "
            f"gone. The library is only an index; the JSON file is the transcript."
        )
    return found


def read_review(transcript_id: int) -> tuple[ReviewDocument | None, str]:
    """The transcript's review, or None, and the sha of the transcript as it is now.

    The transcript is hashed before WRITING is taken (it may be a Google Drive
    download); the review, a small file beside the library, is read under it,
    where the library says the transcript is now.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        InvalidReview: the saved review cannot be read, named.
    """
    digest = transcript_sha(_transcript(transcript_id).json_path)
    with edits.WRITING:
        path = review_path(_transcript(transcript_id).json_path)
        raw = path.read_text(encoding="utf-8") if path.is_file() else None
    if raw is None:
        return None, digest
    try:
        return ReviewDocument.model_validate_json(raw), digest
    except ValueError as exc:
        raise InvalidReview(f"The review at {path} cannot be read: {exc}") from exc


def _check(document: ReviewDocument) -> None:
    """Raise naming the first segment that is not a span after the one before it."""
    if not math.isfinite(document.cursor_s):
        raise InvalidReview(f"cursor_s is {document.cursor_s}; it must be a number of seconds")
    reached = 0.0
    for index, segment in enumerate(document.segments):
        finite = math.isfinite(segment.start) and math.isfinite(segment.end)
        if not (finite and 0 <= segment.start < segment.end):
            raise InvalidReview(
                f"segment {index} runs from {segment.start} to {segment.end} s; it must "
                f"start at 0 or later and end after it starts"
            )
        if segment.start < reached - EPS:
            raise InvalidReview(
                f"segment {index} starts at {segment.start} s, inside the segment before it, which "
                f"ends at {reached} s"
            )
        reached = segment.end


def save_review(transcript_id: int, document: ReviewDocument) -> ReviewDocument:
    """Save the page's review in place of the last one, whole or not at all.

    Under the lock edit-list saves take, so it is never written under a
    transcript's name while a run is moving that transcript's files to another
    (dsj/ui/jobs.py, keep_earlier_roman_run).

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        InvalidReview: a segment is broken, named; nothing is written.
    """
    _check(document)
    with edits.WRITING:
        path = review_path(_transcript(transcript_id).json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, document.model_dump_json(), fsync=True)
    return document


def _segment_of(entry: hatao.Item, segments: Sequence[ReviewSegment], ends: list[float]) -> int:
    """The segment a word belongs to: the one it overlaps most, else the nearest one.

    So every word lands in exactly one segment, whatever its times: a word that
    starts a little before its sentence's span still belongs to that sentence.
    """
    a, b = entry.source_start, entry.source_end
    first = bisect_right(ends, a + EPS)  # the first segment ending after the word starts
    best, most = -1, 0.0
    k = first
    while k < len(segments) and segments[k].start < b - EPS:
        overlap = min(b, segments[k].end) - max(a, segments[k].start)
        if overlap > most:
            best, most = k, overlap
        k += 1
    if best >= 0:
        return best

    def gap(k: int) -> float:
        return max(segments[k].start - b, a - segments[k].end, 0.0)

    return min((k for k in (first - 1, first) if 0 <= k < len(segments)), key=gap)


def _texts(
    content: Sequence[hatao.Entry], segments: Sequence[ReviewSegment]
) -> list[tuple[str, str | None]]:
    """Each segment's words, in the list's order, and the label of who says its first word.

    Each word is placed by a binary search over the segments' ends, so a 2.5 h
    call's 1,500 sentences cost a few comparisons a word.
    """
    out: list[tuple[str, str | None]] = [("", None) for _ in segments]
    if not segments:
        return out
    started = [False] * len(segments)
    ends = [s.end for s in segments]
    speaker: str | None = None
    for entry in content:
        if isinstance(entry, hatao.Paragraph):
            speaker = entry.speaker
            continue
        if not entry.text:
            continue
        k = _segment_of(entry, segments, ends)
        text, who = out[k]
        out[k] = (text + entry.text, who if started[k] else speaker)
        started[k] = True
    return out


def _plain(segments: list[dict[str, Any]]) -> str:
    """The answer key as text: one line a sentence, `[m:ss] Name: words (flags)`."""
    lines: list[str] = []
    for s in segments:
        who = f"{s['speaker']}: " if s["speaker"] else ""
        flags = cast("list[str]", s["flags"])
        said = f" ({', '.join(_FLAG_WORDS[f] for f in flags)})" if flags else ""
        unchecked = "" if s["checked"] else " [not checked]"
        lines.append(f"[{clock(float(s['start']))}] {who}{s['text']}{said}{unchecked}")
    return "\n".join(lines) + "\n"


_MADE_AGAIN = (
    "The transcript was made again after this review was checked, so its checks are of "
    "words the transcript no longer has. Open Review, which re-checks the sentences by their "
    "span and says how many need checking again, then save the answer key."
)


def _keep_earlier(as_json: Path, as_text: Path) -> None:
    """Move a complete answer key out of the way of a partial one, under a numbered name.

    A partial key written over a complete one would lose the finished pass. A
    key that cannot be read is kept too: nobody can say it was not complete.
    """
    if not as_json.is_file():
        return
    try:
        complete = cast("dict[str, Any]", json.loads(as_json.read_text(encoding="utf-8")))[
            "complete"
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log.warning("the answer key %s could not be read, so it is kept: %s", as_json, exc)
        complete = True
    if complete is not True:
        return
    stem = as_json.name.removesuffix(".json")
    n = 2
    while (as_json.with_name(f"{stem}-{n}.json")).exists() or (
        as_text.with_name(f"{stem}-{n}.txt")
    ).exists():
        n += 1
    as_json.replace(as_json.with_name(f"{stem}-{n}.json"))
    if as_text.is_file():
        as_text.replace(as_text.with_name(f"{stem}-{n}.txt"))
    _log.warning("kept the earlier complete answer key as %s-%d.json", stem, n)


def reference(transcript_id: int, *, allow_partial: bool = False) -> ReferenceWritten:
    """Write the review as the transcript's answer key, beside the transcript JSON.

    Refused, before the edit list is opened, when the review was checked
    against a transcript since made again: its checks vouch for other words,
    and `allow_partial` does not change that. A partial key never writes over
    a complete one: that is kept under a numbered name. The JSON and the text
    are written together (dsj.atomic.atomic_write_texts).

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        InvalidReview: the saved review cannot be read, named.
        dsj.ui.edits.TranscriptChanged: the review was checked against an
            earlier version of the transcript.
        ReviewIncomplete: there is no review, or sentences are unchecked and
            `allow_partial` is not set; it says how many.
    """
    document, digest = read_review(transcript_id)
    if document is None:
        raise ReviewIncomplete(
            "This transcript has no review yet. Open Review, check its sentences, then save "
            "the answer key."
        )
    if document.transcript_sha != digest:
        raise TranscriptChanged(_MADE_AGAIN)
    total = len(document.segments)
    unchecked = sum(1 for s in document.segments if s.state != "checked")
    if unchecked and not allow_partial:
        raise ReviewIncomplete(
            f"{unchecked} of {total} sentences are not checked yet. Finish the pass, or save "
            f"a partial answer key, which says it is partial."
        )
    opened = edits.open_edits(transcript_id)
    if opened.transcript_sha != document.transcript_sha:
        # Made again in the moment between the two reads.
        raise TranscriptChanged(_MADE_AGAIN)
    labels = edits.labels_of(opened)
    row = _transcript(transcript_id)
    segments = [
        {
            "start": s.start,
            "end": s.end,
            "speaker": edits.display_name(who, labels, opened.doc.names),
            "label": who,
            "text": text.strip(),
            "flags": list(s.flags),
            "checked": s.state == "checked",
        }
        for s, (text, who) in zip(
            document.segments, _texts(opened.doc.content, document.segments), strict=True
        )
    ]
    key = {
        "format": "dsj-reference",
        "version": 1,
        "transcript": row.json_path.name,
        "engine": row.engine,
        "model": row.model,
        "reviewed_against": document.transcript_sha,
        "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "complete": unchecked == 0,
        "segments": segments,
    }
    as_json = row.json_path.with_name(f"{row.json_path.stem}.reference.json")
    as_text = row.json_path.with_name(f"{row.json_path.stem}.reference.txt")
    if unchecked:
        _keep_earlier(as_json, as_text)
    text = json.dumps(key, ensure_ascii=False, indent=1)
    atomic_write_texts([(as_json, text), (as_text, _plain(segments))], fsync=True)
    return ReferenceWritten(files=[as_json.name, as_text.name], segments=total, unchecked=unchecked)
