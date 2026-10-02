"""What a recording contains after your changes: the edit list behind bleeping (#63).

Named for the command it serves, `dsj hatao` (#153), the way `dsj/suno.py` and
`dsj/dekho.py` are named for theirs. #44 first called this module `saaf.py`, before
the command had a name.

The document is a list of entries. A `Paragraph` opens a run of words and says who
spoke it and in which language; an `Item` says where its audio comes from (a
source, a start in that source, a length) and what text it carries. Audio between
words is an item too, with no text, so walking the list from the top plays the
recording from its start. Playing or exporting means walking that list; the
recording itself is never written to.

There are exactly three kinds of change, and each is data:

    mute(doc, start, stop)          silence entries [start, stop); muted=False undoes it
    delete(doc, start, stop)        take them out of the list
    move(doc, start, stop, to)      put them before entry `to`

Un-flagging a word is one `mute(..., muted=False)`: the audio comes back with no
re-render of anything else, because nothing else changed. The scope stops at those
three on purpose. The team whose design this follows (audapolis) dropped the whole
layer in their next project, because media editing is expensive to keep alive.
The undo for each kind is #66's, in the app.

Every change ends in `validate`, as loading does, so a broken list fails at the
change that broke it and the message names the entry.
"""

from __future__ import annotations

__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "Document",
    "Entry",
    "InvalidDocument",
    "Item",
    "Paragraph",
    "TranscriptUnusable",
    "delete",
    "dumps",
    "from_transcript",
    "load",
    "loads",
    "move",
    "mute",
    "save",
    "validate",
]

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from dsj.atomic import atomic_write_text

# The file says what it is and which shape it has. A reader meeting a version it
# does not know refuses by name rather than guessing; when version 2 exists, its
# loader turns a version 1 file into a version 2 one before validating it.
FORMAT = "dsj-edits"
FORMAT_VERSION = 1

# A BCP 47 tag's shape, loosely: a 2 or 3 letter language, then subtags ("ur",
# "pa-Guru", "en-GB"). Enough to reject a full language name or a stray space,
# which is what a hand-edited file gets wrong.
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")


class InvalidDocument(ValueError):
    """The entry list is broken. The message names the entry and what is wrong with it."""


class TranscriptUnusable(ValueError):
    """The transcript cannot be turned into a document without guessing."""


@dataclass(frozen=True)
class Paragraph:
    """Opens a run of items: who spoke it and in which language, both optional.

    `language` is per paragraph rather than per document because one recording
    switches language halfway (#33, #79), and adding it later would have cost the
    file format a migration (#86).
    """

    speaker: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class Item:
    """A stretch of one source's audio, and the text said in it ("" for none)."""

    source: str
    source_start: float
    length: float
    text: str
    muted: bool = False

    @property
    def source_end(self) -> float:
        """Where the stretch ends in its source, in seconds."""
        return self.source_start + self.length


type Entry = Paragraph | Item


@dataclass(frozen=True)
class Document:
    """Sources by id, each an absolute path, and the entries that play from them."""

    sources: Mapping[str, str]
    content: tuple[Entry, ...]


def _where(index: int, entry: Entry) -> str:
    if isinstance(entry, Paragraph):
        return f"entry {index} (paragraph, speaker {entry.speaker!r})"
    return (
        f"entry {index} (item {entry.text!r} at {entry.source_start:g} s "
        f"of source {entry.source!r})"
    )


def validate(doc: Document) -> Document:
    """Return `doc` unchanged, or raise naming the first entry that is wrong.

    Checked after every change, not only on load: a change that leaves the list
    broken is found at that change, not at the save that comes much later (#86).

    Raises:
        InvalidDocument: naming the entry and what is wrong with it.
    """
    for key, path in doc.sources.items():
        if not key or not path:
            raise InvalidDocument(f"source {key!r} has no path; every source names a file")
    for index, entry in enumerate(doc.content):
        if isinstance(entry, Paragraph):
            if entry.language is not None and not _LANGUAGE.match(entry.language):
                raise InvalidDocument(
                    f"{_where(index, entry)}: language {entry.language!r} is not a "
                    f"language tag such as 'ur' or 'en-GB'; use null when it is unknown"
                )
            continue
        if index == 0:
            raise InvalidDocument(f"{_where(index, entry)}: the list must open with a paragraph")
        if entry.source not in doc.sources:
            raise InvalidDocument(
                f"{_where(index, entry)}: no such source; the document has {sorted(doc.sources)}"
            )
        for name, value in (("start", entry.source_start), ("length", entry.length)):
            if not math.isfinite(value) or value < 0:
                raise InvalidDocument(
                    f"{_where(index, entry)}: {name} is {value}; it must be a "
                    f"finite number of seconds, 0 or more"
                )
    return doc


