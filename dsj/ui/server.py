"""The local server behind `dsj ui`: the built page, and the API it calls (#154).

Imported only by the `ui` command, after `dsj.ui.require_extra()` has checked
that fastapi and uvicorn are here, so the import at the top of this file is
never what a user without the extra sees.

The server imports dsj in this same process (#57 section 16). Nothing here
shells out to the CLI: a job started from the page is a function call, and its
failure is an exception this process can see.
"""

from __future__ import annotations

__all__ = ["STATIC", "create_app", "dev_app", "list_recordings", "serve"]

import secrets
import socket
import sys
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dsj.ui import UIUnavailable

# Committed, and inside the package, so an install carries the page with no
# Node on the machine. `just ui-build` writes it from ui/ (#57 section 8).
STATIC = Path(__file__).resolve().parent / "static"

# Loopback only, never 0.0.0.0: the page is for this machine (#57 section 9).
HOST = "127.0.0.1"


def list_recordings() -> list[dict[str, object]]:
    """Every recording dsj knows: none, until the store (#105) and the page (#156)."""
    return []


def create_app(port: int) -> tuple[FastAPI, str]:  # noqa: ARG001
    """Build the app for a server about to listen on `port`, and its token.

    The shape is the one #112's tests call, `app, token = create_app(port=8721)`.
    #112 is also what reads `port`, for the Host check, and what makes the token
    required on every request; until then neither is enforced.

    Raises:
        UIUnavailable: when the built page is not where the package expects it.
    """
    if not (STATIC / "index.html").is_file():
        raise UIUnavailable(
            f"the built page is missing: there is no index.html in {STATIC}. "
            f"From a clone, `just ui-build` writes it."
        )
    token = secrets.token_urlsafe(32)
    # No /docs or /redoc: they load their scripts from a CDN, and nothing about
    # this app may reach off the machine. /openapi.json stays, for #155.
    app = FastAPI(title="dsj", docs_url=None, redoc_url=None)
    app.add_api_route("/api/recordings", list_recordings, methods=["GET"])
    # Last, so every /api route above wins over a file of the same name.
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app, token


def serve(*, open_browser: bool) -> None:
    """Listen on a port the kernel picks, print the URL, and serve until stopped.

    The socket is bound here rather than by uvicorn so the port is known before
    the app is built, with no window between choosing a free port and taking it.
    It is listening before the URL is printed, so anything that reads the URL
    and connects at once is queued, not refused.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        sock.listen()
        port: int = sock.getsockname()[1]
        app, _token = create_app(port)
        url = f"http://{HOST}:{port}/"
        # The URL alone on stdout, so `dsj ui --print-url` composes the way
        # `dsj dikhao` does; everything for a person goes to stderr.
        print(url, flush=True)
        print("dsj ui is serving; Ctrl-C stops it.", file=sys.stderr, flush=True)
        if open_browser:
            webbrowser.open(url)
        # uvicorn shuts down cleanly on Ctrl-C or SIGTERM and then re-raises the
        # signal, so the exit code is the one the shell expects for it: 130 or 143.
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])


def dev_app() -> FastAPI:
    """The app for `just ui-dev`, which runs uvicorn with --reload on port 8721."""
    return create_app(8721)[0]
