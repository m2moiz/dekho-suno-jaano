"""`dsj ui`: the local app that holds every recording and its transcripts (#57).

This module imports nothing beyond the standard library, on purpose. The web
server lives in the `ui` extra, and anything under `dsj.ui` that does not serve
pages (the library store, for one) must stay importable without it. Only
`require_extra()` reaches for fastapi, and only when a caller asks.
"""

from __future__ import annotations

__all__ = ["INSTALL_HINT", "UIUnavailable", "require_extra"]

# The working line, not the bare `dsj[mac,ui]` that #57 and #111 wrote down:
# dsj is not on PyPI, so `uv tool install 'dsj[mac,ui]'` fails with "there are
# no versions of dsj[mac]" (run 2026-10-02). From a clone the hint cannot be a
# whole `uv sync` line, because `uv sync` uninstalls every extra it is not given
# (#170); it names the flag to add instead, as the engine extras do.
INSTALL_HINT = (
    '`uv tool install "dsj[mac,ui] @ git+https://github.com/m2moiz/dekho-suno-jaano"`,'
    " or from a clone add `--extra ui` to the `uv sync` line you already use"
    " (`uv sync` uninstalls every extra it is not given)"
)


class UIUnavailable(RuntimeError):
    """`dsj ui` cannot start here. No server is listening.

    The sibling of dsj.asr.EngineUnavailable and dsj.media.FFmpegNotFound: a
    missing piece named, with the line that installs it, rather than a bare
    ModuleNotFoundError that says what is absent and not what to type. There is
    no degraded mode to fall back to; an app with no server has nothing to show.
    """


def require_extra() -> None:
    """Import the web server's packages, or say how to install them.

    Called inside the `ui` command, never at import time: a module-top import of
    fastapi would be paid by every `dsj --help` and every `dsj suno`.

    Raises:
        UIUnavailable: when fastapi or uvicorn will not import.
    """
    try:
        import fastapi  # noqa: F401  # pyright: ignore[reportUnusedImport]
        import uvicorn  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except ImportError as exc:
        raise UIUnavailable(
            f"dsj ui needs the `ui` extra, which is not installed here ({exc}). "
            f"Install it with {INSTALL_HINT}."
        ) from exc
