"""The app's own settings, kept between launches (#69), with versioned migrations (#131).

One JSON file beside the library, `settings.json`: what is about the whole
app and not about one recording. The first key is the Transcribe dialog's
last answer, so the next launch opens the dialog on it. What is about one
recording (where it was left playing) goes on that recording's row in the
library, never here and never beside a transcript. The theme is not here
either: it must be known before the first paint, so it stays in a cookie
(ui/src/features/theme/theme.ts).

The file carries a version number from its first commit. `_MIGRATIONS` is
the list that brings an older file up to date, one version at a time, each
step written to disk with its stamp as it lands: a crash between two steps
leaves a file the next boot resumes from, and a step is written so that
running it twice leaves what running it once did. The shape is vibe's
`desktop/src/lib/migrations/index.ts` (MIT), which the issue names.

A file a newer dsj wrote is refused, as the library refuses a newer schema,
rather than misread. Keys this dsj does not know are kept as read.
"""

from __future__ import annotations

__all__ = [
    "ANSWERS",
    "SETTINGS_VERSION",
    "Settings",
    "SettingsError",
    "read_settings",
    "settings_path",
    "write_settings",
]

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dsj.atomic import atomic_write_text
from dsj.ui.store import library_path

# Bumped by whoever changes what a key means or is called; _MIGRATIONS then
# carries the older file across. Version 1 is the two transcribe keys.
SETTINGS_VERSION = 1

# The Transcribe dialog's answers to "What's spoken?" (ui/src/features/transcribe/choices.ts).
ANSWERS = ("mixed", "urdu", "english", "unsure")

# What a finished transcription is also written as, beside its recording
# (#132): the formats dsj likho writes (dsj/likho.py EXPORTERS).
FORMATS = ("srt", "vtt", "txt")


class SettingsError(RuntimeError):
    """The settings file cannot be used as it is. Nothing in it has changed."""


@dataclass(frozen=True)
class Settings:
    """Every key the app keeps, typed, with the value a fresh install starts from."""

    # The dialog's last answer, so it opens on it next time (#69, #113).
    transcribe_answer: str = "mixed"
    # Whether the last run labelled speakers.
    transcribe_diarize: bool = True
    # The formats a finished transcription is also written as, beside its
    # recording (#132); none until turned on.
    export_formats: tuple[str, ...] = ()
    # Whether such an export writes over a file already there, or leaves it.
    export_overwrite: bool = False


Migration = Callable[[dict[str, Any]], dict[str, Any]]

# What each older version needs to become the next, keyed by the older one.
# Each step takes the file's contents and returns them changed; it must be
# safe to run twice on its own output (tests/test_settings_store.py holds
# the runner to that). Empty until the first key changes.
_MIGRATIONS: dict[int, Migration] = {}


def settings_path() -> Path:
    """Where the file lives: beside the library, so one `DSJ_LIBRARY` moves both."""
    return library_path().with_name("settings.json")


def _write(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(raw, indent=2, sort_keys=True) + "\n")


def _load(path: Path) -> dict[str, Any]:
    """The file's contents, migrated to this version and written back if that changed them."""
    if not path.exists():
        return {"version": SETTINGS_VERSION}
    try:
        raw: Any = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise SettingsError(f"{path} is not a settings file dsj can read ({exc}).") from exc
    if not isinstance(raw, dict):
        raise SettingsError(f"{path} is not a settings file dsj can read (not an object).")
    found: dict[str, Any] = dict(raw)  # pyright: ignore[reportUnknownArgumentType]
    version = found.get("version")
    if not isinstance(version, int) or version < 1:
        raise SettingsError(f"{path} carries no version number dsj can read ({version!r}).")
    if version > SETTINGS_VERSION:
        raise SettingsError(
            f"{path} was written by a newer dsj (settings version {version}; this dsj reads "
            f"up to {SETTINGS_VERSION}). Upgrade dsj, or move the file aside."
        )
    while version < SETTINGS_VERSION:
        found = _MIGRATIONS[version](found)
        version += 1
        found["version"] = version
        _write(path, found)
    return found


def _typed(raw: dict[str, Any]) -> Settings:
    """The known keys, each its own type, the default standing in for anything else."""
    answer = raw.get("transcribe_answer")
    diarize = raw.get("transcribe_diarize")
    formats: object = raw.get("export_formats")
    overwrite = raw.get("export_overwrite")
    listed: list[object] = list(formats) if isinstance(formats, list | tuple) else []  # pyright: ignore[reportUnknownArgumentType]
    return Settings(
        transcribe_answer=answer if isinstance(answer, str) and answer in ANSWERS else "mixed",
        transcribe_diarize=diarize if isinstance(diarize, bool) else True,
        export_formats=(
            tuple(f for f in listed if isinstance(f, str))
            if all(isinstance(f, str) and f in FORMATS for f in listed)
            else ()
        ),
        export_overwrite=overwrite if isinstance(overwrite, bool) else False,
    )


def read_settings() -> Settings:
    """What the app kept, or the defaults when nothing was kept yet."""
    return _typed(_load(settings_path()))


def write_settings(**changes: Any) -> Settings:
    """Keep `changes` (known keys only) and return everything as it now stands."""
    unknown = sorted(set(changes) - set(Settings.__dataclass_fields__))
    if unknown:
        raise SettingsError(f"no such setting: {', '.join(unknown)}")
    path = settings_path()
    raw = _load(path)
    now = _typed(raw | changes)
    kept = asdict(now) | {"export_formats": list(now.export_formats)}
    _write(path, raw | kept | {"version": SETTINGS_VERSION})
    return now
