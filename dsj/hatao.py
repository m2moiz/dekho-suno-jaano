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

Finding what to bleep (#64) is a word list and a matcher over the same list. The
shipped lists are data in `dsj/words/`, one TOML file a language, inside the
package so `uv tool install` carries them; the user's additions live in a file of
their own in dsj's data folder, which no reinstall touches. A match is a flag,
and a flag is a `mute` of the word's entries, so a later detector (filler words,
hallucinations) is the same operation with another list.

Matching is exact, one word at a time, after folding case, punctuation and
script variants, never by edit distance. Roman Urdu has no fixed spelling, so
each entry lists the spellings recognisers choose between. Edit distance 1 was
the alternative, and on the short words these lists hold it reaches ordinary
words: measured on a 45 s parakeet transcript of English speech (202 tokens, 114
words), 6 of its words sit within distance 1 of a listed spelling and 0 match
exactly, every one of the 6 an ordinary word. A missed spelling is fixed by one
line in the user file; a false mute is found by the person you sent the file to.
"""

from __future__ import annotations

__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "PAD_S",
    "RECALL",
    "SHIPPED_LISTS",
    "WORDS_ENV",
    "Document",
    "Entry",
    "Found",
    "InvalidDocument",
    "Item",
    "Match",
    "Paragraph",
    "RenderRefused",
    "Rendered",
    "TranscriptUnusable",
    "WordList",
    "WordListError",
    "delete",
    "dumps",
    "find",
    "flag",
    "from_transcript",
    "load",
    "load_words",
    "loads",
    "move",
    "mute",
    "normalize",
    "recall_line",
    "render",
    "save",
    "spans_to_mute",
    "user_words_path",
    "validate",
    "word_lists",
]

import json
import math
import os
import re
import sys
import tomllib
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from dsj import filetag
from dsj import media as media_mod
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


# --------------------------------------------------------------------------
# Finding the words to bleep (#64)
# --------------------------------------------------------------------------

# The shipped lists, in the order a spelling found in two of them is credited:
# ur before hi, since the two share most Roman spellings and this tool's Hindi
# and Urdu speakers are mostly Urdu speakers.
SHIPPED_LISTS = ("en", "ur", "hi", "pa")
_WORDS_DIR = Path(__file__).parent / "words"

# Names the user's own list, in place of the default below. Tests point it at a
# temp file, so the suite never reads or writes the owner's list.
WORDS_ENV = "DSJ_WORDS"

# The keys an entry may carry. Anything else is a typo, and a typo'd key would
# otherwise drop its spellings in silence.
_SPELLING_KEYS = ("roman", "script", "disguised")

# Arabic-script letters a recogniser or a keyboard writes for their Urdu forms,
# which look the same and compare different: Arabic yeh, alef maksura, kaf, heh
# and teh marbuta, each to the letter Urdu uses.
_FOLD = str.maketrans({"\u064a": "\u06cc", "\u0649": "\u06cc", "\u0643": "\u06a9",
                       "\u0647": "\u06c1", "\u0629": "\u06c1"})
# Arabic short-vowel marks (harakat) and the superscript alef: optional in
# written Urdu, so one word arrives with or without them.
_HARAKAT = re.compile("[\u064b-\u065f\u0670]")


class WordListError(ValueError):
    """A word list file is broken. The message names the file and the entry."""


def user_words_path() -> Path:
    """The user's own word list: `$DSJ_WORDS`, else `words.toml` in dsj's data folder.

    The same folder the library uses (`dsj/ui/store.py`, `library_path`), worked out
    here rather than imported because `dsj hatao` imports nothing from `dsj.ui`;
    a test holds the two equal. Outside the package, so reinstalling dsj never
    touches it.
    """
    configured = os.environ.get(WORDS_ENV)
    if configured:
        return Path(configured)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dsj" / "words.toml"
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "dsj" / "words.toml"


def word_lists() -> list[Path]:
    """Every list a run searches: the shipped ones, then the user's if it exists."""
    user = user_words_path()
    return [_WORDS_DIR / f"{name}.toml" for name in SHIPPED_LISTS] + (
        [user] if user.is_file() else []
    )


def normalize(word: str) -> str:
    """The form a spelling is compared in: one recogniser's word, or one list entry.

    NFKC, case folded, the Urdu letter variants folded, Arabic short vowels
    dropped, and every character that is not a letter, a mark or a digit dropped:
    "Bhen-chod," and "bhenchod" compare equal. The asterisk is kept, because a
    recogniser that masks a word writes "f***ing", and that is a spelling to
    match, not punctuation.
    """
    folded = _HARAKAT.sub("", unicodedata.normalize("NFKC", word).casefold().translate(_FOLD))
    return "".join(
        ch for ch in folded if ch == "*" or unicodedata.category(ch)[0] in ("L", "M", "N")
    )


