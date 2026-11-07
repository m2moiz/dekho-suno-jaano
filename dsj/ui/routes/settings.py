"""The app's settings (#69): read them, change some of them.

The file and its versioning are dsj/ui/settings.py; this only turns requests
into calls on it. Both handlers are sync, run on a worker thread, and touch
one small file, so there is nothing to hold open between them.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter

from dsj.ui import settings as store
from dsj.ui.schemas import Settings, SettingsUpdate

router = APIRouter(prefix="/api")


def _wire(found: store.Settings) -> Settings:
    return Settings(
        version=store.SETTINGS_VERSION,
        transcribe_answer=found.transcribe_answer,  # pyright: ignore[reportArgumentType]
        transcribe_diarize=found.transcribe_diarize,
        export_formats=list(found.export_formats),  # pyright: ignore[reportArgumentType]
        export_overwrite=found.export_overwrite,
    )


@router.get("/settings")
def read_settings() -> Settings:
    """Every setting as it stands, the defaults for anything never changed."""
    return _wire(store.read_settings())


@router.put("/settings")
def change_settings(update: SettingsUpdate) -> Settings:
    """Change the keys given, keep the rest, and answer with all of them."""
    changes = update.model_dump(exclude_none=True)
    return _wire(store.write_settings(**changes) if changes else store.read_settings())
