"""Export a transcript when its job finishes, without being asked (#132).

The same writers as the Export menu and `dsj likho` (dsj/likho.py EXPORTERS),
run over the transcript's edit list as it stands (dsj/ui/edits.py as_payload),
to a file beside the recording named after it: `call.m4a` gets `call.srt`.
Which formats, and whether a file already there is written over, are settings
(dsj/ui/settings.py); nothing is written while no format is turned on.

Each format gets its own result: `exported`, `skipped` (a file was there and
overwriting is off), or `failed` with the exception's own words. Nothing here
raises past the job: a transcript that is done is done, whatever became of its
copies, and the job carries the results for the page to show.
"""

from __future__ import annotations

__all__ = ["ExportResult", "auto_export"]

from dataclasses import asdict, dataclass
from pathlib import Path

from dsj import likho
from dsj.atomic import atomic_write_text
from dsj.ui import edits
from dsj.ui.settings import read_settings


@dataclass(frozen=True)
class ExportResult:
    """What became of one format: where it went, or why it did not."""

    format: str
    path: str
    # exported, skipped or failed.
    outcome: str
    reason: str | None

    def view(self) -> dict[str, object]:
        """This result as the page reads it, on the job (dsj/ui/schemas.py ExportResult)."""
        return asdict(self)


def _one(fmt: str, dest: Path, payload: dict[str, object] | None, overwrite: bool) -> ExportResult:
    write = likho.EXPORTERS.get(fmt)
    if write is None:
        return ExportResult(fmt, str(dest), "failed", f"dsj writes no {fmt!r}")
    if dest.exists() and not overwrite:
        return ExportResult(
            fmt, str(dest), "skipped",
            f"{dest.name} is already there and overwriting is off in the settings",
        )
    if payload is None:
        return ExportResult(fmt, str(dest), "failed", "the transcript could not be read back")
    try:
        atomic_write_text(dest, write(payload))
    except Exception as exc:
        return ExportResult(fmt, str(dest), "failed", f"{type(exc).__name__}: {exc}")
    return ExportResult(fmt, str(dest), "exported", None)


def auto_export(transcript_id: int, media: Path) -> list[ExportResult]:
    """Write every configured format beside `media`, one result each; none when none is on."""
    found = read_settings()
    if not found.export_formats:
        return []
    payload: dict[str, object] | None
    try:
        payload = edits.as_payload(edits.open_edits(transcript_id))
    except Exception as exc:
        # Every format fails the same way, said once each so the page can show it per file.
        why = f"{type(exc).__name__}: {exc}"
        return [
            ExportResult(fmt, str(media.with_suffix(f".{fmt}")), "failed", why)
            for fmt in found.export_formats
        ]
    return [
        _one(fmt, media.with_suffix(f".{fmt}"), payload, found.export_overwrite)
        for fmt in found.export_formats
    ]
