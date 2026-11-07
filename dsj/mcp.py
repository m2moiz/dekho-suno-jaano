"""dsj as MCP tools (#76): suno, dekho and dikhao, for an agent to call directly.

A second face on the same core, not a second product: the tools call the
functions `dsj/cli.py` calls, `transcribe()`, `mark_video()` and
`extract_frame()`, in this process, with the same defaults imported from the
same names, so nothing about the pipeline is repeated here and nothing here
runs ffmpeg or loads a model of its own (tests/test_mcp.py holds it to that).

A transcription reports progress through the MCP progress notification while
it runs, from `transcribe()`'s own `on_progress`, so an agent sees the run
move instead of waiting on a silent call. The run itself happens on a worker
thread: the functions are blocking, and the session has to keep talking.

The surface is tools only (SEP-1865: an MCP app renders in a sandboxed frame
with no network, so the editing workspace stays in the local app). Run it
with `dsj-mcp`, which speaks MCP over stdio.
"""

from __future__ import annotations

__all__ = ["build_server", "main", "serve_streams"]

from collections.abc import Callable
from pathlib import Path
from typing import Any

from anyio import from_thread, to_thread

try:
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as exc:  # pragma: no cover - the extra is in every test environment
    raise SystemExit(
        "the MCP server needs the `mcp` extra, which this install lacks: "
        '`uv tool install "dsj[mac] @ git+https://github.com/m2moiz/dekho-suno-jaano"`, '
        "or from a clone add `--extra mcp` to the `uv sync` line you already use."
    ) from exc

from dsj.dekho import DEFAULT_BUDGET, DEFAULT_DELTA, DEFAULT_FPS, DEFAULT_MIN_GAP_S, mark_video
from dsj.media import extract_frame
from dsj.suno import DEFAULT_MODEL, DEFAULT_WHISPER_MODEL, Progress, transcribe
from dsj.suno import roman_urdu as roman_urdu_args

INSTRUCTIONS = (
    "dsj makes a long screen recording answerable. `suno` writes a timestamped "
    "transcript (JSON) of a video or audio file; `dekho` adds marks for the moments the "
    "picture changed most; `dikhao` writes the frame at a given second to an image. Paths "
    "are on this machine. A first `suno` run downloads its model."
)

SUNO = (
    "Transcribe a recording to a timestamped JSON transcript at `out`. `engine` is parakeet "
    "(English and European languages, the default), whisper (Urdu and the languages parakeet "
    "lacks) or sherpa; `roman_urdu` picks whisper with Urdu written in Roman letters. An "
    "interrupted run resumes from its checkpoint unless `resume` is false. Progress is "
    "reported while it runs."
)
DEKHO = (
    "Mark the moments a recording's picture changed most, so a transcript can say what was "
    "on screen. Reads `transcript` (from suno) and writes it with marks to `out`, or back "
    "over `transcript` when `out` is not given."
)
DIKHAO = (
    "Write the frame at `seconds` into `video` to the image file `out` (.jpg is what a "
    "vision model wants), at most `width` pixels wide."
)


async def _in_thread[T](work: Callable[[], T]) -> T:
    """Run blocking `work` on a worker thread; a failure is the tool's error, in dsj's own words.

    The SDK answers an unexpected exception with "Error executing tool", which
    tells an agent nothing; `ToolError` carries the sentence dsj raised (a
    missing file, an engine that cannot run here, ffmpeg's own complaint).
    """
    try:
        return await to_thread.run_sync(work)
    except Exception as exc:
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


async def suno(
    media: str,
    out: str,
    ctx: Context,
    engine: str = "parakeet",
    model: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
    roman_urdu: bool = False,
    diarize: bool = True,
    resume: bool = True,
) -> dict[str, Any]:
    """The `suno` tool: dsj.suno.transcribe with the CLI's defaults and its progress relayed."""
    anchor_s: float | None = None
    if roman_urdu:
        engine, language, prompt, anchor_s = roman_urdu_args(engine, language, prompt)
    # Resolved here as the CLI resolves it, from the same names (dsj/cli.py).
    model_id = model or (DEFAULT_WHISPER_MODEL if engine == "whisper" else DEFAULT_MODEL)

    def report(p: Progress, state: str) -> None:
        # From the worker thread back onto the session's loop.
        from_thread.run(
            ctx.report_progress,
            p.audio_done_s,
            p.audio_total_s or None,
            f"{state}: {p.audio_done_s:.0f} s of {p.audio_total_s:.0f} s",
        )

    payload: dict[str, Any] = await _in_thread(
        lambda: transcribe(
            Path(media),
            Path(out),
            model_id,
            on_progress=report,
            resume=resume,
            diarize=diarize,
            engine=engine,
            language=language,
            prompt=prompt,
            anchor_s=anchor_s,
        )
    )
    sentences: list[Any] = payload.get("sentences", [])
    text: str = payload.get("text", "")
    return {
        "out": out,
        "sentences": len(sentences),
        "speakers": payload.get("speakers"),
        "text_chars": len(text),
    }


async def dekho(
    media: str,
    transcript: str,
    ctx: Context,
    out: str | None = None,
    fps: float = DEFAULT_FPS,
    delta: int = DEFAULT_DELTA,
    budget: int = DEFAULT_BUDGET,
    min_gap_s: float = DEFAULT_MIN_GAP_S,
) -> dict[str, Any]:
    """The `dekho` tool: dsj.dekho.mark_video with the CLI's defaults and its progress relayed."""
    dest = Path(out) if out else Path(transcript)

    def report(done_s: float) -> None:
        from_thread.run(ctx.report_progress, done_s, None, f"scanning {done_s:.0f} s of video")

    payload: dict[str, Any] = await _in_thread(
        lambda: mark_video(
            Path(media),
            Path(transcript),
            dest,
            fps=fps,
            delta=delta,
            budget=budget,
            min_gap_s=min_gap_s,
            on_progress=report,
        )
    )
    marks: list[Any] = payload.get("marks", [])
    meta: dict[str, Any] = payload.get("marks_meta", {})
    return {"out": str(dest), "marks": len(marks), "frames_sampled": meta.get("frames_sampled")}


async def dikhao(video: str, seconds: float, out: str, width: int = 1500) -> dict[str, Any]:
    """The `dikhao` tool: dsj.media.extract_frame, with the CLI's width ceiling."""
    dest = await _in_thread(
        lambda: extract_frame(Path(video), seconds, Path(out), width=width or None)
    )
    return {"frame": str(dest)}


def build_server() -> MCPServer:
    """The server with its three tools registered; one per process, built on demand."""
    server = MCPServer("dsj", instructions=INSTRUCTIONS)
    server.tool(name="suno", description=SUNO)(suno)
    server.tool(name="dekho", description=DEKHO)(dekho)
    server.tool(name="dikhao", description=DIKHAO)(dikhao)
    return server


async def serve_streams(server: MCPServer, read_stream: Any, write_stream: Any) -> None:
    """Serve `server` over a pair of streams: a test's memory streams, or stdio's."""
    low = server._lowlevel_server  # pyright: ignore[reportPrivateUsage]
    await low.run(read_stream, write_stream, low.create_initialization_options())


def main() -> None:
    """`dsj-mcp`: the server over stdio, for an MCP host to start."""
    build_server().run("stdio")