@dataclass(frozen=True)
class WordList:
    """Normalised spellings, each to the entry it belongs to, and the files read."""

    spellings: Mapping[str, str]
    files: tuple[Path, ...]


def load_words(paths: Sequence[Path]) -> WordList:
    """Read word list files into one lookup, earlier files winning a shared spelling.

    An entry is credited as `<list>:<name>`, the list being the file's stem for a
    shipped list and `user` for the user's own, so the bleep log can say which.

    Raises:
        WordListError: a file that is not TOML, or an entry with no name, no
            spellings, a key it does not know, or a spelling that is all
            punctuation, named with its file.
    """
    spellings: dict[str, str] = {}
    for path in paths:
        label = path.stem if path.parent == _WORDS_DIR else "user"
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise WordListError(f"{path} is not valid TOML: {exc}") from exc
        entries = raw.get("entry", [])
        if not isinstance(entries, list):
            raise WordListError(f"{path}: `entry` must be a list of [[entry]] tables")
        for index, item in enumerate(cast("list[Any]", entries)):
            where = f"{path}, entry {index}"
            if not isinstance(item, dict):
                raise WordListError(f"{where} is not a table")
            fields = cast("dict[str, Any]", item)
            name = fields.get("name")
            if not isinstance(name, str) or not name:
                raise WordListError(f"{where} has no `name`")
            unknown = sorted(set(fields) - {"name", *_SPELLING_KEYS})
            if unknown:
                raise WordListError(
                    f"{where} ({name}) has keys {unknown}; an entry takes `name` and "
                    f"any of {list(_SPELLING_KEYS)}"
                )
            found = [
                spelling
                for key in _SPELLING_KEYS
                for spelling in cast("list[Any]", fields.get(key, []))
            ]
            if not found or not all(isinstance(x, str) for x in found):
                raise WordListError(f"{where} ({name}) needs at least one spelling, all strings")
            for spelling in cast("list[str]", found):
                key = normalize(spelling)
                if not key:
                    raise WordListError(f"{where} ({name}): {spelling!r} is all punctuation")
                spellings.setdefault(key, f"{label}:{name}")
    return WordList(spellings, tuple(paths))


@dataclass(frozen=True)
class Match:
    """One word a list matched: its entries in the document, its time, what matched it."""

    start: int
    stop: int
    word: str
    entry: str
    source_start: float
    source_end: float


@dataclass(frozen=True)
class Found:
    """What a search found, and what it searched: zero is a result to report."""

    matches: tuple[Match, ...]
    words_searched: int
    lists: tuple[Path, ...]

    @property
    def count(self) -> int:
        """How many words matched. The caller says so out loud when it is 0."""
        return len(self.matches)


def _words(doc: Document) -> Iterator[tuple[int, int]]:
    """Each word as the range of entries it spans.

    A word starts at an item whose text starts with a space, or the first one in
    a paragraph, and runs through the items with text after it: parakeet and
    sherpa write a word in pieces (" questi", "on") and a full stop as a piece of
    its own. A gap item between two pieces stays inside the word.
    """
    start: int | None = None
    last = 0
    for index, entry in enumerate(doc.content):
        if isinstance(entry, Paragraph):
            if start is not None:
                yield start, last + 1
            start = None
            continue
        if not entry.text:
            continue
        if start is None or entry.text[0].isspace():
            if start is not None:
                yield start, last + 1
            start = index
        last = index
    if start is not None:
        yield start, last + 1


def find(doc: Document, words: WordList) -> Found:
    """Every word of `doc` a list spells, one word at a time, never one language at a time.

    One sentence routinely mixes Urdu and English, so every word is looked up in
    every list.
    """
    matches: list[Match] = []
    searched = 0
    for start, stop in _words(doc):
        searched += 1
        pieces = [e for e in doc.content[start:stop] if isinstance(e, Item) and e.text]
        written = "".join(piece.text for piece in pieces).strip()
        entry = words.spellings.get(normalize(written))
        if entry is not None:
            matches.append(
                Match(
                    start=start,
                    stop=stop,
                    word=written,
                    entry=entry,
                    source_start=min(piece.source_start for piece in pieces),
                    source_end=max(piece.source_end for piece in pieces),
                )
            )
    return Found(tuple(matches), searched, words.files)


def flag(doc: Document, found: Found) -> Document:
    """Mute every word `found` matched."""
    for match in found.matches:
        doc = mute(doc, match.start, match.stop)
    return doc


# --------------------------------------------------------------------------
# Rendering the bleeped file (#65)
# --------------------------------------------------------------------------

