"""The local server behind `dsj ui`: the built page, and the API it calls (#154).

Imported only by the `ui` command, after `dsj.ui.require_extra()` has checked
that fastapi and uvicorn are here, so the import at the top of this file is
never what a user without the extra sees.

The server imports dsj in this same process (#57 section 16). Nothing here
shells out to the CLI: a job started from the page is a function call, and its
failure is an exception this process can see.

Any page open in any other tab can send requests to a server on this machine;
it only has to guess the port. So only this machine's own page may use this one
(#112), by six rules:

  1. It listens on 127.0.0.1 only, on a port the kernel picks.
  2. Every /api and /media request carries a token made at startup, in an
     `Authorization` header. The page itself is served without one: a browser
     navigation cannot send a header. Nor can an <audio> or <video> element,
     so a recording's media route alone also takes it as `?t=` (#59).
  3. A request whose `Host` is not this server's loopback address is refused
     before anything else is looked at. That is what stops a hostile site
     pointing its own domain at 127.0.0.1 (DNS rebinding).
  4. No CORS header is ever sent, so another origin's script cannot read a
     reply even when it guesses the port and the token check lets it through.
  5. No route takes a filesystem path. The page names a recording by id and
     the server looks the path up itself.
  6. The page heartbeats, and the process exits after a minute without one.
     A lock file lets a second `dsj ui` find the first instead of binding a
     rival.
"""

from __future__ import annotations

__all__ = [
    "IDLE_S",
    "STATIC",
    "Heartbeat",
    "create_app",
    "dev_app",
    "lock_path",
    "serve",
]

import contextlib
import fcntl
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from dsj.ui import UIUnavailable
from dsj.ui.errors import STATUS, describe
from dsj.ui.jobs import Jobs
from dsj.ui.routes import jobs, media, recording
from dsj.ui.store import library_path

# Committed, and inside the package, so an install carries the page with no
# Node on the machine. `just ui-build` writes it from ui/ (#57 section 8).
STATIC = Path(__file__).resolve().parent / "static"

# Loopback only, never 0.0.0.0: the page is for this machine (#57 section 9).
HOST = "127.0.0.1"

# How long the server outlives the last sign of a page, in seconds (#112 rule 6).
# The page beats every 15 s, so a minute is four missed beats, not one.
IDLE_S = 60.0

# The prefixes whose requests must carry the token. The page and its assets
# are everything else, and are served to any loopback request (#112 rule 2).
_GUARDED = ("/api", "/media")

# The one route whose requests come from a media element, which sends no
# headers of its own: GET or HEAD of a recording's file (dsj/ui/routes/media.py).
_MEDIA = re.compile(r"/api/recording/[^/]+/media")

# How long a second `dsj ui` waits for the first to write where it listens. The
# first writes it straight after binding, so this only covers two launched in
# the same instant.
_HOLDER_WAIT_S = 2.0


class Heartbeat:
    """When the page was last heard from, on a clock that never jumps."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Start the count now, so a server no page ever opens still stops."""
        self._clock = clock
        self._last = clock()
        self._holds = 0
        self._lock = threading.Lock()

    def beat(self) -> None:
        """The page is still there."""
        self._last = self._clock()

    def idle_s(self) -> float:
        """Seconds since the page was last heard from, or 0 while something holds it."""
        if self._holds:
            return 0.0
        return self._clock() - self._last

    @contextlib.contextmanager
    def hold(self) -> Generator[None]:
        """Count as heard from for as long as the block runs, and for IDLE_S after.

        A transcription started from the page (#113) can take an hour, and a
        closed tab must not stop the server under it: the job would die with
        the process, half done, its status file still saying `running`.
        """
        with self._lock:
            self._holds += 1
        try:
            yield
        finally:
            with self._lock:
                self._holds -= 1
            self.beat()


