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
  6. The page heartbeats, and the process exits after three minutes without one,
     or BYE_S after the last open page says it is going away (#206). A lock
     file lets a second `dsj ui` find the first instead of binding a rival.
"""

from __future__ import annotations

__all__ = [
    "BYE_S",
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
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager
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
from dsj.ui.routes import jobs, marks, media, recording
from dsj.ui.store import library_path

# Committed, and inside the package, so an install carries the page with no
# Node on the machine. `just ui-build` writes it from ui/ (#57 section 8).
STATIC = Path(__file__).resolve().parent / "static"

# Loopback only, never 0.0.0.0: the page is for this machine (#57 section 9).
HOST = "127.0.0.1"

# How long the server outlives the last sign of a page, in seconds (#112 rule 6).
# The page beats every 15 s while it is in front. Behind another tab, Chromium
# holds that timer to one beat a minute: measured 2026-10-02 (#204), gaps of
# 59.9 to 61.0 s over two runs, and a one-minute cutoff stopped the server
# 531 s after the tab was hidden. Three minutes rides out one of those beats going missing
# with a minute to spare (tests/test_ui_server.py replays the measured beats).
# A closed window does not wait this long: its page says goodbye (BYE_S below).
IDLE_S = 180.0

# How long the server outlives a page that said it was going away, the last one
# open (#206). The page says so on `pagehide`, which also fires when it moves
# between the library and a transcript, or reloads: those are page loads, and
# the next page's first beat has to land inside this to cancel the stop. A
# window closed for good stops the server this long after, well inside the 60 s
# #57 asks for, where the cutoff alone took up to three minutes.
BYE_S = 10.0

# The header each page puts on its requests: an id it makes when it loads, so a
# goodbye from one tab does not stop the server under another still open.
PAGE_HEADER = "x-dsj-page"

# The prefixes whose requests must carry the token. The page and its assets
# are everything else, and are served to any loopback request (#112 rule 2).
_GUARDED = ("/api", "/media")

# The routes whose requests come from a media element, which sends no headers
# of its own: GET or HEAD of a recording's file (dsj/ui/routes/media.py), and
# of a finished bleep render's (#215, dsj/ui/routes/jobs.py).
_MEDIA = re.compile(r"/api/(?:recording|renders)/[^/]+/media")

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
        # When each page was last heard from, by the id it sends (PAGE_HEADER).
        self._pages: dict[str, float] = {}
        # When the last page said it was going, until anything is heard again.
        self._bye: float | None = None
        self._lock = threading.Lock()

    def beat(self, page: str | None = None) -> None:
        """A page is still there: any request cancels a goodbye before it."""
        with self._lock:
            self._last = self._clock()
            self._bye = None
            if page:
                self._pages[page] = self._last

    def bye(self, page: str | None) -> None:
        """`page` is going away: a page load, a reload, or the window closing (#206)."""
        with self._lock:
            if page:
                self._pages.pop(page, None)
            self._bye = self._clock()

    def gone_s(self, idle_s: float) -> float | None:
        """Seconds since the last open page said it was going, or None.

        None while nothing has said goodbye since the last request, while a job
        holds the server, or while another page was heard from within `idle_s`:
        a tab hidden behind another beats only once a minute (#204), and closing
        a second tab must not stop the server under it. When that page closes
        too it says so; if it never does, the `idle_s` cutoff still applies.
        """
        with self._lock:
            if self._bye is None or self._holds:
                return None
            now = self._clock()
            if any(now - seen < idle_s for seen in self._pages.values()):
                return None
            return now - self._bye

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
            # A media element's carries no page id, and still counts.
            page = headers.get(PAGE_HEADER.encode())
            self.heartbeat.beat(page.decode("latin-1") if page else None)
        await self.app(scope, receive, send)


async def failed(request: Request, exc: Exception) -> JSONResponse:
    """Any error a route raises, as the one shape the page's error dialog reads (#82)."""
    status, body = describe(exc, request.url.path)
    return JSONResponse(body, status_code=status)


def heartbeat() -> None:
    """The page is still open. The guard has already counted the request."""


def bye(request: Request) -> None:
    """The page is going away (#206). The server stops BYE_S later unless a page beats.

    Sent by the page on `pagehide` with `fetch(..., {keepalive: true})`, which
    outlives the page and, unlike `sendBeacon`, carries the token header.
    """
    beats = cast("Heartbeat", request.app.state.heartbeat)
    beats.bye(request.headers.get(PAGE_HEADER))


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
    # The lifespan is where the server's own state is let go of, as uvicorn
    # stops (Ctrl-C, SIGTERM, the watchdog's idle stop): the jobs' status folder
    # in the temp folder (#242).
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            app.state.jobs.close()

    app = FastAPI(title="dsj", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.heartbeat = Heartbeat()
    app.state.jobs = Jobs(app.state.heartbeat.hold)
    app.include_router(recording.router)
    app.include_router(media.router)
    app.include_router(jobs.router)
    app.include_router(marks.router)
    app.add_api_route("/api/heartbeat", heartbeat, methods=["POST"], status_code=204)
    app.add_api_route("/api/bye", bye, methods=["POST"], status_code=204)
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


def _watch(
    server: uvicorn.Server, beats: Heartbeat, idle_s: float, bye_s: float, done: threading.Event
) -> None:
    """Stop `server` when the last open page has gone.

    Gone is `bye_s` after it said so, or `idle_s` without a sign of any page.
    """
    while not done.wait(min(1.0, idle_s / 4, bye_s / 4)):
        gone = beats.gone_s(idle_s)
        if gone is not None and gone >= bye_s:
            why = "The dsj page was closed"
        elif beats.idle_s() >= idle_s:
            why = f"No dsj page has been open for {idle_s:g} s"
        else:
            continue
        # The stop first, the sentence after. Whoever started dsj ui may be gone,
        # and with it the reader of stderr: the print then raises BrokenPipeError,
        # and when it came first that killed this thread before the stop, so the
        # server ran on with nobody to stop it (an e2e run that timed out, #206).
        server.should_exit = True
        with contextlib.suppress(OSError):
            print(f"{why}, so dsj ui stopped.", file=sys.stderr, flush=True)
        return


def serve(*, open_browser: bool, idle_s: float = IDLE_S, bye_s: float = BYE_S) -> None:
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
                target=_watch, args=(server, app.state.heartbeat, idle_s, bye_s, done),
                daemon=True,
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
    # description, and a URL for a server nobody started would mislead. Wrapped
    # round the app's own lifespan, because a router that has one ignores its
    # on_startup handlers.
    serving = app.router.lifespan_context

    @asynccontextmanager
    async def announced(a: FastAPI) -> AsyncGenerator[None]:
        say_where()
        async with serving(a):
            yield

    app.router.lifespan_context = announced
    return app
