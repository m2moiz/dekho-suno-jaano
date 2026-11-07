"""What a run needs, asked up front (#70): ffmpeg, an engine, its model.

dsj already answers all three, but only when the work reaches each one: ffmpeg
when a video is read (dsj.media.FFmpegNotFound), the engine when it is asked
for (dsj.asr.EngineUnavailable), the model when the engine loads it, silently,
through huggingface_hub's cache. Here they are asked before anything starts,
so the app can say what is missing on its first screen, with the fix, rather
than forty minutes into a run or not at all.

Each answer is a reading of the machine now, never a guess from the platform
(dsj/asr.py says why): a person who installs ffmpeg and reloads sees it.
"""

from __future__ import annotations

__all__ = ["ModelState", "ToolState", "model_state", "readiness", "tool_state"]

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dsj.ui.jobs import EngineChoice, engine_choices


@dataclass(frozen=True)
class ToolState:
    """One command the run shells out to: on PATH or not, and where, or the fix."""

    name: str
    ok: bool
    path: str | None
    # dsj.media's own sentence for a missing tool, so the screen and the error agree.
    reason: str | None


@dataclass(frozen=True)
class ModelState:
    """An engine's default model, as this machine holds it right now."""

    engine: str
    model: str
    # present: whole, on disk. missing: not fetched yet, the first run fetches
    # it. partial: a download that did not finish (an `.incomplete` blob in
    # the cache); the next run resumes it. unknown: the engine keeps its model
    # somewhere this check does not read.
    state: str
    reason: str


def tool_state(name: str) -> ToolState:
    """Whether `name` is on PATH now, with dsj.media's own sentence when it is not."""
    path = shutil.which(name)
    if path is not None:
        return ToolState(name, True, path, None)
    return ToolState(
        name, False, None,
        f"{name} is not on PATH. dsj reads video through ffmpeg; install it with "
        f"`brew install ffmpeg`.",
    )


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


def _hub_state(model: str) -> tuple[str, str]:
    repo = _hub_cache() / f"models--{model.replace('/', '--')}"
    if not repo.is_dir() or not any((repo / "snapshots").glob("*")):
        return "missing", f"{model} is not on this Mac yet; the first run downloads it"
    if any((repo / "blobs").glob("*.incomplete")):
        return (
            "partial",
            f"a download of {model} did not finish; the next run resumes it before transcribing",
        )
    return "present", f"{model} is on this Mac"


def model_state(engine: str, model: str) -> ModelState:
    """How this machine holds `engine`'s `model`: present, missing, partial or unknown."""
    if engine == "sherpa":
        # sherpa takes a directory on disk (dsj/sherpa.py load), nothing is fetched.
        folder = Path(model).expanduser()
        if folder.is_dir():
            return ModelState(engine, model, "present", f"{folder} is on this Mac")
        return ModelState(
            engine, model, "missing",
            f"sherpa model directory not found: {folder}; put a sherpa-onnx model there",
        )
    if engine in ("parakeet", "whisper"):
        state, reason = _hub_state(model)
        return ModelState(engine, model, state, reason)
    return ModelState(
        engine, model, "unknown", f"{engine} keeps its model where this check does not read"
    )


def readiness() -> tuple[list[ToolState], list[EngineChoice], list[ModelState]]:
    """Ffmpeg and ffprobe, every engine with its reason, and each engine's default model."""
    tools = [tool_state("ffmpeg"), tool_state("ffprobe")]
    engines = engine_choices()
    models = [
        model_state(choice.name, choice.default_model)
        for choice in engines
        if choice.reason is None
    ]
    return tools, engines, models
