"""A transcript's review (Hashiya spec, Review mode): which sentences a person has checked.

This first part says where a review lives and how far it has got, for the
library list (#245). The review document itself, its routes and the
answer-key export are added with Review mode's backend.

A review is filed beside the library in `reviews/`, under the same key as the
transcript's edit list (dsj/ui/edits.py, edits_path): the transcript JSON's
path, so a rebuilt library finds it again, and never beside the recording.

Plain Python, no fastapi.
"""

from __future__ import annotations

__all__ = ["progress", "review_path"]

import json
import logging
from pathlib import Path
from typing import Any, cast

from dsj.ui.edits import edits_path
from dsj.ui.store import library_path

_log = logging.getLogger(__name__)


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
