"""The MCP server (#76): suno, dekho and dikhao as tools, called in process.

Each test connects a client to the server over the SDK's memory streams, so
nothing is spawned and no socket is opened. The heavy functions the tools wrap
are stood in for where they would load a model or scan a video, as the job
tests stand in for the engine; dikhao runs the real frame extraction over a
one-second video ffmpeg makes here.
"""

from __future__ import annotations

import ast
import json
import subprocess
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolResult

from dsj import mcp as dsj_mcp
from dsj.dekho import DEFAULT_BUDGET, DEFAULT_FPS
from dsj.suno import DEFAULT_MODEL, DEFAULT_WHISPER_MODEL, Progress
from dsj.whisper import ANCHOR_CHUNK_S, ROMAN_URDU_PROMPT


@asynccontextmanager  # pyright: ignore[reportDeprecated]
async def connected() -> AsyncIterator[ClientSession]:
    """A client talking to the server in this process, initialised and ready."""
    server = dsj_mcp.build_server()
    async with (
        create_client_server_memory_streams() as (client_streams, server_streams),
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(dsj_mcp.serve_streams, server, *server_streams)
        async with ClientSession(*client_streams) as session:
            await session.initialize()
            yield session
        tg.cancel_scope.cancel()


def _run(test: Callable[[], Any]) -> Any:
    return anyio.run(test)


def _structured(result: CallToolResult | Any) -> dict[str, Any]:
    assert isinstance(result, CallToolResult), result
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


def test_the_three_tools_are_listed_with_their_arguments() -> None:
    async def go() -> None:
        async with connected() as session:
            listed = await session.list_tools()
            tools = {t.name: t for t in listed.tools}
            assert set(tools) == {"suno", "dekho", "dikhao"}
            assert set(tools["suno"].input_schema["properties"]) >= {
                "media",
                "out",
                "engine",
                "model",
                "language",
                "prompt",
                "roman_urdu",
                "diarize",
                "resume",
            }
            assert set(tools["dekho"].input_schema["properties"]) >= {
                "media",
                "transcript",
                "out",
                "fps",
                "budget",
            }
            assert set(tools["dikhao"].input_schema["properties"]) >= {
                "video",
                "seconds",
                "out",
                "width",
            }
            description = tools["suno"].description
            assert description is not None
            assert "transcri" in description.lower()

    _run(go)


def test_suno_transcribes_through_dsj_and_reports_progress_while_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_transcribe(
        media: Path, out: Path, model_id: str | None = None, **kw: Any
    ) -> dict[str, Any]:
        calls.append({"media": media, "out": out, "model_id": model_id, **kw})
        on_progress = kw["on_progress"]
        on_progress(Progress(30.0, 120.0, 1.0), "running")
        on_progress(Progress(120.0, 120.0, 4.0), "running")
        payload: dict[str, Any] = {
            "audio": str(media),
            "model": model_id,
            "text": " Hello.",
            "sentences": [{"start": 0.0, "end": 1.0, "text": " Hello.", "tokens": []}],
            "speakers": ["SPEAKER_00"],
        }
        out.write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(dsj_mcp, "transcribe", fake_transcribe)
    media = tmp_path / "call.m4a"
    media.write_bytes(b"not read")
    out = tmp_path / "call.json"
    seen: list[tuple[float, float | None, str | None]] = []

    async def go() -> None:
        async with connected() as session:

            async def progress(progress: float, total: float | None, message: str | None) -> None:
                seen.append((progress, total, message))

            result = await session.call_tool(
                "suno",
                {"media": str(media), "out": str(out), "diarize": False},
                progress_callback=progress,
            )
            found = _structured(result)
            assert found == {
                "out": str(out),
                "sentences": 1,
                "speakers": ["SPEAKER_00"],
                "text_chars": 7,
            }

    _run(go)
    (call,) = calls
    # The CLI's defaults, from the same names: parakeet's model, resume on.
    assert call["model_id"] == DEFAULT_MODEL
    assert call["engine"] == "parakeet"
    assert call["resume"] is True
    assert call["diarize"] is False
    assert call["anchor_s"] is None
    assert [(d, t) for d, t, _ in seen] == [(30.0, 120.0), (120.0, 120.0)]
    assert seen[0][2] is not None
    assert "running" in seen[0][2]


def test_suno_roman_urdu_turns_into_what_the_cli_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_transcribe(
        media: Path, out: Path, model_id: str | None = None, **kw: Any
    ) -> dict[str, Any]:
        calls.append({"model_id": model_id, **kw})
        out.write_text(
            json.dumps({"audio": str(media), "model": model_id, "text": "", "sentences": []})
        )
        return {"audio": str(media), "model": model_id, "text": "", "sentences": []}

    monkeypatch.setattr(dsj_mcp, "transcribe", fake_transcribe)
    media = tmp_path / "call.m4a"
    media.write_bytes(b"x")

    async def go() -> None:
        async with connected() as session:
            _structured(
                await session.call_tool(
                    "suno",
                    {"media": str(media), "out": str(tmp_path / "o.json"), "roman_urdu": True},
                )
            )

    _run(go)
    (call,) = calls
    assert call["engine"] == "whisper"
    assert call["language"] == "ur"
    assert call["prompt"] == ROMAN_URDU_PROMPT
    assert call["anchor_s"] == ANCHOR_CHUNK_S
    assert call["model_id"] == DEFAULT_WHISPER_MODEL


def test_a_run_that_fails_is_a_tool_error_in_dsj_s_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("the model exploded")

    monkeypatch.setattr(dsj_mcp, "transcribe", refuse)
    media = tmp_path / "call.m4a"
    media.write_bytes(b"x")

    async def go() -> None:
        async with connected() as session:
            result = await session.call_tool(
                "suno", {"media": str(media), "out": str(tmp_path / "o.json")}
            )
            assert isinstance(result, CallToolResult)
            assert result.is_error
            assert "the model exploded" in str(result.content[0])

    _run(go)


def test_dekho_marks_through_dsj_with_the_cli_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_mark_video(media: Path, transcript: Path, out: Path, **kw: Any) -> dict[str, Any]:
        calls.append({"media": media, "transcript": transcript, "out": out, **kw})
        kw["on_progress"](0.5)
        payload = {"marks": [{"t": 0.5}, {"t": 0.9}], "marks_meta": {"frames_sampled": 2}}
        out.write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(dsj_mcp, "mark_video", fake_mark_video)
    media = tmp_path / "screen.mov"
    media.write_bytes(b"x")
    transcript = tmp_path / "screen.json"
    transcript.write_text("{}")

    async def go() -> None:
        async with connected() as session:
            found = _structured(
                await session.call_tool(
                    "dekho", {"media": str(media), "transcript": str(transcript)}
                )
            )
            assert found == {"out": str(transcript), "marks": 2, "frames_sampled": 2}

    _run(go)
    (call,) = calls
    assert (
        call["out"] == transcript
    )  # no `out` given: the transcript is written over, as the CLI does
    assert call["fps"] == DEFAULT_FPS
    assert call["budget"] == DEFAULT_BUDGET


def test_dikhao_writes_a_real_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    out = tmp_path / "frame.jpg"

    async def go() -> None:
        async with connected() as session:
            found = _structured(
                await session.call_tool(
                    "dikhao", {"video": str(video), "seconds": 0.5, "out": str(out)}
                )
            )
            assert found == {"frame": str(out)}

    _run(go)
    assert out.stat().st_size > 0


def test_the_server_calls_no_ffmpeg_and_loads_no_model_of_its_own() -> None:
    """The tools reuse dsj/ in process (#76): no subprocess and no engine import of their own."""
    source = Path(dsj_mcp.__file__).read_text()
    tree = ast.parse(source)
    imported = {
        name.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for name in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "subprocess" not in imported
    assert not {"mlx", "mlx_whisper", "parakeet_mlx", "sherpa_onnx", "senko"} & imported
    # The only dsj functions it calls are the three the CLI calls, by the names it imports.
    from_dsj = {
        name.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("dsj.")
        for name in node.names
        if name.name[0].islower()
    }
    assert from_dsj == {"mark_video", "extract_frame", "roman_urdu", "transcribe"}
