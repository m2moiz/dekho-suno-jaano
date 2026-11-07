"""How much of a model has come down while a job loads it (#337).

parakeet and whisper fetch their models through huggingface_hub inside the
engine's load, which says nothing to the job: a first run on a slow
connection reads as a hang for the length of a multi-GB download. The hub
writes what it has into its cache as it goes, finished blobs beside
`.incomplete` ones, so a watcher that adds those up every EVERY_S has the
number the job can show. It reads the cache only; it changes nothing and
never raises past the job.
"""

from __future__ import annotations

__all__ = ["EVERY_S", "Watcher", "downloaded_bytes", "hub_repo"]

import os
import threading
from collections.abc import Callable
from pathlib import Path

# How often the cache is read while a model loads: often enough to move,
# rare enough that a directory listing costs nothing beside the download.
EVERY_S = 1.0


def _hub_cache() -> Path:
    # The same resolution huggingface_hub makes (HF_HUB_CACHE, else HF_HOME/hub,
    # else ~/.cache/huggingface/hub), read here from the environment so this
    # check costs no import of the hub on a machine without the extras, and
    # a test that points the cache elsewhere is read the way the engine reads it.
    configured = os.environ.get("HF_HUB_CACHE")
    if configured:
        return Path(configured).expanduser()
    home = os.environ.get("HF_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def hub_repo(model: str) -> Path:
    """Where the hub cache keeps `model`, whether or not anything is there yet."""
    return _hub_cache() / f"models--{model.replace('/', '--')}"


def downloaded_bytes(model: str) -> int | None:
    """Bytes the hub cache holds for `model`, finished or not; None when it has no folder yet."""
    repo = hub_repo(model)
    blobs = repo / "blobs"
    if not blobs.is_dir():
        return None if not repo.is_dir() else 0
    total = 0
    for blob in blobs.iterdir():
        try:
            total += blob.stat().st_size
        except OSError:
            # Renamed under us, as a finished download is; the next read sees it whole.
            continue
    return total


class Watcher:
    """Read `model`'s bytes every EVERY_S on a thread of its own and hand them to `report`."""

    def __init__(self, model: str, report: Callable[[float], None]) -> None:
        """Watch `model`'s cache folder; `report` gets the megabytes there at every look."""
        self._model = model
        self._report = report
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dsj-ui-download", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            found = downloaded_bytes(self._model)
            if found is not None:
                self._report(found / 1_000_000)
            self._stop.wait(EVERY_S)

    def __enter__(self) -> Watcher:
        """Start looking."""
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        """Stop looking, whatever ended the block."""
        self.stop()

    def stop(self) -> None:
        """Stop reading; the last number handed over stays with the job."""
        self._stop.set()
