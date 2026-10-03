"""Adding a word to the user's own bleep list from the app (#84).

The list is #64's user file, `dsj.hatao.user_words_path()`: the one `dsj hatao`
reads in the terminal, so a word added in the app is muted by the terminal's
next run too. Its format is #64's, one `[[entry]]` table a word; this only ever
appends one, and never rewrites what the owner typed there by hand.

Plain Python, no fastapi: the route is dsj/ui/routes/marks.py.
"""

from __future__ import annotations

__all__ = ["Added", "add_word"]

import json
from dataclasses import dataclass

from dsj import hatao
from dsj.atomic import atomic_write_text


@dataclass(frozen=True)
class Added:
    """The entry a spelling now matches as, and whether this call wrote it."""

    entry: str
    added: bool


def _key(spelling: str) -> str:
    """`script` for a spelling in a non-Latin script, `roman` for one in Latin letters."""
    return "script" if any(ch.isalpha() and not ch.isascii() for ch in spelling) else "roman"


def add_word(spelling: str) -> Added:
    """Append `spelling` to the user's list as an entry of its own, unless a list has it already.

    The file is checked whole, with the entry in it, before it replaces the
    one on disk, so a spelling the lists cannot read never reaches the file.

    Raises:
        dsj.hatao.WordListError: a spelling with no letters or digits, or a
            user file that was already broken, named.
    """
    spelling = spelling.strip()
    if not hatao.normalize(spelling):
        raise hatao.WordListError(f"{spelling!r} has no letters or digits to match a word by")
    found = hatao.load_words(hatao.word_lists()).spellings.get(hatao.normalize(spelling))
    if found is not None:
        return Added(found, added=False)
    path = hatao.user_words_path()
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    # A JSON string is a TOML basic string: the same quotes and escapes.
    quoted = json.dumps(spelling, ensure_ascii=False)
    after = (
        before
        + ("\n" if before and not before.endswith("\n") else "")
        + f"\n[[entry]]\nname = {quoted}\n{_key(spelling)} = [{quoted}]\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, after, fsync=True)
    try:
        entry = hatao.load_words([path]).spellings[hatao.normalize(spelling)]
    except hatao.WordListError:
        atomic_write_text(path, before, fsync=True)
        raise
    return Added(entry, added=True)
