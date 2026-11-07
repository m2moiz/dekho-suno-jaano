"""A transcript riding inside a copy of its recording (#122).

#117 tried six ways of writing a transcript into a recording and measured one
that survives a QuickTime re-save: a hidden `mov_text` subtitle track holding
the transcript gzip-compressed and base64-encoded. A timed-metadata track, a
free atom and bytes appended at the end all died on the re-save. This module
is that one route.

What it survives, and only this: a copy (`cp`) and a QuickTime passthrough
re-save (`avconvert --preset PresetPassthrough`, tests/test_embed.py keeps
that true). A plain `ffmpeg -c copy` drops subtitle tracks from a .mov unless
told `-map 0 -c:s copy`, and dsj's own bleep render does not carry it.

The source recording is never written: `embed_transcript` refuses an `out`
that is the source and writes a copy. The track is flagged so a player does
not show gzip-and-base64 as subtitles: language `und`, no default
disposition, and a title (`TRACK_TITLE`) that is how it is found again.
"""

from __future__ import annotations

__all__ = [
    "TRACK_TITLE",
    "EmbedRefused",
    "NoTranscriptInside",
    "cue_count",
    "embed_transcript",
    "extract_transcript",
    "find_track",
]

import base64
import gzip
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from dsj.media import MediaError, tool

# How the track names itself, in the mov's handler name and title, for a
# reader to find it among the recording's own subtitles.
TRACK_TITLE = "dsj-transcript"

# A tx3g sample carries a 16-bit length, so a cue holds under 65,535 bytes;
# this leaves room for the length word and a player that pads.
CUE_BYTES = 60_000

# Each cue is one millisecond, back to back from the start of the recording:
# the times mean nothing, the order is everything.
CUE_MS = 1


class EmbedRefused(MediaError):
    """The embed cannot be done as asked. Nothing was written."""


class NoTranscriptInside(MediaError):
    """The recording carries no transcript track of ours."""


def _encode(payload: bytes) -> str:
    return base64.b64encode(gzip.compress(payload, mtime=0)).decode("ascii")


def _decode(text: str) -> bytes:
    return gzip.decompress(base64.b64decode(text))


def _srt_clock(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _cues(encoded: str) -> str:
    """The encoded transcript as SRT cues of CUE_BYTES each, one millisecond apart."""
    chunks = [encoded[i : i + CUE_BYTES] for i in range(0, len(encoded), CUE_BYTES)] or [""]
    blocks = [
        f"{n}\n{_srt_clock(n * CUE_MS)} --> {_srt_clock((n + 1) * CUE_MS)}\n{chunk}\n"
        for n, chunk in enumerate(chunks, start=1)
    ]
    return "\n".join(blocks)


def embed_transcript(media: Path, transcript: Path, out: Path) -> Path:
    """Write a copy of `media` to `out` with `transcript` riding inside it as a hidden track.

    Every stream of `media` is copied as it is (`-map 0 -c copy`); the track is
    added beside them, never in place of one.

    Raises:
        EmbedRefused: `out` is the source, or ffmpeg refused the copy.
    """
    if out.resolve() == media.resolve():
        raise EmbedRefused(
            f"{out} is the recording itself; the embed writes a copy, never the source (#117)."
        )
    payload = transcript.read_bytes()
    json.loads(payload)  # a transcript, not any file: refused here, not found broken later
    with tempfile.TemporaryDirectory(prefix="dsj-embed-") as tmp:
        cues = Path(tmp) / "transcript.srt"
        cues.write_text(_cues(_encode(payload)), encoding="utf-8")
        # Beside `out`, so the rename at the end is within one file system.
        partial = out.with_name(f".{out.name}.partial{out.suffix}")
        cmd = [
            tool("ffmpeg"),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(media),
            "-i",
            str(cues),
            "-map",
            "0",
            "-map",
            "1:0",
            "-c",
            "copy",
            "-c:s",
            "mov_text",
            # The track names itself and hides: no default flag, no language a
            # player picks. The name is the first way to find it; a QuickTime
            # re-save renames the handler, so the content is the second
            # (find_track).
            "-metadata:s:s:0",
            f"title={TRACK_TITLE}",
            "-metadata:s:s:0",
            f"handler_name={TRACK_TITLE}",
            "-metadata:s:s:0",
            "language=und",
            "-disposition:s:0",
            "0",
            str(partial),
        ]
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            partial.unlink(missing_ok=True)
            raise EmbedRefused(
                f"ffmpeg could not write {out} with the transcript inside "
                f"(exit {done.returncode}):\n{done.stderr.strip()}"
            )
        partial.replace(out)
    return out


def _streams(media: Path) -> list[dict[str, Any]]:
    done = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", str(media)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise MediaError(
            f"ffprobe could not read {media} (exit {done.returncode}):\n{done.stderr.strip()}"
        )
    streams: list[dict[str, Any]] = json.loads(done.stdout).get("streams", [])
    return streams


# gzip's magic bytes, 1f 8b, as base64 opens them: what every cue of ours starts with.
_GZIP_B64 = "H4sI"


def find_track(media: Path) -> dict[str, Any] | None:
    """The ffprobe stream of our track in `media`, or None when it carries none.

    By name first; by content when a re-save has renamed the track (QuickTime
    writes "Core Media Text" over the handler name): a mov_text track whose
    first cue opens as gzip in base64 is ours, and no subtitle a person wrote does.
    """
    subtitles = [s for s in _streams(media) if s.get("codec_type") == "subtitle"]
    for stream in subtitles:
        tags: dict[str, Any] = stream.get("tags", {})
        names = {str(tags.get("title", "")), str(tags.get("handler_name", ""))}
        if any(TRACK_TITLE in name for name in names):
            return stream
    for stream in subtitles:
        if stream.get("codec_name") != "mov_text":
            continue
        texts = _cue_texts(media, int(stream["index"]))
        if texts and texts[0].startswith(_GZIP_B64):
            return stream
    return None


_CUE_TEXT = re.compile(r"^\d+\n\S+ --> \S+\n(.*?)(?:\n\n|\Z)", re.MULTILINE | re.DOTALL)


def _cue_texts(media: Path, index: int) -> list[str]:
    done = subprocess.run(
        [
            tool("ffmpeg"),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media),
            "-map",
            f"0:{index}",
            "-f",
            "srt",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise MediaError(
            f"ffmpeg could not read the transcript track out of {media} (exit {done.returncode}):\n"
            f"{done.stderr.strip()}"
        )
    return [m.group(1).replace("\n", "") for m in _CUE_TEXT.finditer(done.stdout.strip() + "\n\n")]


def cue_count(media: Path) -> int:
    """How many cues our track in `media` holds; 0 when there is no track."""
    track = find_track(media)
    return 0 if track is None else len(_cue_texts(media, int(track["index"])))


def extract_transcript(media: Path) -> dict[str, Any]:
    """The transcript riding inside `media`, as the JSON it was.

    Raises:
        NoTranscriptInside: `media` carries no track of ours.
    """
    track = find_track(media)
    if track is None:
        raise NoTranscriptInside(
            f"{media} carries no dsj transcript. `dsj daalo` writes one into a copy of a recording."
        )
    texts = _cue_texts(media, int(track["index"]))
    found: dict[str, Any] = json.loads(_decode("".join(texts)))
    return found