def from_transcript(
    payload: Mapping[str, Any],
    media: Path,
    *,
    duration_s: float | None = None,
    language: str | None = None,
) -> Document:
    """Build the untouched document of `media` from a transcript `dsj suno` wrote.

    One paragraph per sentence, one item per token, and an item with no text for
    every stretch of audio no token covers: before the first word, between words,
    across `unclear` stretches, and from the last word to `duration_s` when given.
    So the document plays the recording from its start, nothing muted.

    Each token's item runs from its `t` to its own `e` (#56, #77), never to the
    next token's `t`, which would swallow every pause into the word before it.
    A token's `e` can pass the next one's `t` where whisper inferred a long word,
    and each item keeps the times the transcript gave it, so two items can cover
    the same audio there. Gaps are measured from the furthest end so far, so no
    audio is listed twice as a pause.

    Raises:
        TranscriptUnusable: a token has no `e`, which transcripts written before
            v0.2.0 and caption imports lack, or tokens run backwards in time,
            which transcripts written before v0.2.3 can at a seam. Either way the
            only way on would be to guess where a word is.
    """
    source = "0"
    speakers = cast("list[str]", payload.get("speakers") or [])
    content: list[Entry] = []
    cursor = 0.0
    previous = 0.0

    def gap(until: float) -> None:
        if until > cursor:
            content.append(Item(source, cursor, round(until - cursor, 3), ""))

    sentences = cast("list[dict[str, Any]]", payload.get("sentences") or [])
    for s_index, sentence in enumerate(sentences):
        label = sentence.get("speaker")
        speaker = speakers[label] if isinstance(label, int) and label < len(speakers) else None
        content.append(Paragraph(speaker=speaker, language=language))
        for t_index, token in enumerate(cast("list[dict[str, Any]]", sentence["tokens"])):
            where = f"sentence {s_index}, token {t_index} (at {token['t']} s)"
            if "e" not in token:
                raise TranscriptUnusable(
                    f"{where} has no end time `e`, so where the word stops is unknown. "
                    f"Transcripts written before v0.2.0 and `dsj parho` imports lack it; "
                    f"transcribe the recording again with `dsj suno`."
                )
            start, end = float(token["t"]), float(token["e"])
            if start < previous:
                raise TranscriptUnusable(
                    f"{where} starts before the token ahead of it ({previous} s). "
                    f"Transcripts written before v0.2.3 can overlap at a seam; "
                    f"transcribe the recording again with `dsj suno`."
                )
            previous = start
            gap(start)
            content.append(Item(source, start, round(max(end - start, 0.0), 3), str(token["w"])))
            cursor = max(cursor, end)
    if duration_s is not None and duration_s > cursor:
        if not content:
            content.append(Paragraph(language=language))
        gap(duration_s)
    return validate(Document({source: str(media.resolve())}, tuple(content)))


def _check_range(doc: Document, start: int, stop: int) -> None:
    if not 0 <= start <= stop <= len(doc.content):
        raise IndexError(
            f"entries [{start}, {stop}) are not inside a document of {len(doc.content)} entries"
        )


def mute(doc: Document, start: int, stop: int, *, muted: bool = True) -> Document:
    """Silence entries [start, stop), or with `muted=False` give their audio back."""
    _check_range(doc, start, stop)
    content = tuple(
        replace(entry, muted=muted) if start <= i < stop and isinstance(entry, Item) else entry
        for i, entry in enumerate(doc.content)
    )
    return validate(Document(doc.sources, content))


def delete(doc: Document, start: int, stop: int) -> Document:
    """Take entries [start, stop) out of the list. The source keeps its audio."""
    _check_range(doc, start, stop)
    return validate(Document(doc.sources, doc.content[:start] + doc.content[stop:]))