# How far a mute reaches past each side of a flagged word, in seconds. The 0.1
# is #44's starting guess, and it has not been chosen by ear yet: the owner's
# listening check at the timestamps a render logs decides it. What has been
# measured is the cost. In fluent speech words abut: on the parakeet transcript
# of scratch/clip45.wav (114 words), 84 of 113 word boundaries have no gap at
# all, and a pad of 0.05 s reaches into the next or previous word at 90 of them,
# 0.1 s at 97. So any pad shaves the edge of a neighbouring word; without one,
# the edge of the flagged word can be heard, since parakeet times words on an
# 80 ms grid and whisper only infers its ends. A zero-length word (e == t) is
# muted by its pad alone.
PAD_S = 0.1

# How often each engine leaves a swear word out of its transcript, once #152 has
# measured it, as the sentence `dsj hatao` prints for that engine. Empty until
# then, and every engine reads "unmeasured": a word the recogniser never wrote
# down cannot be matched or muted, and a run that muted nothing it heard is not
# allowed to look like a clean recording (#44).
RECALL: dict[str, str] = {}


def recall_line(engine: str) -> str:
    """The one line `dsj hatao` prints about what `engine` may have missed."""
    measured = RECALL.get(engine)
    if measured is not None:
        return f"recall: {engine} {measured}"
    return (
        f"recall: how often {engine} leaves a swear word out of its transcript is unmeasured "
        f"(#152); a word it never wrote down was not muted"
    )


# Two items closer than this are one stretch of the recording, not a cut: the
# times are rounded to the millisecond and summed.
_TOUCH_S = 0.002


class RenderRefused(ValueError):
    """The document holds a change the render does not make, or another recording."""


def spans_to_mute(
    doc: Document, *, duration_s: float, pad_s: float = PAD_S
) -> list[tuple[float, float]]:
    """The stretches of the recording to silence: muted items, padded, merged, in order.

    The render mutes and does nothing else (#128: no cut, no trim, no re-timing),
    so the document must still play its one recording from the start in order.
    A deleted or moved entry would be rendered as though it were not, which is
    the silent wrong answer, so it is refused instead.

    Raises:
        RenderRefused: more than one source, or entries out of order or missing.
    """
    sources = {entry.source for entry in doc.content if isinstance(entry, Item)}
    if len(sources) > 1:
        raise RenderRefused(
            f"the document plays from {len(sources)} recordings; a render mutes one"
        )
    reached = 0.0
    previous = 0.0
    spans: list[tuple[float, float]] = []
    for index, entry in enumerate(doc.content):
        if not isinstance(entry, Item):
            continue
        if entry.source_start < previous or entry.source_start > reached + _TOUCH_S:
            raise RenderRefused(
                f"{_where(index, entry)} does not follow the entry before it in the "
                f"recording, so something was deleted or moved; a render only mutes"
            )
        previous = entry.source_start
        reached = max(reached, entry.source_end)
        if not entry.muted:
            continue
        start = max(entry.source_start - pad_s, 0.0)
        end = min(entry.source_end + pad_s, duration_s)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    return [(round(a, 3), round(b, 3)) for a, b in spans if b > a]


@dataclass(frozen=True)
class Rendered:
    """What a render did: the spans it silenced, and why its source tag is missing, if it is."""

    spans: list[tuple[float, float]]
    untagged: str | None


def render(
    doc: Document,
    media: Path,
    out: Path,
    *,
    replace: bool = False,
    on_progress: Callable[[float, float], None] | None = None,
) -> Rendered:
    """Write `media` to `out` with every muted item of `doc` silenced (#65).

    The one render, for `dsj hatao` and for the app alike. `media` must be the
    recording the document plays from: a document made for one recording and
    rendered onto another would mute the wrong moments, in silence.
    `on_progress` is called with seconds written and the recording's length.

    The finished file is stamped with its source's content id (#121,
    dsj.filetag.stamp_source), so a copy that leaves this folder can still say
    which recording it came from.

    Raises:
        RenderRefused: `media` is not the document's recording, or the document
            holds a delete or a move.
        and whatever dsj.media.mute raises.
    """
    recordings = {Path(doc.sources[e.source]) for e in doc.content if isinstance(e, Item)}
    if recordings and recordings != {media.resolve()}:
        raise RenderRefused(
            f"the document plays {sorted(map(str, recordings))}, not {media.resolve()}"
        )
    total = media_mod.probe(media).duration_s
    spans = spans_to_mute(doc, duration_s=total)
    media_mod.mute(
        media,
        spans,
        out,
        replace=replace,
        on_progress=(lambda done: on_progress(done, total)) if on_progress else None,
    )
    return Rendered(spans, filetag.stamp_source(media, out))
