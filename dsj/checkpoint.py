"""Persist a partially merged transcript so an interrupted run can continue.

The file sits beside the output rather than inside the status heartbeat. The
heartbeat is advisory and optional (`--status`); this is load-bearing for
correctness and keyed to the required `--out`. They also want different
durability -- see atomic_write_text's fsync argument.
"""

from __future__ import annotations

__all__ = [
    "SCHEMA",
    "Fingerprint",
    "checkpoint_path_for",
    "fingerprint",
    "read_checkpoint",
    "write_checkpoint",
]

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError

from dsj.alignment import AlignedToken
from dsj.atomic import atomic_write_text
from dsj.identity import content_id

# 2 since #118, when the recording stopped being named by its path, size and
# mtime and started being named by content_id. A schema 1 checkpoint cannot
# match, so a run interrupted before the upgrade starts over once, and the
# message it prints says that is why.
SCHEMA = 2


@dataclass(frozen=True)
class Fingerprint:
    """Everything that, if it changed, makes the stored tokens wrong to reuse.

    Reusing a checkpoint across any of these produces a transcript that is
    wrong without looking wrong, so the check is exact equality of the whole
    record rather than a heuristic on a few fields.

    `engine_fields` is the engine's own contribution (dsj.parakeet supplies
    `{"parakeet_version": ...}`), and it is why cross-engine reuse is
    impossible without a version bump: two engines contribute different KEY
    SETS, so their serialized fingerprints can never be equal even where every
    shared value collides. Stronger than comparing an engine-name value, and
    free.

    The recording is named by `content_id`, its bytes, and not by where it
    sits. The path and the mtime used to be in this record, so renaming,
    moving or plainly copying a recording between two runs threw its resume
    away without a word (#118). `media` still travels with the record, as a
    note for a person reading a stray checkpoint, and takes no part in the
    match: it is excluded from equality here and from `to_dict()`.
    """

    schema: int
    content_id: str
    total_samples: int
    model_id: str
    chunk_s: float
    overlap_s: float
    engine_fields: dict[str, str]
    media: str = dataclasses.field(compare=False)

    def to_dict(self) -> dict[str, Any]:
        """The comparable, serializable form. Engine keys merge FLAT.

        Flat because that is how every checkpoint dsj has written stores them:
        `parakeet_version` started life as a dataclass field of its own, and
        nesting the engine's keys now would change the bytes for nothing.
        tests/test_checkpoint_golden.py holds this shape against a checkpoint
        written by the code that introduced it, so a refactor cannot move it
        without a test saying so.
        """
        return {
            k: v
            for k, v in dataclasses.asdict(self).items()
            if k not in ("engine_fields", "media")
        } | self.engine_fields


def fingerprint(
    media: Path,
    total_samples: int,
    model_id: str,
    chunk_s: float,
    overlap_s: float,
    engine_fields: dict[str, str],
) -> Fingerprint:
    """Describe the run precisely enough that a stale checkpoint cannot match.

    Keyed on the SOURCE media -- the file the user handed us -- and never on
    the audio actually fed to the model. A .mov is extracted to a fresh temp
    wav on every run, so keying on that would tie resume to ffmpeg decoding
    the same bytes every time, rather than to the recording the user named.

    By content, not by path or mtime (#118): content_id reads the size and
    the first and last MiB, so a renamed, moved or copied recording still
    resumes and an edited one does not. mtime used to be here to catch an edit
    in place; the content id catches that, and mtime is also what a plain `cp`
    changes. What the content id cannot see is an edit confined to the middle
    of a file that keeps its size exactly; dsj/identity.py says why that is
    accepted.

    `total_samples` is included even though the content id already covers most
    edits: it is the only field that catches an ffmpeg upgrade decoding the
    same untouched file to a different length, which would silently shift every
    chunk boundary.

    `engine_fields` comes from the engine module's fingerprint_fields() --
    the caller does not invent it, because the engine knows what invalidates
    its own tokens (for parakeet: the vendored merge functions' ancestry).
    """
    return Fingerprint(
        schema=SCHEMA,
        content_id=content_id(media),
        total_samples=total_samples,
        model_id=model_id,
        chunk_s=chunk_s,
        overlap_s=overlap_s,
        engine_fields=engine_fields,
        media=str(media.resolve()),
    )


def checkpoint_path_for(out: Path) -> Path:
    """Return the checkpoint path that sits beside `out`.

    A sibling of the output rather than a temp-dir entry: a resume has to find
    it on a later run, in a later process, with no shared state but the path.
    """
    return out.with_name(out.name + ".ckpt")


def _to_json(token: AlignedToken) -> dict[str, Any]:
    # `end` is omitted deliberately: AlignedToken.__post_init__ recomputes it
    # from start + duration, so persisting it would only add a way to disagree.
    return {
        "id": token.id,
        "text": token.text,
        "start": token.start,
        "duration": token.duration,
        "confidence": token.confidence,
    }


def write_checkpoint(
    path: Path, fp: Fingerprint, next_start: int, tokens: list[AlignedToken]
) -> None:
    """Record the merged tokens and the sample index to resume from.

    The whole token list is rewritten each time rather than appended to. That
    is quadratic in chunk count, but a 74-minute file is ~43 chunks and a few
    megabytes; an append log would buy nothing and cost a recovery path.
    """
    payload = {
        # Beside the fingerprint, not in it: which file this run read, for a
        # person, never compared (#118).
        "media": fp.media,
        "fingerprint": fp.to_dict(),
        "next_start": next_start,
        "tokens": [_to_json(t) for t in tokens],
    }
    # fsync here, unlike the heartbeat: losing this costs minutes of GPU time,
    # and one fsync per ~105 seconds of audio is free.
    atomic_write_text(path, json.dumps(payload), fsync=True)