def move(doc: Document, start: int, stop: int, to: int) -> Document:
    """Put entries [start, stop) before entry `to`, counted in the list as it is now."""
    _check_range(doc, start, stop)
    if start < to < stop or not 0 <= to <= len(doc.content):
        raise IndexError(f"cannot move entries [{start}, {stop}) to {to}")
    block = doc.content[start:stop]
    rest = doc.content[:start] + doc.content[stop:]
    at = to if to <= start else to - len(block)
    return validate(Document(doc.sources, rest[:at] + block + rest[at:]))


def _entry_json(entry: Entry) -> dict[str, Any]:
    if isinstance(entry, Paragraph):
        return {"kind": "paragraph", "speaker": entry.speaker, "language": entry.language}
    return {
        "kind": "item",
        "source": entry.source,
        "sourceStart": entry.source_start,
        "length": entry.length,
        "text": entry.text,
        "muted": entry.muted,
    }


def dumps(doc: Document) -> str:
    """The document as its versioned JSON file.

    Only sources an item still refers to are written (#86): a source that edits
    have taken out entirely does not ride along in every later save.
    """
    validate(doc)
    used = {entry.source for entry in doc.content if isinstance(entry, Item)}
    return json.dumps(
        {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "sources": {key: path for key, path in doc.sources.items() if key in used},
            "content": [_entry_json(entry) for entry in doc.content],
        },
        ensure_ascii=False,
    )


def _broken(index: int, name: str, kind: str, raw: Mapping[str, Any]) -> InvalidDocument:
    return InvalidDocument(f"entry {index}: `{name}` must be {kind}: {dict(raw)!r}")


def _seconds(index: int, raw: Mapping[str, Any], name: str) -> float:
    value = raw.get(name)
    # bool is an int to isinstance, and a `true` start time is a broken file.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _broken(index, name, "a number", raw)
    return float(value)


def _text(index: int, raw: Mapping[str, Any], name: str, *, nullable: bool = False) -> str | None:
    value = raw.get(name)
    if isinstance(value, str) or (nullable and value is None):
        return value
    raise _broken(index, name, "a string or null" if nullable else "a string", raw)


def _entry(index: int, raw: object) -> Entry:
    if not isinstance(raw, dict):
        raise InvalidDocument(f"entry {index} is not an object: {raw!r}")
    fields = cast("dict[str, Any]", raw)
    kind = fields.get("kind")
    if kind == "paragraph":
        return Paragraph(
            speaker=_text(index, fields, "speaker", nullable=True),
            language=_text(index, fields, "language", nullable=True),
        )
    if kind == "item":
        muted = fields.get("muted")
        if not isinstance(muted, bool):
            raise _broken(index, "muted", "true or false", fields)
        return Item(
            source=cast("str", _text(index, fields, "source")),
            source_start=_seconds(index, fields, "sourceStart"),
            length=_seconds(index, fields, "length"),
            text=cast("str", _text(index, fields, "text")),
            muted=muted,
        )
    raise InvalidDocument(f"entry {index} has kind {kind!r}; expected 'paragraph' or 'item'")


def loads(text: str) -> Document:
    """Read a document file's text back into the document it was saved from.

    Raises:
        InvalidDocument: not a dsj edit list, a version this dsj cannot read, or a
            broken entry, named.
    """
    raw: Any = json.loads(text)
    if not isinstance(raw, dict) or cast("dict[str, Any]", raw).get("format") != FORMAT:
        raise InvalidDocument(f'not a dsj edit list: no "format": {FORMAT!r} at its top')
    top = cast("dict[str, Any]", raw)
    version = top.get("version")
    if version != FORMAT_VERSION:
        raise InvalidDocument(
            f"edit list version {version!r}; this dsj reads version {FORMAT_VERSION}. "
            f"A newer version was written by a newer dsj: upgrade to open it."
        )
    sources = top.get("sources")
    content = top.get("content")
    if not isinstance(sources, dict) or not isinstance(content, list):
        raise InvalidDocument("an edit list needs a `sources` object and a `content` list")
    paths = cast("dict[Any, Any]", sources)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in paths.items()):
        raise InvalidDocument(f"every source must map an id to a path: {paths!r}")
    entries = tuple(_entry(i, entry) for i, entry in enumerate(cast("list[Any]", content)))
    return validate(Document(cast("dict[str, str]", paths), entries))


def save(doc: Document, path: Path) -> None:
    """Write the document to `path`, replacing it whole or not at all."""
    atomic_write_text(path, dumps(doc), fsync=True)


def load(path: Path) -> Document:
    """Read a document `save` wrote."""
    return loads(path.read_text(encoding="utf-8"))