class _Guard:
    """Rules 2 and 3, in that order, before any route runs.

    The `Host` check comes first and the token check second, so a request from
    the wrong origin learns nothing from which of the two refused it, and no
    route ever starts a lookup for a caller nobody has identified (#112, first
    comment, point 2). A pure ASGI middleware rather than an HTTP one, so a
    refusal never builds a Request or reads a body.
    """

    def __init__(
        self, app: ASGIApp, *, hosts: frozenset[str], token: str, heartbeat: Heartbeat
    ) -> None:
        self.app = app
        self.hosts = hosts
        self.expected = f"Bearer {token}".encode()
        self.token = token.encode()
        self.heartbeat = heartbeat

    def _carries_token(self, scope: Scope, headers: dict[bytes, bytes]) -> bool:
        """The header, or for a media element's request, `?t=`.

        A query token is accepted on the media route only, and only to read:
        the URL of a subresource reaches no history and no Referer, and serve()
        runs uvicorn at "warning", below its access log, so no log either: the
        three reasons for the header (#57 section 9). Every other route still
        refuses it.
        """
        if secrets.compare_digest(headers.get(b"authorization", b""), self.expected):
            return True
        if scope.get("method") not in ("GET", "HEAD") or not _MEDIA.fullmatch(scope["path"]):
            return False
        query = parse_qs(scope["query_string"].decode("latin-1")).get("t", [])
        return len(query) == 1 and secrets.compare_digest(query[0].encode(), self.token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, bytes] = dict(scope["headers"])
        host = headers.get(b"host", b"").decode("latin-1").lower()
        if host not in self.hosts:
            # Says nothing about what was asked for, and nothing about the token.
            await JSONResponse({"detail": "Forbidden"}, status_code=403)(scope, receive, send)
            return
        path: str = scope["path"]
        if any(path == p or path.startswith(f"{p}/") for p in _GUARDED):
            if not self._carries_token(scope, headers):
                await JSONResponse(
                    {
                        "error": "Unauthorized",
                        "message": "This request did not carry the dsj ui token. Open the "
                        "address `dsj ui` printed, including the part after #.",
                        "request": path,
                    },
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
            # Any request from the page shows it is open, not only the beat.
            self.heartbeat.beat()
        await self.app(scope, receive, send)


async def failed(request: Request, exc: Exception) -> JSONResponse:
    """Any error a route raises, as the one shape the page's error dialog reads (#82)."""
    status, body = describe(exc, request.url.path)
    return JSONResponse(body, status_code=status)


def heartbeat() -> None:
    """The page is still open. The guard has already counted the request."""


def create_app(
    port: int, *, token: str | None = None, extra_ports: tuple[int, ...] = ()
) -> tuple[FastAPI, str]:
    """Build the app for a server about to listen on `port`, and its token.

    `extra_ports` are other loopback ports whose `Host` is accepted too: only
    `dev_app()` uses it, for Vite's dev server, which passes the browser's own
    `Host` through to this one. The app's Heartbeat is `app.state.heartbeat`.

    Raises:
        UIUnavailable: when the built page is not where the package expects it.
    """
    if not (STATIC / "index.html").is_file():
        raise UIUnavailable(
            f"the built page is missing: there is no index.html in {STATIC}. "
            f"From a clone, `just ui-build` writes it."
        )
    token = token or secrets.token_urlsafe(32)
    hosts = frozenset(
        f"{name}:{p}" for p in (port, *extra_ports) for name in (HOST, "localhost")
    )
    # No /docs or /redoc: they load their scripts from a CDN, and nothing about
    # this app may reach off the machine. /openapi.json stays, for #155.
    app = FastAPI(title="dsj", docs_url=None, redoc_url=None)
    app.state.heartbeat = Heartbeat()
    app.state.jobs = Jobs(app.state.heartbeat.hold)
    app.include_router(recording.router)
    app.include_router(media.router)
    app.include_router(jobs.router)
    app.add_api_route("/api/heartbeat", heartbeat, methods=["POST"], status_code=204)
    # Last, so every /api route above wins over a file of the same name.
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    # dsj's own errors are answered quietly with their status. Anything else
    # takes the Exception handler, which Starlette runs in its outermost layer
    # and then re-raises, so the traceback still reaches the terminal.
    for cls in STATUS:
        app.add_exception_handler(cls, failed)
    app.add_exception_handler(Exception, failed)
    # No CORSMiddleware, ever (rule 4). Its absence is the defence.
    app.add_middleware(_Guard, hosts=hosts, token=token, heartbeat=app.state.heartbeat)
    return app, token


def lock_path() -> Path:
    """Where a running `dsj ui` says where it listens: beside the library it serves."""
    return library_path().parent / "ui.lock"


def _take_lock(path: Path) -> int | None:
    """Hold the lock for this process: the descriptor, or None if another `dsj ui` has it.

    An flock(2), as dsj/runlock.py's for `dsj suno`, and for the same reason:
    the kernel drops it however the holder ends, `kill -9` included, so a
    crashed server never locks the next one out and no pid has to be judged.
    Mode 0600, because the file will hold the token.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    return fd


def _running_url(path: Path) -> str:
    """The URL the `dsj ui` holding the lock at `path` printed."""
    deadline = time.monotonic() + _HOLDER_WAIT_S
    while True:
        with contextlib.suppress(OSError, ValueError):
            holder: object = json.loads(path.read_text())
            if isinstance(holder, dict):
                url = cast("dict[str, object]", holder).get("url")
                if isinstance(url, str):
                    return url
        if time.monotonic() >= deadline:
            raise UIUnavailable(
                f"another dsj ui holds {path} but has not written where it listens. "
                f"If it is stuck, find it with `lsof {path}` and stop it, then run this again."
            )
        time.sleep(0.05)


def _write_holder(fd: int, holder: dict[str, object]) -> None:
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, json.dumps(holder).encode())


def _watch(server: uvicorn.Server, beats: Heartbeat, idle_s: float, done: threading.Event) -> None:
    """Stop `server` once no page has been heard from for `idle_s` seconds."""
    while not done.wait(min(1.0, idle_s / 4)):
        if beats.idle_s() >= idle_s:
            print(
                f"No dsj page has been open for {idle_s:g} s, so dsj ui stopped.",
                file=sys.stderr, flush=True,
            )
            server.should_exit = True
            return


def serve(*, open_browser: bool, idle_s: float = IDLE_S) -> None:
    """Listen on a port the kernel picks, print the URL, and serve until idle or stopped.

    If another `dsj ui` is already serving this library, print its URL (and
    open it) instead, binding nothing.

    The socket is bound here rather than by uvicorn so the port is known before
    the app is built, with no window between choosing a free port and taking it.
    It is listening before the URL is printed, so anything that reads the URL
    and connects at once is queued, not refused.
    """
    lock = lock_path()
    fd = _take_lock(lock)
    if fd is None:
        url = _running_url(lock)
        print(url, flush=True)
        print(f"dsj ui is already running; this is its address ({lock}).",
              file=sys.stderr, flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((HOST, 0))
            sock.listen()
            port: int = sock.getsockname()[1]
            app, token = create_app(port)
            # After `#` the token never reaches a server, a log or a Referer;
            # the page reads it and wipes it from the address bar (#112).
            url = f"http://{HOST}:{port}/#t={token}"
            _write_holder(fd, {
                "url": url, "port": port, "pid": os.getpid(),
                "started": datetime.now(UTC).isoformat(timespec="seconds"),
            })
            # The URL alone on stdout, so `dsj ui --print-url` composes the way
            # `dsj dikhao` does; everything for a person goes to stderr.
            print(url, flush=True)
            print("dsj ui is serving; Ctrl-C stops it.", file=sys.stderr, flush=True)
            if open_browser:
                webbrowser.open(url)
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            done = threading.Event()
            watchdog = threading.Thread(
                target=_watch, args=(server, app.state.heartbeat, idle_s, done), daemon=True
            )
            watchdog.start()
            try:
                # uvicorn shuts down cleanly on Ctrl-C or SIGTERM and then
                # re-raises the signal, so the exit code is the one the shell
                # expects for it: 130 or 143. The watchdog's stop returns here.
                server.run(sockets=[sock])
            finally:
                done.set()
    finally:
        # Emptied, not deleted: the token goes with the server, and deleting a
        # file another `dsj ui` may be waiting to flock would let two run.
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
        os.close(fd)


def dev_app() -> FastAPI:
    """The app for `just ui-dev`: uvicorn --reload on 8721, behind Vite on 5173.

    Vite passes the browser's own `Host` (port 5173) through, so that is let in
    as well. The token is `DSJ_UI_DEV_TOKEN` when set, so it survives each
    reload; the URL to open is printed either way. No watchdog runs here.
    """
    app, token = create_app(8721, token=os.environ.get("DSJ_UI_DEV_TOKEN"), extra_ports=(5173,))

    def say_where() -> None:
        print(f"dsj ui dev: open http://{HOST}:5173/#t={token}", file=sys.stderr, flush=True)

    # On startup, not here: `just api` builds this app only to read its OpenAPI
    # description, and a URL for a server nobody started would mislead.
    app.router.on_startup.append(say_where)
    return app