class _TokenDoc(BaseModel):
    """One token as it appears on disk.

    NOT strict. Strict mode rejects a JSON int where a float is declared, and
    AlignedToken is a plain dataclass with no coercion -- so a token whose
    duration or confidence happened to serialise as a bare integer would make
    read_checkpoint return None and silently re-transcribe a resumable run.
    "Resume just stopped working" with no error is the exact failure class this
    validation exists to close, so the numerics stay lax and the strictness
    goes where the real bug is: next_start, below.
    """

    id: int
    text: str
    start: float
    duration: float
    confidence: float


class _CheckpointDoc(BaseModel):
    """The checkpoint document, validated because a previous PROCESS wrote it.

    This is the one trust boundary in dsj that reads bytes it did not
    produce in this run. Everything else here is internal and belongs to the
    type checker.

    `next_start` is strict: it is an index into an audio buffer, and the string
    "44" survived the old `except (KeyError, TypeError)` net all the way to
    transcribe.py, where `skip_before / rate` raised TypeError. Loud, but at
    the wrong layer and only on the CLI's progress path -- a library caller
    with a different path could carry it further.

    `fingerprint` is `dict[str, Any]`: it is compared for exact equality
    against a freshly built one before this model is ever constructed, so
    validating its fields would restate the check that already happened.
    """

    model_config = ConfigDict(strict=False)

    fingerprint: dict[str, Any]
    next_start: StrictInt
    tokens: list[_TokenDoc]


# What each fingerprint key means, in the words a rejected checkpoint prints.
# Every other key is an engine's own, from its fingerprint_fields().
_WHAT_CHANGED = {
    "content_id": "the recording's contents changed",
    "total_samples": "the audio decoded to a different length",
    "model_id": "the model changed",
    "chunk_s": "the chunk length changed",
    "overlap_s": "the chunk overlap changed",
}
_ENGINE_CHANGED = "the engine or its version changed"
_UNREADABLE = "the file is not a checkpoint this dsj can read"


def _mismatch(stored: dict[str, Any], expected: dict[str, Any]) -> str | None:
    """Say which part of a stored fingerprint differs from this run's, or None.

    The field is named as well as described, because what the user does next
    depends on which it was: a changed --model is deliberate, an edited
    recording may not be.
    """
    if stored == expected:
        return None
    if stored.get("schema") != expected["schema"]:
        # Every other key may differ too, and listing them would bury the one
        # fact that matters: the file predates, or postdates, this format.
        return (
            f"it was written by another version of dsj, checkpoint schema "
            f"{stored.get('schema')} where this one reads {expected['schema']} (schema)"
        )
    changed: dict[str, list[str]] = {}
    for key in [*expected, *(k for k in stored if k not in expected)]:
        if key not in stored or key not in expected or stored[key] != expected[key]:
            changed.setdefault(_WHAT_CHANGED.get(key, _ENGINE_CHANGED), []).append(key)
    return "; ".join(f"{what} ({', '.join(keys)})" for what, keys in changed.items())


def _load(path: Path, fp: Fingerprint) -> tuple[int, list[AlignedToken]] | str | None:
    """The checkpoint's contents, the reason it cannot be used, or None if absent."""
    try:
        raw: object = json.loads(path.read_text())
    except FileNotFoundError:
        # No checkpoint is the normal case for a first run, not a rejection.
        return None
    except (OSError, json.JSONDecodeError):
        return _UNREADABLE

    if not isinstance(raw, dict):
        return _UNREADABLE
    # The guard above proves it is a dict but says nothing about key/value
    # types; JSON object keys are always str, and the values stay Any because
    # the shape check happens below, in the try.
    payload = cast("dict[str, Any]", raw)

    stored: object = payload.get("fingerprint")
    if not isinstance(stored, dict):
        return _UNREADABLE
    reason = _mismatch(cast("dict[str, Any]", stored), fp.to_dict())
    if reason is not None:
        return reason

    try:
        doc = _CheckpointDoc.model_validate(payload)
    except ValidationError:
        # Well-formed JSON with the right fingerprint but the wrong shape means
        # something wrote this file that was not us. Do not guess.
        return _UNREADABLE

    return doc.next_start, [
        AlignedToken(id=t.id, text=t.text, start=t.start, duration=t.duration,
                     confidence=t.confidence)
        for t in doc.tokens
    ]


def read_checkpoint(
    path: Path, fp: Fingerprint, on_reject: Callable[[str], None] | None = None
) -> tuple[int, list[AlignedToken]] | None:
    """Return `(next_start, tokens)` if the checkpoint matches, else None.

    A mismatch is not an error. A changed model or a re-encoded source just
    means the stored tokens describe something else; the caller starts over.

    It is not the same as having no checkpoint, though, and until #118 the two
    looked identical: a rename cost a whole transcription and printed nothing.
    So when a checkpoint exists and is not used, `on_reject` gets one clause
    saying why, naming the fingerprint field that failed. A missing file is
    not a rejection and reports nothing.
    """
    found = _load(path, fp)
    if isinstance(found, str):
        if on_reject is not None:
            on_reject(found)
        return None
    return found
